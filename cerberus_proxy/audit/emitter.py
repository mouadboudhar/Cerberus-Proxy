import asyncio
import logging
from typing import Any

from cerberus_proxy.audit.broadcaster import Broadcaster
from cerberus_proxy.audit.models import AuditEvent, EventType
from cerberus_proxy.audit.repository import AuditRepository

logger = logging.getLogger("cerberus_proxy.audit")

_repository: AuditRepository | None = None
_broadcaster: Broadcaster | None = None


def init_emitter(repository: AuditRepository, broadcaster: Broadcaster) -> None:
    global _repository, _broadcaster
    _repository = repository
    _broadcaster = broadcaster


def reset_emitter() -> None:
    global _repository, _broadcaster
    _repository = None
    _broadcaster = None


def get_repository() -> AuditRepository | None:
    return _repository


def get_broadcaster() -> Broadcaster | None:
    return _broadcaster


async def _safe_record(repository: AuditRepository, event: AuditEvent) -> None:
    try:
        await repository.record(event)
    except Exception:  # noqa: BLE001
        logger.exception("audit record failed")


async def _safe_broadcast(broadcaster: Broadcaster, event: AuditEvent) -> None:
    try:
        await broadcaster.broadcast(event)
    except Exception:  # noqa: BLE001
        logger.exception("audit broadcast failed")


async def emit(
    event_type: EventType,
    severity: str = "INFO",
    key_id: int | None = None,
    endpoint_id: int | None = None,
    detail: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    request_id: str | None = None,
) -> None:
    try:
        event = AuditEvent(
            event_type=event_type.value if isinstance(event_type, EventType) else str(event_type),
            severity=severity,
            key_id=key_id,
            endpoint_id=endpoint_id,
            latency_ms=latency_ms,
            request_id=request_id,
        )
        event.set_detail(detail)

        if _repository is not None:
            asyncio.create_task(_safe_record(_repository, event))
        if _broadcaster is not None:
            asyncio.create_task(_safe_broadcast(_broadcaster, event))
    except Exception:  # noqa: BLE001
        logger.exception("audit emit failed")
