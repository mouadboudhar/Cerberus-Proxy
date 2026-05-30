from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from cerberus_proxy.audit.models import AuditEvent
from cerberus_proxy.auth.models import ApiKey, _utcnow
from cerberus_proxy.config.models import Endpoint


class AuditRepository(ABC):
    @abstractmethod
    async def record(self, event: AuditEvent) -> None: ...

    @abstractmethod
    async def query(
        self,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        key_id: int | None = None,
        endpoint_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]: ...

    @abstractmethod
    async def count(
        self,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        key_id: int | None = None,
        endpoint_id: int | None = None,
    ) -> int: ...

    @abstractmethod
    async def get_stats(self, hours: int = 24) -> dict[str, Any]: ...

    @abstractmethod
    async def get_stats_by_endpoint(
        self, endpoint_id: int, hours: int = 24
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_summary_stats(self) -> dict[str, Any]: ...

    @abstractmethod
    async def get_by_id(self, event_id: int) -> AuditEvent | None: ...


class SQLiteAuditRepository(AuditRepository):
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    def _apply_filters(
        self,
        stmt,
        from_ts: datetime | None,
        to_ts: datetime | None,
        event_type: str | None,
        severity: str | None,
        key_id: int | None,
        endpoint_id: int | None,
    ):
        if from_ts is not None:
            stmt = stmt.where(AuditEvent.timestamp >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(AuditEvent.timestamp <= to_ts)
        if event_type is not None:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if severity is not None:
            stmt = stmt.where(AuditEvent.severity == severity)
        if key_id is not None:
            stmt = stmt.where(AuditEvent.key_id == key_id)
        if endpoint_id is not None:
            stmt = stmt.where(AuditEvent.endpoint_id == endpoint_id)
        return stmt

    async def record(self, event: AuditEvent) -> None:
        async with self._session_factory() as session:
            session.add(event)
            await session.commit()

    async def query(
        self,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        key_id: int | None = None,
        endpoint_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        async with self._session_factory() as session:
            stmt = select(AuditEvent)
            stmt = self._apply_filters(
                stmt, from_ts, to_ts, event_type, severity, key_id, endpoint_id
            )
            stmt = stmt.order_by(AuditEvent.timestamp.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count(
        self,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        key_id: int | None = None,
        endpoint_id: int | None = None,
    ) -> int:
        async with self._session_factory() as session:
            stmt = select(func.count(AuditEvent.id))
            stmt = self._apply_filters(
                stmt, from_ts, to_ts, event_type, severity, key_id, endpoint_id
            )
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    async def get_by_id(self, event_id: int) -> AuditEvent | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AuditEvent).where(AuditEvent.id == event_id)
            )
            return result.scalar_one_or_none()

    async def get_stats_by_endpoint(
        self, endpoint_id: int, hours: int = 24
    ) -> dict[str, Any]:
        # REQUEST_COMPLETE carries no endpoint_id, so per-endpoint request volume
        # is measured from UPSTREAM_REQUEST events (which do) plus blocked guards.
        from_ts = _utcnow() - timedelta(hours=hours)
        blocked_types = ("INPUT_GUARD_BLOCKED", "OUTPUT_GUARD_BLOCKED")

        async with self._session_factory() as session:
            total_stmt = (
                select(func.count(AuditEvent.id))
                .where(AuditEvent.endpoint_id == endpoint_id)
                .where(AuditEvent.event_type == "UPSTREAM_REQUEST")
            )
            requests_total = int((await session.execute(total_stmt)).scalar_one() or 0)

            today_stmt = total_stmt.where(AuditEvent.timestamp >= from_ts)
            requests_today = int((await session.execute(today_stmt)).scalar_one() or 0)

            blocked_stmt = (
                select(func.count(AuditEvent.id))
                .where(AuditEvent.endpoint_id == endpoint_id)
                .where(AuditEvent.event_type.in_(blocked_types))
                .where(AuditEvent.timestamp >= from_ts)
            )
            blocked_today = int((await session.execute(blocked_stmt)).scalar_one() or 0)

            avg_stmt = (
                select(func.avg(AuditEvent.latency_ms))
                .where(AuditEvent.endpoint_id == endpoint_id)
                .where(AuditEvent.event_type == "UPSTREAM_REQUEST")
                .where(AuditEvent.timestamp >= from_ts)
            )
            avg_raw = (await session.execute(avg_stmt)).scalar_one()
            avg_latency_ms = int(avg_raw) if avg_raw is not None else 0

        return {
            "requests_today": requests_today,
            "requests_total": requests_total,
            "blocked_today": blocked_today,
            "avg_latency_ms": avg_latency_ms,
        }

    async def get_summary_stats(self) -> dict[str, Any]:
        # Aggregate across all endpoints. requests_today/blocked_today use a
        # rolling 24h window (consistent with get_stats); total is all-time.
        from_ts = _utcnow() - timedelta(hours=24)
        blocked_types = ("INPUT_GUARD_BLOCKED", "OUTPUT_GUARD_BLOCKED")

        async with self._session_factory() as session:
            total_stmt = select(func.count(AuditEvent.id)).where(
                AuditEvent.event_type == "REQUEST_COMPLETE"
            )
            total_requests = int((await session.execute(total_stmt)).scalar_one() or 0)

            today_stmt = total_stmt.where(AuditEvent.timestamp >= from_ts)
            requests_today = int((await session.execute(today_stmt)).scalar_one() or 0)

            blocked_stmt = (
                select(func.count(AuditEvent.id))
                .where(AuditEvent.event_type.in_(blocked_types))
                .where(AuditEvent.timestamp >= from_ts)
            )
            blocked_today = int((await session.execute(blocked_stmt)).scalar_one() or 0)

            avg_stmt = (
                select(func.avg(AuditEvent.latency_ms))
                .where(AuditEvent.event_type == "REQUEST_COMPLETE")
                .where(AuditEvent.timestamp >= from_ts)
            )
            avg_raw = (await session.execute(avg_stmt)).scalar_one()
            avg_latency_ms = int(avg_raw) if avg_raw is not None else 0

            endpoints_stmt = select(func.count(Endpoint.id)).where(
                Endpoint.is_active.is_(True)
            )
            active_endpoints = int(
                (await session.execute(endpoints_stmt)).scalar_one() or 0
            )

            keys_stmt = select(func.count(ApiKey.id)).where(
                ApiKey.revoked_at.is_(None)
            )
            active_keys = int((await session.execute(keys_stmt)).scalar_one() or 0)

        return {
            "total_requests": total_requests,
            "requests_today": requests_today,
            "blocked_today": blocked_today,
            "avg_latency_ms": avg_latency_ms,
            "active_endpoints": active_endpoints,
            "active_keys": active_keys,
        }

    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        from_ts = _utcnow() - timedelta(hours=hours)
        blocked_types = ("INPUT_GUARD_BLOCKED", "OUTPUT_GUARD_BLOCKED")

        async with self._session_factory() as session:
            total_stmt = (
                select(func.count(AuditEvent.id))
                .where(AuditEvent.timestamp >= from_ts)
                .where(AuditEvent.event_type == "REQUEST_COMPLETE")
            )
            requests_total = int((await session.execute(total_stmt)).scalar_one() or 0)

            blocked_stmt = (
                select(func.count(AuditEvent.id))
                .where(AuditEvent.timestamp >= from_ts)
                .where(AuditEvent.event_type.in_(blocked_types))
            )
            requests_blocked = int((await session.execute(blocked_stmt)).scalar_one() or 0)

            redacted_stmt = (
                select(func.count(AuditEvent.id))
                .where(AuditEvent.timestamp >= from_ts)
                .where(AuditEvent.event_type == "OUTPUT_GUARD_REDACTED")
            )
            requests_redacted = int((await session.execute(redacted_stmt)).scalar_one() or 0)

            avg_stmt = (
                select(func.avg(AuditEvent.latency_ms))
                .where(AuditEvent.timestamp >= from_ts)
                .where(AuditEvent.event_type == "REQUEST_COMPLETE")
            )
            avg_raw = (await session.execute(avg_stmt)).scalar_one()
            avg_latency_ms = int(avg_raw) if avg_raw is not None else 0

            top_stmt = (
                select(AuditEvent.event_type, func.count(AuditEvent.id).label("c"))
                .where(AuditEvent.timestamp >= from_ts)
                .group_by(AuditEvent.event_type)
                .order_by(func.count(AuditEvent.id).desc())
                .limit(10)
            )
            top_rows = (await session.execute(top_stmt)).all()
            top_event_types = [{"type": r[0], "count": int(r[1])} for r in top_rows]

            hour_expr = func.strftime("%Y-%m-%dT%H:00:00", AuditEvent.timestamp)
            hour_stmt = (
                select(hour_expr.label("h"), func.count(AuditEvent.id).label("c"))
                .where(AuditEvent.timestamp >= from_ts)
                .where(AuditEvent.event_type == "REQUEST_COMPLETE")
                .group_by("h")
                .order_by("h")
            )
            hour_rows = (await session.execute(hour_stmt)).all()
            requests_by_hour = [{"hour": r[0], "count": int(r[1])} for r in hour_rows]

        return {
            "requests_total": requests_total,
            "requests_blocked": requests_blocked,
            "requests_redacted": requests_redacted,
            "avg_latency_ms": avg_latency_ms,
            "top_event_types": top_event_types,
            "requests_by_hour": requests_by_hour,
        }
