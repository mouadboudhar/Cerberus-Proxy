import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from cerberus_proxy.auth.models import ApiKey, Base

WINDOWS = ("minute", "hour", "day")


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"

    key_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("api_keys.id"), primary_key=True
    )
    window: Mapped[str] = mapped_column(String(10), primary_key=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _window_start(window: str, now: datetime | None = None) -> datetime:
    n = now or _now()
    if window == "minute":
        return n.replace(second=0, microsecond=0)
    if window == "hour":
        return n.replace(minute=0, second=0, microsecond=0)
    if window == "day":
        return n.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unknown window: {window}")


def _resets_in(window: str, now: datetime | None = None) -> int:
    n = now or _now()
    start = _window_start(window, n)
    if window == "minute":
        nxt = start + timedelta(minutes=1)
    elif window == "hour":
        nxt = start + timedelta(hours=1)
    else:
        nxt = start + timedelta(days=1)
    return max(0, int((nxt - n).total_seconds()))


def effective_limits(key_record: ApiKey) -> dict[str, int]:
    return {
        "minute": key_record.rate_limit_rpm
        or int(os.getenv("CERBERUS_DEFAULT_RPM", "60")),
        "hour": key_record.rate_limit_rph
        or int(os.getenv("CERBERUS_DEFAULT_RPH", "1000")),
        "day": key_record.rate_limit_rpd
        or int(os.getenv("CERBERUS_DEFAULT_RPD", "10000")),
    }


class TokenBucket:
    async def check_and_increment(
        self,
        session: AsyncSession,
        key_id: int,
        window: str,
        limit: int,
    ) -> tuple[bool, int]:
        # SQLite serializes writers; the surrounding transaction makes the
        # read-modify-write sequence atomic across concurrent requests.
        current_start = _window_start(window)
        bucket = await session.get(RateLimitBucket, (key_id, window))

        if bucket is None:
            bucket = RateLimitBucket(
                key_id=key_id,
                window=window,
                tokens_used=0,
                window_start=current_start,
            )
            session.add(bucket)
        elif bucket.window_start < current_start:
            bucket.tokens_used = 0
            bucket.window_start = current_start

        if bucket.tokens_used >= limit:
            await session.flush()
            return (False, 0)

        bucket.tokens_used += 1
        await session.flush()
        return (True, limit - bucket.tokens_used)

    async def get_usage(
        self, session: AsyncSession, key_id: int
    ) -> dict[str, dict[str, int]]:
        key = await session.get(ApiKey, key_id)
        if key is None:
            raise ValueError(f"unknown key_id: {key_id}")
        limits = effective_limits(key)
        now = _now()
        out: dict[str, dict[str, int]] = {}
        for window in WINDOWS:
            bucket = await session.get(RateLimitBucket, (key_id, window))
            start = _window_start(window, now)
            used = (
                bucket.tokens_used
                if bucket is not None and bucket.window_start >= start
                else 0
            )
            out[window] = {
                "used": used,
                "limit": limits[window],
                "resets_in": _resets_in(window, now),
            }
        return out
