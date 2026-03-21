import asyncio
import logging
import os
import subprocess
import time

import grpc

logger = logging.getLogger(__name__)

_MAX_RESTART_DELAY = 30.0
_READY_POLL_INTERVAL = 0.5


class XrayProcess:
    def __init__(self, xray_bin: str, config_path: str, api_addr: str) -> None:
        self._bin = xray_bin
        self._config = config_path
        self._api_addr = api_addr
        self._proc: asyncio.subprocess.Process | None = None
        self._started_at: float = 0.0
        self._version: str = ""
        self._supervision_task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def version(self) -> str:
        return self._version

    def uptime_seconds(self) -> int:
        if not self.is_running():
            return 0
        return int(time.monotonic() - self._started_at)

    async def start(self) -> None:
        if not os.path.isfile(self._bin):
            raise FileNotFoundError(f"xray binary not found: {self._bin}")
        if not os.path.isfile(self._config):
            raise FileNotFoundError(f"xray config not found: {self._config}")
        self._version = await self._fetch_version()
        await self._spawn()
        self._supervision_task = asyncio.create_task(self._supervision_loop())

    async def stop(self) -> None:
        if self._supervision_task:
            self._supervision_task.cancel()
            try:
                await self._supervision_task
            except asyncio.CancelledError:
                pass
        await self._kill()

    async def wait_until_ready(self, timeout: float = 30.0) -> None:
        """Poll the xray gRPC API endpoint until it responds or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                channel = grpc.aio.insecure_channel(self._api_addr)
                await asyncio.wait_for(channel.channel_ready(), timeout=1.0)
                await channel.close()
                return
            except Exception:
                pass
            await asyncio.sleep(_READY_POLL_INTERVAL)
        raise TimeoutError(f"xray gRPC API at {self._api_addr} did not become ready within {timeout}s")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _fetch_version(self) -> str:
        try:
            result = subprocess.run([self._bin, "version"], capture_output=True, text=True, timeout=5)
            first_line = result.stdout.splitlines()[0] if result.stdout else ""
            # "Xray 1.8.x ..." → "1.8.x"
            parts = first_line.split()
            if len(parts) >= 2:
                return parts[1]
            return first_line
        except Exception as exc:
            logger.warning("Could not get xray version: %s", exc)
            return "unknown"

    async def _spawn(self) -> None:
        logger.info("Starting xray: %s -c %s", self._bin, self._config)
        self._proc = await asyncio.create_subprocess_exec(
            self._bin,
            "run",
            "-c",
            self._config,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._started_at = time.monotonic()
        asyncio.create_task(self._pipe_output())

    async def _pipe_output(self) -> None:
        assert self._proc and self._proc.stdout
        async for line in self._proc.stdout:
            logger.info("[xray] %s", line.decode().rstrip())

    async def _kill(self) -> None:
        if self._proc is None or self._proc.returncode is not None:
            return
        try:
            self._proc.terminate()
            await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("xray did not exit after SIGTERM, sending SIGKILL")
            self._proc.kill()
            await self._proc.wait()

    async def _supervision_loop(self) -> None:
        delay = 1.0
        while True:
            try:
                if self._proc:
                    await self._proc.wait()
                    code = self._proc.returncode
                    logger.error("xray exited unexpectedly (code=%s), restarting in %.1fs", code, delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, _MAX_RESTART_DELAY)
                    await self._spawn()
                    delay = 1.0  # reset after successful start
                else:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Supervision loop error: %s", exc)
                await asyncio.sleep(delay)
