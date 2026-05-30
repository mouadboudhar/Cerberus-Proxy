import hashlib
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

MAX_HISTORY = 100
SPIKE_THRESHOLD = 10
SPIKE_WINDOW_SECONDS = 5
OVERSIZED_CHAR_LIMIT = 10000
REPEAT_THRESHOLD = 3
REPEAT_WINDOW_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _total_chars(body: dict[str, Any]) -> int:
    total = 0
    for m in body.get("messages") or []:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
    return total


def _user_content(body: dict[str, Any]) -> str:
    parts = [
        m["content"]
        for m in (body.get("messages") or [])
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    ]
    return " ".join(parts)


class AbuseDetector:
    def __init__(self) -> None:
        self._timestamps: dict[int, deque[datetime]] = defaultdict(
            lambda: deque(maxlen=MAX_HISTORY)
        )
        self._query_hashes: dict[int, deque[tuple[datetime, str]]] = defaultdict(
            lambda: deque(maxlen=MAX_HISTORY)
        )

    def record_request(self, key_id: int) -> deque[datetime]:
        self._timestamps[key_id].append(_now())
        return self._timestamps[key_id]

    def history(self, key_id: int) -> deque[datetime]:
        return self._timestamps[key_id]

    def check(
        self,
        key_id: int,
        request_history: list[datetime],
        current_request_body: dict[str, Any],
    ) -> list[str]:
        signals: list[str] = []

        recent = list(request_history)[-SPIKE_THRESHOLD:]
        if (
            len(recent) >= SPIKE_THRESHOLD
            and (recent[-1] - recent[0]).total_seconds() <= SPIKE_WINDOW_SECONDS
        ):
            signals.append("TRAFFIC_SPIKE")

        if _total_chars(current_request_body) > OVERSIZED_CHAR_LIMIT:
            signals.append("OVERSIZED_REQUEST")

        user_text = _user_content(current_request_body)
        if user_text:
            h = hashlib.sha256(user_text.encode("utf-8")).hexdigest()
            now = _now()
            hashes = self._query_hashes[key_id]
            hashes.append((now, h))
            cutoff = now - timedelta(seconds=REPEAT_WINDOW_SECONDS)
            count = sum(1 for ts, qh in hashes if ts >= cutoff and qh == h)
            if count >= REPEAT_THRESHOLD:
                signals.append("REPEATED_QUERY")

        return signals
