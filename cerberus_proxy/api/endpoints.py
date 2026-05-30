"""Admin REST API for managing proxy endpoints (Stage 12, Component 1).

All routes require the dashboard token via the X-Dashboard-Token header,
enforced by the shared verify_dashboard_token dependency.
"""

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cerberus_proxy import db
from cerberus_proxy.audit.api import verify_dashboard_token
from cerberus_proxy.audit.repository import SQLiteAuditRepository
from cerberus_proxy.auth.repository import SQLiteKeyRepository
from cerberus_proxy.config.models import Endpoint
from cerberus_proxy.config.repository import SQLiteEndpointRepository

router = APIRouter(
    prefix="/api/endpoints",
    dependencies=[Depends(verify_dashboard_token)],
)


class Provider(str, Enum):
    openai = "openai"
    anthropic = "anthropic"
    ollama = "ollama"
    mistral = "mistral"
    grok = "grok"
    nvidia = "nvidia"


class EndpointCreate(BaseModel):
    name: str
    provider: Provider
    upstream_url: str
    default_model: str | None = None
    kb_type: str | None = None
    kb_url: str | None = None
    kb_collection: str | None = None
    kb_top_k: int = 4


class EndpointUpdate(BaseModel):
    name: str | None = None
    provider: Provider | None = None
    upstream_url: str | None = None
    default_model: str | None = None
    kb_type: str | None = None
    kb_url: str | None = None
    kb_collection: str | None = None
    kb_top_k: int | None = None
    is_active: bool | None = None


_EMPTY_STATS = {
    "requests_today": 0,
    "requests_total": 0,
    "blocked_today": 0,
    "avg_latency_ms": 0,
}


def _audit_repo() -> SQLiteAuditRepository:
    # Bind to the live session factory so the dashboard reads the same DB the
    # proxy writes to (and so tests that monkeypatch db.AsyncSessionLocal work).
    return SQLiteAuditRepository(db.AsyncSessionLocal)


def _serialize(endpoint: Endpoint, stats: dict) -> dict:
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "provider": endpoint.provider,
        "upstream_url": endpoint.upstream_url,
        "default_model": endpoint.default_model,
        "is_active": endpoint.is_active,
        "kb_type": endpoint.kb_type,
        "kb_url": endpoint.kb_url,
        "kb_collection": endpoint.kb_collection,
        "kb_top_k": endpoint.kb_top_k,
        "created_at": endpoint.created_at.isoformat() if endpoint.created_at else None,
        "stats": stats,
    }


@router.get("")
async def list_endpoints() -> list[dict]:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        # Soft-deleted (inactive) endpoints are hidden from the admin API.
        endpoints = [ep for ep in await repo.list_all() if ep.is_active]
    audit = _audit_repo()
    return [
        _serialize(ep, await audit.get_stats_by_endpoint(ep.id)) for ep in endpoints
    ]


@router.post("")
async def create_endpoint(body: EndpointCreate) -> dict:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.create(
            name=body.name,
            provider=body.provider.value,
            upstream_url=body.upstream_url,
            default_model=body.default_model,
            kb_type=body.kb_type,
            kb_url=body.kb_url,
            kb_collection=body.kb_collection,
            kb_top_k=body.kb_top_k,
        )
        await session.commit()
        return _serialize(endpoint, dict(_EMPTY_STATS))


@router.get("/{endpoint_id}")
async def get_endpoint(endpoint_id: int) -> dict:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.get_by_id(endpoint_id)
    if endpoint is None or not endpoint.is_active:
        raise HTTPException(status_code=404, detail="endpoint_not_found")
    stats = await _audit_repo().get_stats_by_endpoint(endpoint_id)
    return _serialize(endpoint, stats)


@router.patch("/{endpoint_id}")
async def update_endpoint(endpoint_id: int, body: EndpointUpdate) -> dict:
    # mode="json" coerces the Provider enum to its string value.
    fields = body.model_dump(exclude_unset=True, mode="json")
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.update(endpoint_id, **fields)
        if endpoint is None:
            raise HTTPException(status_code=404, detail="endpoint_not_found")
        await session.commit()
        endpoint_id = endpoint.id
        serialized_base = _serialize(endpoint, dict(_EMPTY_STATS))
    serialized_base["stats"] = await _audit_repo().get_stats_by_endpoint(endpoint_id)
    return serialized_base


@router.delete("/{endpoint_id}")
async def delete_endpoint(endpoint_id: int) -> dict:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        # Soft delete: flip is_active rather than dropping the row.
        endpoint = await repo.update(endpoint_id, is_active=False)
        if endpoint is None:
            raise HTTPException(status_code=404, detail="endpoint_not_found")
        # Revoke every API key bound to this endpoint.
        key_repo = SQLiteKeyRepository(session)
        await key_repo.revoke_by_endpoint(endpoint_id)
        await session.commit()
    return {"deleted": True}
