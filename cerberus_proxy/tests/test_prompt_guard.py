import asyncio

import httpx
import pytest
import respx

from cerberus_proxy.config.repository import SQLiteEndpointRepository
from cerberus_proxy.guards.prompt_guard import PromptGuard

# The judge and the upstream forward share this URL, so integration tests
# monkeypatch PromptGuard.evaluate (to control the verdict independently) and
# use respx only for the actual upstream completion.
UPSTREAM_URL = "https://api.openai.com/v1/chat/completions"

FAKE_COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
}


def _judge(text: str) -> dict:
    return {
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}}
        ]
    }


async def _make_pg_endpoint(
    session_factory,
    *,
    enabled: bool = True,
    prompt: str | None = "Block anything about salaries",
    model: str | None = None,
    action: str = "block",
) -> int:
    async with session_factory() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.create(
            name="pg-endpoint",
            provider="openai",
            upstream_url="https://api.openai.com",
        )
        await repo.update(
            endpoint.id,
            prompt_guard_enabled=enabled,
            prompt_guard_prompt=prompt,
            prompt_guard_model=model,
            prompt_guard_action=action,
        )
        await session.commit()
        return endpoint.id


# ── Unit tests: PromptGuard.evaluate (mock the LLM call) ─────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_allow_response_passes():
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=_judge("ALLOW - message is appropriate"))
    )
    allowed, text = await PromptGuard().evaluate(
        "hi", "policy", "gpt-4o-mini", "https://api.openai.com", "sk-x"
    )
    assert allowed is True
    assert text.startswith("ALLOW")


@pytest.mark.asyncio
@respx.mock
async def test_block_response_blocks():
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=_judge("BLOCK - discusses competitor pricing"))
    )
    allowed, text = await PromptGuard().evaluate(
        "hi", "policy", "gpt-4o-mini", "https://api.openai.com", "sk-x"
    )
    assert allowed is False
    assert text.startswith("BLOCK")


@pytest.mark.asyncio
@respx.mock
async def test_ambiguous_response_fails_open():
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=_judge("I cannot determine that"))
    )
    allowed, _text = await PromptGuard().evaluate(
        "hi", "policy", "gpt-4o-mini", "https://api.openai.com", "sk-x"
    )
    assert allowed is True


@pytest.mark.asyncio
@respx.mock
async def test_timeout_fails_open():
    respx.post(UPSTREAM_URL).mock(side_effect=asyncio.TimeoutError)
    allowed, text = await PromptGuard().evaluate(
        "hi", "policy", "gpt-4o-mini", "https://api.openai.com", "sk-x"
    )
    assert allowed is True
    assert text == "prompt_guard_error"


@pytest.mark.asyncio
@respx.mock
async def test_http_error_fails_open():
    respx.post(UPSTREAM_URL).mock(side_effect=httpx.HTTPError("boom"))
    allowed, text = await PromptGuard().evaluate(
        "hi", "policy", "gpt-4o-mini", "https://api.openai.com", "sk-x"
    )
    assert allowed is True
    assert text == "prompt_guard_error"


# ── Integration tests: proxy wiring ─────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_proxy_prompt_guard_blocks(session_factory, client, create_key, monkeypatch):
    endpoint_id = await _make_pg_endpoint(session_factory, action="block")

    async def fake_evaluate(self, *args, **kwargs):
        return (False, "BLOCK - discusses salary")

    monkeypatch.setattr(PromptGuard, "evaluate", fake_evaluate)

    api_key, _ = await create_key("pg-block")
    respx.post(UPSTREAM_URL).mock(return_value=httpx.Response(200, json=FAKE_COMPLETION))
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "What is the CEO salary?"}]},
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 403
    assert response.json()["guard"] == "prompt_guard"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_prompt_guard_warn_passes_through(
    session_factory, client, create_key, monkeypatch
):
    endpoint_id = await _make_pg_endpoint(session_factory, action="warn")

    async def fake_evaluate(self, *args, **kwargs):
        return (False, "BLOCK - discusses salary")

    monkeypatch.setattr(PromptGuard, "evaluate", fake_evaluate)

    api_key, _ = await create_key("pg-warn")
    respx.post(UPSTREAM_URL).mock(return_value=httpx.Response(200, json=FAKE_COMPLETION))
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "What is the CEO salary?"}]},
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Cerberus-Policy-Warning") == "true"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_prompt_guard_disabled_skips(
    session_factory, client, create_key, monkeypatch
):
    # Prompt is set but the guard is disabled — it must not run.
    endpoint_id = await _make_pg_endpoint(session_factory, enabled=False)

    async def must_not_run(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("prompt guard should not run when disabled")

    monkeypatch.setattr(PromptGuard, "evaluate", must_not_run)

    api_key, _ = await create_key("pg-disabled")
    respx.post(UPSTREAM_URL).mock(return_value=httpx.Response(200, json=FAKE_COMPLETION))
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
@respx.mock
async def test_proxy_prompt_guard_fail_open(
    session_factory, client, create_key, monkeypatch
):
    endpoint_id = await _make_pg_endpoint(session_factory, action="block")

    async def boom(self, *args, **kwargs):
        raise RuntimeError("evaluator exploded")

    monkeypatch.setattr(PromptGuard, "evaluate", boom)

    api_key, _ = await create_key("pg-fail-open")
    respx.post(UPSTREAM_URL).mock(return_value=httpx.Response(200, json=FAKE_COMPLETION))
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    # Guard error must never block — request continues.
    assert response.status_code == 200


@pytest.mark.asyncio
@respx.mock
async def test_proxy_no_prompt_guard_unaffected(
    session_factory, client, create_key, monkeypatch
):
    # Endpoint created with no prompt guard configured at all.
    async with session_factory() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.create(
            name="plain", provider="openai", upstream_url="https://api.openai.com"
        )
        await session.commit()
        endpoint_id = endpoint.id

    async def must_not_run(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("prompt guard should not run when unconfigured")

    monkeypatch.setattr(PromptGuard, "evaluate", must_not_run)

    api_key, _ = await create_key("pg-none")
    respx.post(UPSTREAM_URL).mock(return_value=httpx.Response(200, json=FAKE_COMPLETION))
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 200
