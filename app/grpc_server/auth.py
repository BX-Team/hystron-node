import hmac
import logging

import grpc

logger = logging.getLogger(__name__)

_API_KEY_METADATA = "x-api-key"


class ApiKeyInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def intercept_service(self, continuation, handler_call_details):
        # Extract x-api-key from metadata
        metadata = dict(handler_call_details.invocation_metadata or [])
        provided_key = metadata.get(_API_KEY_METADATA, "")

        if not hmac.compare_digest(provided_key.encode(), self._api_key.encode()):
            logger.warning(
                "Rejected unauthenticated gRPC call to %s",
                handler_call_details.method,
            )
            return _abort_handler(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing API key")

        return await continuation(handler_call_details)


def _abort_handler(status_code: grpc.StatusCode, details: str):
    async def abort(request, context):
        await context.abort(status_code, details)

    return grpc.unary_unary_rpc_method_handler(abort)
