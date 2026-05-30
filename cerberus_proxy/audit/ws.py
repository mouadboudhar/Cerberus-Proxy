import asyncio
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from cerberus_proxy.audit.broadcaster import event_to_dict
from cerberus_proxy.audit.emitter import get_broadcaster, get_repository

logger = logging.getLogger("cerberus_proxy.audit.ws")

router = APIRouter()


def _expected_token() -> str | None:
    return os.getenv("CERBERUS_DASHBOARD_TOKEN")


def _extract_token(websocket: WebSocket) -> str | None:
    header_token = websocket.headers.get("x-dashboard-token")
    if header_token:
        return header_token
    return websocket.query_params.get("token")


@router.websocket("/ws/events")
async def events_ws(websocket: WebSocket) -> None:
    expected = _expected_token()
    presented = _extract_token(websocket)

    if not expected or not presented or presented != expected:
        await websocket.close(code=4001)
        return

    broadcaster = get_broadcaster()
    repository = get_repository()
    if broadcaster is None or repository is None:
        await websocket.close(code=1011)
        return

    await broadcaster.connect(websocket)
    try:
        recent = await repository.query(limit=20)
        for event in reversed(recent):
            await websocket.send_json(event_to_dict(event))

        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("websocket events handler error")
    finally:
        broadcaster.disconnect(websocket)
