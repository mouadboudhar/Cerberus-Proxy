import os
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cerberus_proxy.audit import models as _audit_models  # noqa: F401  (register AuditEvent on Base.metadata)
from cerberus_proxy.auth.models import Base
from cerberus_proxy.config import models as _config_models  # noqa: F401  (register Endpoint on Base.metadata)
from cerberus_proxy.ratelimit import bucket as _ratelimit_models  # noqa: F401  (register RateLimitBucket on Base.metadata)


def _database_url() -> str:
    raw = os.getenv("CERBERUS_DB_PATH", "sqlite+aiosqlite:///cerberus.db")
    if "://" in raw:
        return raw
    # Bare filesystem path from .env -> normalize to an async sqlite URL.
    if os.path.isabs(raw):
        return f"sqlite+aiosqlite:///{raw}"
    return f"sqlite+aiosqlite:///{raw.removeprefix('./')}"


DATABASE_URL = _database_url()

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_api_keys_rate_limits(conn)
        await _migrate_api_keys_endpoint_id(conn)
        await _migrate_endpoint_kb_columns(conn)
        await _migrate_endpoint_guard_columns(conn)
        await _migrate_endpoint_prompt_guard_columns(conn)


async def _migrate_api_keys_rate_limits(conn) -> None:
    # create_all doesn't ALTER existing tables; backfill rate-limit columns
    # on databases created before Stage 10.
    result = await conn.execute(text("PRAGMA table_info(api_keys)"))
    existing = {row[1] for row in result.fetchall()}
    for col in ("rate_limit_rpm", "rate_limit_rph", "rate_limit_rpd"):
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE api_keys ADD COLUMN {col} INTEGER"))


async def _migrate_api_keys_endpoint_id(conn) -> None:
    # Stage 12: bind keys to an endpoint (soft reference, no DB-level FK).
    result = await conn.execute(text("PRAGMA table_info(api_keys)"))
    existing = {row[1] for row in result.fetchall()}
    if "endpoint_id" not in existing:
        await conn.execute(text("ALTER TABLE api_keys ADD COLUMN endpoint_id INTEGER"))


async def _migrate_endpoint_kb_columns(conn) -> None:
    # Stage 12: knowledge-base config columns on endpoints.
    result = await conn.execute(text("PRAGMA table_info(endpoints)"))
    existing = {row[1] for row in result.fetchall()}
    coldefs = {
        "kb_type": "VARCHAR(50)",
        "kb_url": "VARCHAR(512)",
        "kb_collection": "VARCHAR(255)",
        "kb_top_k": "INTEGER NOT NULL DEFAULT 4",
    }
    for col, ddl in coldefs.items():
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE endpoints ADD COLUMN {col} {ddl}"))


async def _migrate_endpoint_guard_columns(conn) -> None:
    # Stage 14b: per-endpoint guard config columns (JSON arrays as TEXT).
    result = await conn.execute(text("PRAGMA table_info(endpoints)"))
    existing = {row[1] for row in result.fetchall()}
    for col in (
        "disabled_input_rules",
        "custom_blocked_phrases",
        "active_languages",
    ):
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE endpoints ADD COLUMN {col} TEXT"))


async def _migrate_endpoint_prompt_guard_columns(conn) -> None:
    # Stage 14c: optional LLM-as-judge prompt guard config columns.
    result = await conn.execute(text("PRAGMA table_info(endpoints)"))
    existing = {row[1] for row in result.fetchall()}
    coldefs = {
        "prompt_guard_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "prompt_guard_prompt": "TEXT",
        "prompt_guard_model": "VARCHAR(100)",
        "prompt_guard_action": "VARCHAR(20) NOT NULL DEFAULT 'block'",
    }
    for col, ddl in coldefs.items():
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE endpoints ADD COLUMN {col} {ddl}"))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
