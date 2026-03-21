import logging

import grpc

from app.gen import xray_stats_pb2, xray_stats_pb2_grpc

logger = logging.getLogger(__name__)

# Xray stat name format:
#   user>>>USERNAME>>>traffic>>>uplink
#   user>>>USERNAME>>>traffic>>>downlink
_SEP = ">>>"
_TRAFFIC_PREFIX = "user" + _SEP


def _parse_stats(stats: list) -> dict[str, tuple[int, int]]:
    """Parse xray QueryStatsResponse into {username: (tx, rx)}."""
    result: dict[str, tuple[int, int]] = {}
    for stat in stats:
        name: str = stat.name
        if not name.startswith(_TRAFFIC_PREFIX):
            continue
        # user>>>USERNAME>>>traffic>>>uplink  →  ["USERNAME", "uplink"]
        rest = name[len(_TRAFFIC_PREFIX) :]
        # split on >>>traffic>>>
        parts = rest.split(_SEP + "traffic" + _SEP)
        if len(parts) != 2:
            continue
        username = parts[0]
        direction = parts[1]  # "uplink" or "downlink"
        tx, rx = result.get(username, (0, 0))
        if direction == "uplink":
            result[username] = (tx + stat.value, rx)
        elif direction == "downlink":
            result[username] = (tx, rx + stat.value)
    return result


class StatsClient:
    def __init__(self, api_addr: str) -> None:
        self._addr = api_addr
        self._channel: grpc.aio.Channel | None = None
        self._stub: xray_stats_pb2_grpc.StatsServiceStub | None = None

    async def connect(self) -> None:
        self._channel = grpc.aio.insecure_channel(self._addr)
        self._stub = xray_stats_pb2_grpc.StatsServiceStub(self._channel)

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()

    async def query(
        self,
        pattern: str = "user>>>",
        reset: bool = False,
    ) -> dict[str, tuple[int, int]]:
        """
        Query xray StatsService and return {username: (tx_bytes, rx_bytes)}.

        Args:
            pattern: Filter pattern for stat names. Default captures all users.
            reset: If True, xray resets counters after returning them.
        """
        assert self._stub is not None, "StatsClient not connected"
        try:
            request = xray_stats_pb2.QueryStatsRequest(pattern=pattern, reset=reset)
            response = await self._stub.QueryStats(request)
            return _parse_stats(list(response.stat))
        except grpc.RpcError as exc:
            logger.error("StatsService.QueryStats failed: %s", exc)
            return {}
