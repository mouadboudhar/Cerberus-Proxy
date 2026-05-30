from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cerberus_proxy.audit.emitter import emit
from cerberus_proxy.audit.models import EventType
from cerberus_proxy.auth.models import ApiKey
from cerberus_proxy.ratelimit.bucket import (
    WINDOWS,
    TokenBucket,
    _resets_in,
    effective_limits,
)

_bucket = TokenBucket()


async def check_rate_limits(
    request: Request,
    key_record: ApiKey,
    session: AsyncSession,
) -> Response | None:
    request_id = getattr(request.state, "request_id", None)
    limits = effective_limits(key_record)
    for window in WINDOWS:
        allowed, _ = await _bucket.check_and_increment(
            session, key_record.id, window, limits[window]
        )
        if not allowed:
            retry_after = _resets_in(window)
            await emit(
                EventType.RATE_LIMIT_EXCEEDED,
                severity="MEDIUM",
                key_id=key_record.id,
                detail={"window": window, "limit": limits[window]},
                request_id=request_id,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "window": window,
                    "limit": limits[window],
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
    await emit(
        EventType.RATE_LIMIT_PASSED,
        key_id=key_record.id,
        request_id=request_id,
    )
    return None
