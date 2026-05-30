import os
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from cerberus_proxy.audit.broadcaster import event_to_dict
from cerberus_proxy.audit.emitter import get_repository

router = APIRouter(prefix="/api/audit")


def verify_dashboard_token(
    x_dashboard_token: str | None = Header(default=None),
) -> None:
    expected = os.getenv("CERBERUS_DASHBOARD_TOKEN")
    if not expected or not x_dashboard_token or x_dashboard_token != expected:
        raise HTTPException(status_code=401, detail="invalid_dashboard_token")


def _require_repo():
    repo = get_repository()
    if repo is None:
        raise HTTPException(status_code=503, detail="audit_not_initialized")
    return repo


@router.get("/events", dependencies=[Depends(verify_dashboard_token)])
async def list_events(
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    key_id: int | None = Query(default=None),
    endpoint_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    repo = _require_repo()
    events = await repo.query(
        from_ts=from_ts,
        to_ts=to_ts,
        event_type=event_type,
        severity=severity,
        key_id=key_id,
        endpoint_id=endpoint_id,
        limit=limit,
        offset=offset,
    )
    total = await repo.count(
        from_ts=from_ts,
        to_ts=to_ts,
        event_type=event_type,
        severity=severity,
        key_id=key_id,
        endpoint_id=endpoint_id,
    )
    return {
        "events": [event_to_dict(e) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats", dependencies=[Depends(verify_dashboard_token)])
async def get_stats(
    hours: int = Query(default=24, ge=1, le=168),
) -> dict:
    repo = _require_repo()
    return await repo.get_stats(hours=hours)


@router.get("/events/{event_id}", dependencies=[Depends(verify_dashboard_token)])
async def get_event(event_id: int) -> dict:
    repo = _require_repo()
    event = await repo.get_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event_not_found")
    return event_to_dict(event)
