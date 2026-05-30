import json
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cerberus_proxy.auth.models import Base, _utcnow


class EventType(str, Enum):
    AUTH_PASSED = "AUTH_PASSED"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMIT_PASSED = "RATE_LIMIT_PASSED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INPUT_GUARD_PASSED = "INPUT_GUARD_PASSED"
    INPUT_GUARD_BLOCKED = "INPUT_GUARD_BLOCKED"
    OUTPUT_GUARD_PASSED = "OUTPUT_GUARD_PASSED"
    OUTPUT_GUARD_REDACTED = "OUTPUT_GUARD_REDACTED"
    OUTPUT_GUARD_BLOCKED = "OUTPUT_GUARD_BLOCKED"
    UPSTREAM_REQUEST = "UPSTREAM_REQUEST"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    REQUEST_COMPLETE = "REQUEST_COMPLETE"
    ABUSE_SIGNAL = "ABUSE_SIGNAL"
    TRANSLATION_TIMEOUT = "TRANSLATION_TIMEOUT"


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    key_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("api_keys.id"), nullable=True
    )
    endpoint_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("endpoints.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def detail_dict(self) -> dict[str, Any] | None:
        if self.detail is None:
            return None
        try:
            return json.loads(self.detail)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_detail(self, value: dict[str, Any] | None) -> None:
        self.detail = json.dumps(value) if value is not None else None
