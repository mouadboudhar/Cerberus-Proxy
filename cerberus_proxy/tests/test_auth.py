import httpx
import pytest
import respx

from cerberus_proxy.auth.keys import generate_api_key, hash_key, verify_key
from cerberus_proxy.auth.repository import SQLiteKeyRepository

UPSTREAM_URL = "https://api.openai.com/v1/chat/completions"


# --------------------------- unit tests (no database) ---------------------------


def test_generate_key_format():
    key = generate_api_key()
    assert key.startswith("llmg_")
    assert len(key) >= 40


def test_hash_is_deterministic():
    assert hash_key("test") == hash_key("test")


def test_verify_key_correct():
    plaintext = generate_api_key()
    assert verify_key(plaintext, hash_key(plaintext)) is True


def test_verify_key_wrong():
    assert verify_key("wrong", hash_key("correct")) is False


# ------------------------- integration tests (in-memory) ------------------------


@pytest.mark.asyncio
async def test_middleware_missing_key(session_factory, client):
    resp = await client.post(
        "/v1/chat/completions", json={"model": "gpt-4o-mini", "messages": []}
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Missing X-Cerberus-Key header"}


@pytest.mark.asyncio
async def test_middleware_invalid_key(session_factory, client):
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": []},
        headers={"X-Cerberus-Key": "bad"},
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid or revoked API key"}


@pytest.mark.asyncio
@respx.mock
async def test_middleware_valid_key(session_factory, client, create_key):
    plaintext, _ = await create_key("valid-app")
    fake = {"id": "chatcmpl-x", "object": "chat.completion", "choices": []}
    respx.post(UPSTREAM_URL).mock(return_value=httpx.Response(200, json=fake))
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Cerberus-Key": plaintext},
    )
    assert resp.status_code == 200
    assert resp.json() == fake


@pytest.mark.asyncio
async def test_health_no_auth_required(client):
    resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_revoked_key_rejected(session_factory, client, create_key):
    plaintext, key_id = await create_key("revoked-app")
    async with session_factory() as session:
        repo = SQLiteKeyRepository(session)
        await repo.revoke(key_id)
        await session.commit()
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": []},
        headers={"X-Cerberus-Key": plaintext},
    )
    assert resp.status_code == 401
