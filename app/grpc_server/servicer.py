import logging
import time

import grpc

from app.config import VERSION
from app.gen import hystron_node_pb2, hystron_node_pb2_grpc
from app.xray.handler_client import HandlerClient
from app.xray.process import XrayProcess
from app.xray.stats_client import StatsClient

logger = logging.getLogger(__name__)


class HystronNodeServicer(hystron_node_pb2_grpc.HystronNodeServicer):
    def __init__(
        self,
        process: XrayProcess,
        stats: StatsClient,
        handler: HandlerClient,
    ) -> None:
        self._process = process
        self._stats = stats
        self._handler = handler

    # ── Status ────────────────────────────────────────────────────────────────

    async def GetStatus(self, request, context):
        return hystron_node_pb2.StatusResponse(
            xray_running=self._process.is_running(),
            xray_version=self._process.version(),
            node_version=VERSION,
            uptime_seconds=self._process.uptime_seconds(),
        )

    # ── Traffic ───────────────────────────────────────────────────────────────

    async def GetTrafficStats(self, request, context):
        raw = await self._stats.query(reset=False)
        stats = _build_traffic_stats(raw, list(request.usernames))
        return hystron_node_pb2.TrafficResponse(
            stats=stats,
            collected_at=int(time.time()),
        )

    async def ResetTrafficStats(self, request, context):
        await self._stats.query(reset=True)
        return hystron_node_pb2.ResetResponse(success=True)

    # ── User management ───────────────────────────────────────────────────────

    async def AddUser(self, request, context):
        errors: list[str] = []
        for tag in request.inbound_tags:
            try:
                await self._handler.add_user(
                    inbound_tag=tag,
                    protocol=request.protocol,
                    username=request.username,
                    uuid=request.uuid,
                    password=request.password,
                    flow=request.flow,
                )
            except grpc.RpcError as exc:
                errors.append(f"{tag}: {exc.details()}")
        if errors:
            return hystron_node_pb2.UserResponse(success=False, message="; ".join(errors))
        return hystron_node_pb2.UserResponse(success=True)

    async def RemoveUser(self, request, context):
        errors: list[str] = []
        for tag in request.inbound_tags:
            try:
                await self._handler.remove_user(inbound_tag=tag, username=request.username)
            except grpc.RpcError as exc:
                errors.append(f"{tag}: {exc.details()}")
        if errors:
            return hystron_node_pb2.UserResponse(success=False, message="; ".join(errors))
        return hystron_node_pb2.UserResponse(success=True)

    async def UpdateUser(self, request, context):
        # Best-effort: remove first, then add
        remove_req = hystron_node_pb2.RemoveUserRequest(
            username=request.username,
            inbound_tags=request.inbound_tags,
        )
        await self.RemoveUser(remove_req, context)
        return await self.AddUser(request, context)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_traffic_stats(
    raw: dict[str, tuple[int, int]],
    filter_usernames: list[str],
) -> list[hystron_node_pb2.UserTrafficStat]:
    if filter_usernames:
        items = [(u, raw[u]) for u in filter_usernames if u in raw]
    else:
        items = list(raw.items())
    return [hystron_node_pb2.UserTrafficStat(username=username, tx=tx, rx=rx) for username, (tx, rx) in items]
