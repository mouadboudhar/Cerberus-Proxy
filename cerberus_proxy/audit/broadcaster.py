from typing import Any

from fastapi import WebSocket

from cerberus_proxy.audit.models import AuditEvent


def event_to_dict(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "event_type": event.event_type,
        "severity": event.severity,
        "key_id": event.key_id,
        "endpoint_id": event.endpoint_id,
        "detail": event.detail_dict(),
        "latency_ms": event.latency_ms,
        "request_id": event.request_id,
    }


class Broadcaster:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, event: AuditEvent) -> None:
        if not self._connections:
            return
        payload = event_to_dict(event)
        dead: set[WebSocket] = set()
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)


broadcaster = Broadcaster()
