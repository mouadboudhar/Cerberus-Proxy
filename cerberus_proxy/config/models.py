import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cerberus_proxy.auth.models import Base, _utcnow


def _json_list(raw: str | None) -> list[str]:
    """Parse a stored JSON array of strings, returning [] on null/garbage."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, list) else []


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    upstream_url: Mapped[str] = mapped_column(String(512), nullable=False)
    default_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    kb_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kb_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    kb_collection: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kb_top_k: Mapped[int] = mapped_column(
        Integer, default=4, server_default="4", nullable=False
    )
    # Per-endpoint guard config (Stage 14b). JSON arrays of strings; NULL means
    # "use the default" (all rules on, no custom phrases, all languages).
    disabled_input_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_blocked_phrases: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_languages: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def has_knowledge_base(self) -> bool:
        return bool(self.kb_type and self.kb_url)

    @property
    def get_disabled_input_rules(self) -> list[str]:
        return _json_list(self.disabled_input_rules)

    @property
    def get_custom_blocked_phrases(self) -> list[str]:
        return _json_list(self.custom_blocked_phrases)

    @property
    def get_active_languages(self) -> list[str]:
        return _json_list(self.active_languages)
