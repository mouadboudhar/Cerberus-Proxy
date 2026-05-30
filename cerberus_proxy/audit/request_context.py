import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from cerberus_proxy.audit.emitter import emit
from cerberus_proxy.audit.models import EventType


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.request_id = str(uuid.uuid4())
        request.state.start_time = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            if request.url.path.startswith("/v1/"):
                latency_ms = int((time.monotonic() - request.state.start_time) * 1000)
                await emit(
                    EventType.REQUEST_COMPLETE,
                    latency_ms=latency_ms,
                    request_id=request.state.request_id,
                    key_id=getattr(request.state, "key_id", None),
                )
        return response
