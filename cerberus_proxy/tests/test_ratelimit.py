from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
import respx

from cerberus_proxy.auth.models import ApiKey
from cerberus_proxy.ratelimit.abuse import AbuseDetector
from cerberus_proxy.ratelimit.bucket import RateLimitBucket, TokenBucket

UPSTREAM_URL = "https://api.openai.com/v1/chat/completions"

FAKE_COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
}


@pytest_asyncio.fixture
async def session_with_key(session_factory):
    async with session_factory() as s:
        key = ApiKey(name="rl-test", key_hash="rl-hash")
        s.add(key)
        await s.commit()
        key_id = key.id
    async with session_factory() as s:
        yield s, key_id


# ---------- TokenBucket unit tests ----------


@pytest.mark.asyncio
async def test_token_bucket_allows_within_limit(session_with_key):
    session, key_id = session_with_key
    bucket = TokenBucket()
    last_remaining = None
    for _ in range(5):
        ok, last_remaining = await bucket.check_and_increment(
            session, key_id, "minute", 10
        )
        assert ok
    assert last_remaining == 5


@pytest.mark.asyncio
async def test_token_bucket_blocks_at_limit(session_with_key):
    session, key_id = session_with_key
    bucket = TokenBucket()
    for _ in range(10):
        ok, _ = await bucket.check_and_increment(session, key_id, "minute", 10)
        assert ok
    ok, remaining = await bucket.check_and_increment(session, key_id, "minute", 10)
    assert ok is False
    assert remaining == 0


@pytest.mark.asyncio
async def test_token_bucket_resets_after_window(session_with_key):
    session, key_id = session_with_key
    bucket = TokenBucket()
    for _ in range(10):
        await bucket.check_and_increment(session, key_id, "minute", 10)
    ok, _ = await bucket.check_and_increment(session, key_id, "minute", 10)
    assert ok is False

    # Backdate the bucket past the window boundary to simulate time passing.
    row = await session.get(RateLimitBucket, (key_id, "minute"))
    row.window_start = row.window_start - timedelta(minutes=2)
    await session.flush()

    ok, remaining = await bucket.check_and_increment(session, key_id, "minute", 10)
    assert ok is True
    assert remaining == 9


@pytest.mark.asyncio
async def test_token_bucket_tracks_three_windows(session_with_key):
    session, key_id = session_with_key
    bucket = TokenBucket()
    for _ in range(2):
        ok, _ = await bucket.check_and_increment(session, key_id, "minute", 2)
        assert ok
    ok, _ = await bucket.check_and_increment(session, key_id, "minute", 2)
    assert ok is False

    ok, remaining = await bucket.check_and_increment(session, key_id, "hour", 100)
    assert ok is True
    assert remaining == 99


# ---------- AbuseDetector unit tests ----------


def test_abuse_detector_spike_detected():
    detector = AbuseDetector()
    base = datetime(2026, 1, 1, 12, 0, 0)
    history = [base + timedelta(milliseconds=200 * i) for i in range(10)]
    signals = detector.check(1, history, {"messages": []})
    assert "TRAFFIC_SPIKE" in signals


def test_abuse_detector_oversized_request():
    detector = AbuseDetector()
    body = {"messages": [{"role": "user", "content": "x" * 15000}]}
    signals = detector.check(1, [], body)
    assert "OVERSIZED_REQUEST" in signals


def test_abuse_detector_repeated_query():
    detector = AbuseDetector()
    body = {"messages": [{"role": "user", "content": "same question"}]}
    first = detector.check(1, [], body)
    second = detector.check(1, [], body)
    third = detector.check(1, [], body)
    assert "REPEATED_QUERY" not in first
    assert "REPEATED_QUERY" not in second
    assert "REPEATED_QUERY" in third


def test_abuse_detector_clean_traffic():
    detector = AbuseDetector()
    base = datetime(2026, 1, 1, 12, 0, 0)
    history = [base + timedelta(seconds=6 * i) for i in range(5)]
    body = {"messages": [{"role": "user", "content": "hello world"}]}
    signals = detector.check(1, history, body)
    assert signals == []


# ---------- Proxy integration tests ----------


async def _set_rpm(session_factory, key_id: int, rpm: int) -> None:
    async with session_factory() as s:
        k = await s.get(ApiKey, key_id)
        k.rate_limit_rpm = rpm
        await s.commit()


def _request_body(content: str = "Hi") -> dict:
    return {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": content}],
    }


@pytest.mark.asyncio
@respx.mock
async def test_proxy_returns_429_on_rpm_exceeded(session_factory, client, create_key):
    api_key, key_id = await create_key("limit-rpm")
    await _set_rpm(session_factory, key_id, 2)
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )
    headers = {"X-Cerberus-Key": api_key}

    r1 = await client.post("/v1/chat/completions", json=_request_body("one"), headers=headers)
    r2 = await client.post("/v1/chat/completions", json=_request_body("two"), headers=headers)
    r3 = await client.post("/v1/chat/completions", json=_request_body("three"), headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert r3.headers.get("Retry-After")
    assert int(r3.headers["Retry-After"]) >= 0
    assert r3.json()["error"] == "rate_limit_exceeded"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_returns_429_with_correct_window(
    session_factory, client, create_key
):
    api_key, key_id = await create_key("limit-window")
    await _set_rpm(session_factory, key_id, 1)
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )
    headers = {"X-Cerberus-Key": api_key}

    await client.post("/v1/chat/completions", json=_request_body("a"), headers=headers)
    r = await client.post("/v1/chat/completions", json=_request_body("b"), headers=headers)

    assert r.status_code == 429
    assert r.json()["window"] == "minute"
    assert r.json()["limit"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_proxy_allows_request_within_limits(
    session_factory, client, create_key
):
    api_key, key_id = await create_key("limit-ok")
    await _set_rpm(session_factory, key_id, 100)
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )

    r = await client.post(
        "/v1/chat/completions",
        json=_request_body("hello"),
        headers={"X-Cerberus-Key": api_key},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
@respx.mock
async def test_proxy_uses_default_limits_when_key_has_none(
    session_factory, client, create_key, monkeypatch
):
    monkeypatch.setenv("CERBERUS_DEFAULT_RPM", "1")
    api_key, _ = await create_key("limit-default")
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )
    headers = {"X-Cerberus-Key": api_key}

    r1 = await client.post("/v1/chat/completions", json=_request_body("a"), headers=headers)
    r2 = await client.post("/v1/chat/completions", json=_request_body("b"), headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 429
