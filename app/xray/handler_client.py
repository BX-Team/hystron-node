import logging

import grpc

from app.gen import (
    xray_handler_pb2,
    xray_handler_pb2_grpc,
    xray_user_pb2,
    xray_typed_message_pb2,
    xray_vless_account_pb2,
    xray_trojan_account_pb2,
)

logger = logging.getLogger(__name__)

# Full protobuf type names used in TypedMessage.type
_TYPE_ADD_USER_OP = "xray.app.proxyman.command.AddUserOperation"
_TYPE_REMOVE_USER_OP = "xray.app.proxyman.command.RemoveUserOperation"
_TYPE_VLESS_ACCOUNT = "xray.proxy.vless.Account"
_TYPE_TROJAN_ACCOUNT = "xray.proxy.trojan.Account"


def _make_typed_message(type_name: str, message) -> xray_typed_message_pb2.TypedMessage:
    return xray_typed_message_pb2.TypedMessage(
        type=type_name,
        value=message.SerializeToString(),
    )


def _build_account(protocol: int, uuid: str, password: str, flow: str):
    """Build the protocol-specific account proto and return (type_name, proto_message)."""
    from app.gen import hystron_node_pb2

    if protocol == hystron_node_pb2.VLESS:
        account = xray_vless_account_pb2.Account(
            id=uuid,
            flow=flow,
            encryption="none",
        )
        return _TYPE_VLESS_ACCOUNT, account

    if protocol == hystron_node_pb2.TROJAN:
        account = xray_trojan_account_pb2.Account(password=password)
        return _TYPE_TROJAN_ACCOUNT, account

    raise ValueError(f"Unsupported protocol: {protocol}")


class HandlerClient:
    def __init__(self, api_addr: str, tag_protocol_map: dict[str, int] | None = None) -> None:
        self._addr = api_addr
        self._tag_protocol_map = tag_protocol_map or {}
        self._channel: grpc.aio.Channel | None = None
        self._stub: xray_handler_pb2_grpc.HandlerServiceStub | None = None

    async def connect(self) -> None:
        self._channel = grpc.aio.insecure_channel(self._addr)
        self._stub = xray_handler_pb2_grpc.HandlerServiceStub(self._channel)

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()

    async def add_user(
        self,
        inbound_tag: str,
        protocol: int,
        username: str,
        uuid: str = "",
        password: str = "",
        flow: str = "",
    ) -> None:
        """Add a user to the specified xray inbound."""
        assert self._stub is not None, "HandlerClient not connected"

        # Prefer the protocol derived from the local xray config over the one
        # sent by the panel, which may default to VLESS (0) when unset.
        resolved_protocol = self._tag_protocol_map.get(inbound_tag, protocol)

        account_type, account_proto = _build_account(resolved_protocol, uuid, password, flow)

        user = xray_user_pb2.User(
            level=0,
            email=username,
            account=_make_typed_message(account_type, account_proto),
        )
        op = xray_handler_pb2.AddUserOperation(user=user)
        operation_tm = _make_typed_message(_TYPE_ADD_USER_OP, op)

        request = xray_handler_pb2.AlterInboundRequest(tag=inbound_tag, operation=operation_tm)
        try:
            await self._stub.AlterInbound(request)
            logger.debug("Added user '%s' to inbound '%s'", username, inbound_tag)
        except grpc.RpcError as exc:
            if "already exists" in (exc.details() or ""):
                logger.debug("User '%s' already exists in inbound '%s', skipping", username, inbound_tag)
                return
            logger.error(
                "HandlerService.AlterInbound (AddUser) failed for user '%s' tag '%s': %s",
                username,
                inbound_tag,
                exc,
            )
            raise

    async def remove_user(self, inbound_tag: str, username: str) -> None:
        """Remove a user from the specified xray inbound (by email=username)."""
        assert self._stub is not None, "HandlerClient not connected"

        op = xray_handler_pb2.RemoveUserOperation(email=username)
        operation_tm = _make_typed_message(_TYPE_REMOVE_USER_OP, op)

        request = xray_handler_pb2.AlterInboundRequest(tag=inbound_tag, operation=operation_tm)
        try:
            await self._stub.AlterInbound(request)
            logger.debug("Removed user '%s' from inbound '%s'", username, inbound_tag)
        except grpc.RpcError as exc:
            logger.error(
                "HandlerService.AlterInbound (RemoveUser) failed for user '%s' tag '%s': %s",
                username,
                inbound_tag,
                exc,
            )
            raise
