import asyncio
import logging
import signal

from app.config import load_config
from app.grpc_server.server import GrpcServer
from app.grpc_server.servicer import HystronNodeServicer
from app.xray.config_validator import ConfigValidationError, load_tag_protocol_map, validate_xray_config
from app.xray.handler_client import HandlerClient
from app.xray.process import XrayProcess
from app.xray.stats_client import StatsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    # 1. Validate xray config
    try:
        validate_xray_config(config.xray_config_path, config.xray_api_addr)
    except ConfigValidationError as exc:
        logger.error("%s", exc)
        raise SystemExit(1)

    # 2. Start xray process
    process = XrayProcess(
        xray_bin=config.xray_bin,
        config_path=config.xray_config_path,
        api_addr=config.xray_api_addr,
    )
    try:
        await process.start()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        raise SystemExit(1)

    # 3. Wait for xray gRPC API to be ready
    logger.info("Waiting for xray gRPC API at %s ...", config.xray_api_addr)
    try:
        await process.wait_until_ready(timeout=30.0)
    except TimeoutError as exc:
        logger.error("%s", exc)
        await process.stop()
        raise SystemExit(1)
    logger.info("xray v%s is ready.", process.version())

    # 4. Connect internal gRPC clients to xray
    tag_protocol_map = load_tag_protocol_map(config.xray_config_path)
    logger.debug("Tag→protocol map: %s", tag_protocol_map)
    stats = StatsClient(config.xray_api_addr)
    handler = HandlerClient(config.xray_api_addr, tag_protocol_map=tag_protocol_map)
    await stats.connect()
    await handler.connect()

    # 5. Start the node gRPC server
    servicer = HystronNodeServicer(process=process, stats=stats, handler=handler)
    server = GrpcServer(config=config, servicer=servicer)
    await server.start()

    # 6. Register shutdown handlers
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal():
        logger.info("Shutdown signal received.")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    # 7. Run until stopped
    await stop_event.wait()

    logger.info("Shutting down...")
    await server.stop()
    await stats.close()
    await handler.close()
    await process.stop()
    logger.info("Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
