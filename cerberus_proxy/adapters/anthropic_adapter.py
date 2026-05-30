from typing import Any

import httpx
from fastapi import HTTPException

from cerberus_proxy.adapters.base import AdapterConfig, LLMAdapter

_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdapter(LLMAdapter):
    def __init__(self, config: AdapterConfig) -> None:
        self.config = config

    async def forward(
        self,
        request_body: dict[str, Any],
        headers: dict[str, Any],
    ) -> dict[str, Any]:
        anthropic_body = _translate_request(request_body)
        anthropic_headers = _translate_headers(headers)
        url = f"{self.config.upstream_url.rstrip('/')}/messages"

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(url, json=anthropic_body, headers=anthropic_headers)
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise HTTPException(status_code=response.status_code, detail=detail)
        return _translate_response(response.json())


def _translate_request(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages", []) or []
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                system_parts.append(content)
            continue
        converted.append({"role": msg.get("role"), "content": msg.get("content")})

    out: dict[str, Any] = {
        "model": body.get("model"),
        "messages": converted,
    }
    if "max_tokens" in body:
        out["max_tokens"] = body["max_tokens"]
    if system_parts:
        out["system"] = "\n".join(system_parts)
    return out


def _translate_headers(headers: dict[str, Any]) -> dict[str, str]:
    lowered = {k.lower(): v for k, v in headers.items()}
    out: dict[str, str] = {
        "content-type": lowered.get("content-type", "application/json"),
        "anthropic-version": _ANTHROPIC_VERSION,
    }
    auth = lowered.get("authorization", "")
    if auth.lower().startswith("bearer "):
        out["x-api-key"] = auth[7:].strip()
    elif auth:
        out["x-api-key"] = auth.strip()
    return out


def _translate_response(resp: dict[str, Any]) -> dict[str, Any]:
    content_blocks = resp.get("content") or []
    text = ""
    if content_blocks and isinstance(content_blocks, list):
        first = content_blocks[0]
        if isinstance(first, dict):
            text = first.get("text", "") or ""

    usage = resp.get("usage") or {}
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0

    return {
        "id": resp.get("id"),
        "object": "chat.completion",
        "model": resp.get("model"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": resp.get("stop_reason"),
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }
