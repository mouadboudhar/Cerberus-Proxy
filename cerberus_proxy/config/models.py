from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cerberus_proxy.auth.models import Base, _utcnow


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
