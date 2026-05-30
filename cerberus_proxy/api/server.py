"""Server information API (Stage 12, Component 4).

GET /api/server/info requires the dashboard token.
GET /api/server/health is public (no auth) and reports DB connectivity.
"""

import os
import time
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import APIRouter, Depends
from sqlalchemy import text

from cerberus_proxy import db
from cerberus_proxy.audit.api import verify_dashboard_token
from cerberus_proxy.audit.repository import SQLiteAuditRepository

router = APIRouter(prefix="/api/server")

_START_TIME = time.monotonic()


def _version() -> str:
    try:
        return _pkg_version("cerberus_proxy")
    except PackageNotFoundError:
        return "0.1.0"


_VERSION = _version()


def _uptime_seconds() -> int:
    return int(time.monotonic() - _START_TIME)


def _database_size_bytes() -> int:
    # Resolve the on-disk SQLite file from the live engine; 0 for in-memory.
    path = db.engine.url.database
    if not path or path == ":memory:":
        return 0
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


async def _database_ok() -> bool:
    try:
        async with db.AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


@router.get("/info", dependencies=[Depends(verify_dashboard_token)])
async def server_info() -> dict:
    audit = SQLiteAuditRepository(db.AsyncSessionLocal)
    stats = await audit.get_summary_stats()
    return {
        "version": _VERSION,
        "uptime_seconds": _uptime_seconds(),
        "database_size_bytes": _database_size_bytes(),
        "active_endpoints": stats["active_endpoints"],
        "active_keys": stats["active_keys"],
        "total_requests": stats["total_requests"],
        "requests_today": stats["requests_today"],
        "blocked_today": stats["blocked_today"],
        "avg_latency_ms": stats["avg_latency_ms"],
    }


@router.get("/health")
async def server_health() -> dict:
    db_ok = await _database_ok()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": _VERSION,
        "database": "ok" if db_ok else "error",
        "uptime_seconds": _uptime_seconds(),
    }
