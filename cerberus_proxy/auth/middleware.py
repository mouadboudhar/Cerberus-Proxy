from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from cerberus_proxy import db
from cerberus_proxy.audit.emitter import emit
from cerberus_proxy.audit.models import EventType
from cerberus_proxy.auth.keys import hash_key
from cerberus_proxy.auth.repository import SQLiteKeyRepository

# GET-only paths that don't require an API key.
_EXEMPT_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})
# The admin/dashboard surface authenticates with the dashboard token on each
# route (verify_dashboard_token), not the customer API key, so it bypasses this
# middleware entirely. /ws/* websockets already bypass BaseHTTPMiddleware.
_EXEMPT_PREFIXES = ("/api/", "/ws/")


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if (request.method == "GET" and path in _EXEMPT_PATHS) or path.startswith(
            _EXEMPT_PREFIXES
        ):
            return await call_next(request)

        request_id = getattr(request.state, "request_id", None)
        provided = request.headers.get("X-Cerberus-Key")
        if not provided:
            await emit(
                EventType.AUTH_FAILED,
                severity="HIGH",
                detail={"reason": "missing_key"},
                request_id=request_id,
            )
            return JSONResponse(
                status_code=401, content={"detail": "Missing X-Cerberus-Key header"}
            )

        key_hash = hash_key(provided)
        async with db.AsyncSessionLocal() as session:
            repo = SQLiteKeyRepository(session)
            api_key = await repo.get_by_hash(key_hash)
            if api_key is None:
                await emit(
                    EventType.AUTH_FAILED,
                    severity="HIGH",
                    detail={"reason": "invalid_key"},
                    request_id=request_id,
                )
                return JSONResponse(
                    status_code=401, content={"detail": "Invalid or revoked API key"}
                )
            key_id = api_key.id
            await repo.update_last_used(key_id)
            await session.commit()

        request.state.key_id = key_id
        request.state.key_record = api_key
        await emit(
            EventType.AUTH_PASSED,
            key_id=key_id,
            request_id=request_id,
        )
        return await call_next(request)
