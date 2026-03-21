import logging

import grpc

from app.config import Config
from app.gen import hystron_node_pb2_grpc
from app.grpc_server.auth import ApiKeyInterceptor
from app.grpc_server.servicer import HystronNodeServicer

logger = logging.getLogger(__name__)


class GrpcServer:
    def __init__(self, config: Config, servicer: HystronNodeServicer) -> None:
        self._config = config
        self._servicer = servicer
        self._server: grpc.aio.Server | None = None

    async def start(self) -> None:
        interceptors = [ApiKeyInterceptor(self._config.api_key)]
        self._server = grpc.aio.server(interceptors=interceptors)
        hystron_node_pb2_grpc.add_HystronNodeServicer_to_server(self._servicer, self._server)

        listen_addr = f"0.0.0.0:{self._config.grpc_port}"

        if self._config.grpc_tls_cert and self._config.grpc_tls_key:
            with open(self._config.grpc_tls_cert, "rb") as f:
                cert = f.read()
            with open(self._config.grpc_tls_key, "rb") as f:
                key = f.read()
            credentials = grpc.ssl_server_credentials([(key, cert)])
            self._server.add_secure_port(listen_addr, credentials)
            logger.info("gRPC server listening on %s (TLS)", listen_addr)
        else:
            self._server.add_insecure_port(listen_addr)
            logger.info("gRPC server listening on %s (plaintext)", listen_addr)

        await self._server.start()

    async def stop(self) -> None:
        if self._server:
            await self._server.stop(grace=5)

    async def wait_for_termination(self) -> None:
        if self._server:
            await self._server.wait_for_termination()
