import httpx
import pytest
import respx

from cerberus_proxy.adapters.anthropic_adapter import AnthropicAdapter
from cerberus_proxy.adapters.base import AdapterConfig
from cerberus_proxy.adapters.factory import get_adapter
from cerberus_proxy.adapters.mistral_adapter import MistralAdapter
from cerberus_proxy.adapters.ollama_adapter import OllamaAdapter
from cerberus_proxy.adapters.openai_adapter import OpenAIAdapter
from cerberus_proxy.config.repository import SQLiteEndpointRepository

OPENAI_BASE = "https://api.openai.com"
OPENAI_URL = f"{OPENAI_BASE}/v1/chat/completions"

ANTHROPIC_BASE = "https://api.anthropic.com"
ANTHROPIC_URL = f"{ANTHROPIC_BASE}/messages"

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_URL = f"{OLLAMA_BASE}/v1/chat/completions"

MISTRAL_BASE = "https://api.mistral.ai"
MISTRAL_URL = f"{MISTRAL_BASE}/v1/chat/completions"

OPENAI_COMPLETION = {
    "id": "chatcmpl-x",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hi"},
            "finish_reason": "stop",
        }
    ],
}

ANTHROPIC_RESPONSE = {
    "id": "msg_01abc",
    "type": "message",
    "role": "assistant",
    "model": "claude-3-5-sonnet-20241022",
    "content": [{"type": "text", "text": "hello there"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 12, "output_tokens": 7},
}


@pytest.mark.asyncio
@respx.mock
async def test_openai_adapter_forwards_correctly():
    route = respx.post(OPENAI_URL).mock(
        return_value=httpx.Response(200, json=OPENAI_COMPLETION)
    )
    adapter = OpenAIAdapter(AdapterConfig(upstream_url=OPENAI_BASE))
    result = await adapter.forward(
        {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        {"Authorization": "Bearer sk-test", "Content-Type": "application/json"},
    )
    assert result == OPENAI_COMPLETION
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-test"
    assert sent.headers["content-type"] == "application/json"


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_adapter_translates_request():
    route = respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    adapter = AnthropicAdapter(AdapterConfig(upstream_url=ANTHROPIC_BASE))
    await adapter.forward(
        {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "hi"}],
        },
        {"Authorization": "Bearer sk-ant-test", "Content-Type": "application/json"},
    )
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "sk-ant-test"
    assert sent.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in sent.headers
    import json

    body = json.loads(sent.content)
    assert body["model"] == "claude-3-5-sonnet-20241022"
    assert body["max_tokens"] == 256
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "system" not in body


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_adapter_translates_response():
    respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    adapter = AnthropicAdapter(AdapterConfig(upstream_url=ANTHROPIC_BASE))
    result = await adapter.forward(
        {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "hi"}],
        },
        {"Authorization": "Bearer sk-ant-test"},
    )
    assert result["id"] == "msg_01abc"
    assert result["object"] == "chat.completion"
    assert result["model"] == "claude-3-5-sonnet-20241022"
    assert result["choices"][0]["message"] == {
        "role": "assistant",
        "content": "hello there",
    }
    assert result["choices"][0]["finish_reason"] == "end_turn"
    assert result["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_strips_system_message():
    route = respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    adapter = AnthropicAdapter(AdapterConfig(upstream_url=ANTHROPIC_BASE))
    await adapter.forward(
        {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 256,
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "hi"},
            ],
        },
        {"Authorization": "Bearer sk-ant-test"},
    )
    import json

    body = json.loads(route.calls.last.request.content)
    assert body["system"] == "Be concise."
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert all(m.get("role") != "system" for m in body["messages"])


@pytest.mark.asyncio
@respx.mock
async def test_ollama_strips_auth_header():
    route = respx.post(OLLAMA_URL).mock(
        return_value=httpx.Response(200, json=OPENAI_COMPLETION)
    )
    adapter = OllamaAdapter(AdapterConfig(upstream_url=OLLAMA_BASE))
    result = await adapter.forward(
        {"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
        {"Authorization": "Bearer sk-should-be-stripped", "Content-Type": "application/json"},
    )
    assert result == OPENAI_COMPLETION
    sent = route.calls.last.request
    assert "authorization" not in sent.headers
    assert sent.headers["content-type"] == "application/json"


@pytest.mark.asyncio
@respx.mock
async def test_mistral_forwards_correctly():
    route = respx.post(MISTRAL_URL).mock(
        return_value=httpx.Response(200, json=OPENAI_COMPLETION)
    )
    adapter = MistralAdapter(AdapterConfig(upstream_url=MISTRAL_BASE))
    result = await adapter.forward(
        {
            "model": "mistral-small",
            "messages": [{"role": "user", "content": "hi"}],
            "safe_mode": True,
        },
        {"Authorization": "Bearer sk-mistral", "Content-Type": "application/json"},
    )
    assert result == OPENAI_COMPLETION
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-mistral"
    import json

    body = json.loads(sent.content)
    assert "safe_mode" not in body
    assert body["model"] == "mistral-small"


def test_factory_returns_correct_adapter():
    cfg = AdapterConfig(upstream_url="https://example.com")
    assert isinstance(get_adapter("openai", cfg), OpenAIAdapter)
    assert isinstance(get_adapter("anthropic", cfg), AnthropicAdapter)
    assert isinstance(get_adapter("ollama", cfg), OllamaAdapter)
    assert isinstance(get_adapter("mistral", cfg), MistralAdapter)
    assert isinstance(get_adapter("OpenAI", cfg), OpenAIAdapter)


def test_factory_raises_on_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_adapter("cohere", AdapterConfig(upstream_url="https://example.com"))


@pytest.mark.asyncio
@respx.mock
async def test_endpoint_routing(session_factory, client, create_key):
    api_key, _ = await create_key("endpoint-test")
    async with session_factory() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.create(
            name="anthropic-prod",
            provider="anthropic",
            upstream_url=ANTHROPIC_BASE,
            default_model="claude-3-5-sonnet-20241022",
        )
        await session.commit()
        endpoint_id = endpoint.id

    route = respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-ant-test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello there"
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "sk-ant-test"
    assert sent.headers["anthropic-version"] == "2023-06-01"


@pytest.mark.asyncio
async def test_endpoint_routing_404(session_factory, client, create_key):
    api_key, _ = await create_key("endpoint-404")
    response = await client.post(
        "/v1/chat/completions/9999",
        json={"model": "x", "messages": []},
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Endpoint not found"}
