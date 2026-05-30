import httpx
import pytest
import respx

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


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_forwards_request(session_factory, client, create_key):
    api_key, _ = await create_key("proxy-test")
    route = respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )
    request_body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hi"}],
    }
    response = await client.post(
        "/v1/chat/completions",
        json=request_body,
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-customer-key"},
    )
    assert response.status_code == 200
    assert response.json() == FAKE_COMPLETION
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-customer-key"


@pytest.mark.asyncio
@respx.mock
async def test_proxy_handles_upstream_error(session_factory, client, create_key):
    api_key, _ = await create_key("proxy-err")
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate limited"}})
    )
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": []},
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-customer-key"},
    )
    assert response.status_code == 429
