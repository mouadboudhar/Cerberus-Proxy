"""Admin REST API for managing API keys (Stage 12, Component 2).

All routes require the dashboard token via the X-Dashboard-Token header.
The plaintext key is returned exactly once, on creation; only the hash is
ever stored, and the hash is never returned.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cerberus_proxy import db
from cerberus_proxy.audit.api import verify_dashboard_token
from cerberus_proxy.auth.keys import generate_api_key, hash_key
from cerberus_proxy.auth.models import ApiKey
from cerberus_proxy.auth.repository import SQLiteKeyRepository
from cerberus_proxy.config.models import Endpoint
from cerberus_proxy.ratelimit.bucket import TokenBucket

router = APIRouter(
    prefix="/api/keys",
    dependencies=[Depends(verify_dashboard_token)],
)

_bucket = TokenBucket()


class KeyCreate(BaseModel):
    name: str
    endpoint_id: int | None = None


class LimitsUpdate(BaseModel):
    rpm: int | None = None
    rph: int | None = None
    rpd: int | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _serialize(session: AsyncSession, key: ApiKey) -> dict:
    endpoint_name = None
    if key.endpoint_id is not None:
        endpoint = await session.get(Endpoint, key.endpoint_id)
        endpoint_name = endpoint.name if endpoint is not None else None
    usage = await _bucket.get_usage(session, key.id)
    return {
        "id": key.id,
        "name": key.name,
        "endpoint_id": key.endpoint_id,
        "endpoint_name": endpoint_name,
        "created_at": _iso(key.created_at),
        "last_used_at": _iso(key.last_used_at),
        "revoked_at": _iso(key.revoked_at),
        "is_active": key.is_active,
        "rate_limit_rpm": key.rate_limit_rpm,
        "rate_limit_rph": key.rate_limit_rph,
        "rate_limit_rpd": key.rate_limit_rpd,
        "usage": usage,
    }


@router.get(
    "",
    summary="List API keys",
    description=(
        "Return all API keys with their metadata, rate limits, and current "
        "usage. The plaintext key value is never included — only the stored "
        "hash exists after creation. Requires the dashboard token."
    ),
)
async def list_keys() -> list[dict]:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        keys = await repo.list_all()
        return [await _serialize(session, key) for key in keys]


@router.post(
    "",
    summary="Create an API key",
    description=(
        "Create a new API key, optionally bound to an endpoint. The plaintext "
        "key (prefix `cbrs_`) is returned exactly once in this response and is "
        "never recoverable afterwards — only its hash is stored. Requires the "
        "dashboard token."
    ),
)
async def create_key(body: KeyCreate) -> dict:
    plaintext = generate_api_key()
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        key = await repo.create(
            name=body.name,
            key_hash=hash_key(plaintext),
            endpoint_id=body.endpoint_id,
        )
        await session.commit()
        data = await _serialize(session, key)
    # Plaintext key — returned ONCE here and never again. Only the hash is stored.
    data["key"] = plaintext
    return data


@router.get(
    "/{key_id}",
    summary="Get an API key",
    description=(
        "Return a single API key's metadata, rate limits, and usage by id. "
        "The plaintext key is never returned. 404 if the key does not exist. "
        "Requires the dashboard token."
    ),
)
async def get_key(key_id: int) -> dict:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        key = await repo.get_by_id(key_id)
        if key is None:
            raise HTTPException(status_code=404, detail="key_not_found")
        return await _serialize(session, key)


@router.delete(
    "/{key_id}",
    summary="Revoke an API key",
    description=(
        "Revoke an API key by id, marking it inactive so it can no longer "
        "authenticate. The row is retained for audit history. 404 if the key "
        "does not exist. Requires the dashboard token."
    ),
)
async def revoke_key(key_id: int) -> dict:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        key = await repo.get_by_id(key_id)
        if key is None:
            raise HTTPException(status_code=404, detail="key_not_found")
        await repo.revoke(key_id)
        await session.commit()
    return {"revoked": True}


@router.patch(
    "/{key_id}/limits",
    summary="Update API key rate limits",
    description=(
        "Override the per-key rate limits (requests per minute / hour / day). "
        "Only the provided fields are changed; omit a field to leave it on the "
        "deployment default. 404 if the key does not exist. Requires the "
        "dashboard token."
    ),
)
async def update_key_limits(key_id: int, body: LimitsUpdate) -> dict:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        key = await repo.update_limits(
            key_id, rpm=body.rpm, rph=body.rph, rpd=body.rpd
        )
        if key is None:
            raise HTTPException(status_code=404, detail="key_not_found")
        await session.commit()
        return await _serialize(session, key)


@router.get(
    "/{key_id}/usage",
    summary="Get API key usage",
    description=(
        "Return the current rate-limit usage counters for a key across the "
        "minute / hour / day windows. 404 if the key does not exist. Requires "
        "the dashboard token."
    ),
)
async def key_usage(key_id: int) -> dict:
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteKeyRepository(session)
        key = await repo.get_by_id(key_id)
        if key is None:
            raise HTTPException(status_code=404, detail="key_not_found")
        return await _bucket.get_usage(session, key_id)
