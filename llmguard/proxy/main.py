import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from llmguard import db
from llmguard.adapters.base import AdapterConfig
from llmguard.adapters.factory import get_adapter
from llmguard.auth.middleware import ApiKeyAuthMiddleware
from llmguard.config.repository import SQLiteEndpointRepository
from llmguard.db import init_db
from llmguard.guards.input_guard import InputGuard
from llmguard.guards.output_guard import OutputGuard

logger = logging.getLogger("llmguard.proxy")

_input_guard = InputGuard()
_output_guard = OutputGuard()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    upstream = os.getenv("LLMGUARD_UPSTREAM_URL", "https://api.openai.com")
    provider = os.getenv("LLMGUARD_PROVIDER", "openai")
    logger.info("LLMGuard proxy listening — provider: %s, upstream: %s", provider, upstream)
    yield


app = FastAPI(title="LLMGuard", version="0.1.0", lifespan=lifespan)
app.add_middleware(ApiKeyAuthMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


async def _forward(provider: str, upstream_url: str, request: Request) -> JSONResponse:
    body = await request.json()

    user_content = " ".join(
        m["content"]
        for m in body.get("messages", [])
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    )
    guard_result = await _input_guard.scan(user_content)
    if not guard_result.passed:
        return JSONResponse(
            status_code=403,
            content={
                "error": "blocked_by_guard",
                "guard": "input_guard",
                "reason_code": guard_result.reason_code.value,
                "severity": guard_result.severity.value,
                "detail": guard_result.detail,
            },
        )

    headers = dict(request.headers)
    adapter = get_adapter(provider, AdapterConfig(upstream_url=upstream_url))
    try:
        result = await adapter.forward(body, headers)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await _apply_output_guard(result)


def _extract_assistant_content(result: dict) -> str | None:
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) else None


async def _apply_output_guard(result: dict) -> JSONResponse:
    action = os.getenv("LLMGUARD_OUTPUT_GUARD_ACTION", "redact").lower()
    content = _extract_assistant_content(result)
    if not content:
        return JSONResponse(content=result)

    if action == "block":
        scan = await _output_guard.scan(content)
        if not scan.passed:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "blocked_by_guard",
                    "guard": "output_guard",
                    "reason_code": scan.reason_code.value,
                    "severity": scan.severity.value,
                    "detail": scan.detail,
                },
            )
        return JSONResponse(content=result)

    if action == "log_only":
        scan = await _output_guard.scan(content)
        if not scan.passed:
            logger.warning(
                "output_guard log_only — would block: %s/%s — %s",
                scan.reason_code.value,
                scan.severity.value,
                scan.detail,
            )
        return JSONResponse(content=result)

    # default action: redact
    redacted, names = _output_guard.redact(content)
    if names:
        result["choices"][0]["message"]["content"] = redacted
        return JSONResponse(
            content=result,
            headers={"X-LLMGuard-Redacted": ",".join(names)},
        )
    return JSONResponse(content=result)


@app.post("/v1/chat/completions")
async def chat_completions_default(request: Request):
    provider = os.getenv("LLMGUARD_PROVIDER", "openai")
    upstream = os.getenv("LLMGUARD_UPSTREAM_URL", "https://api.openai.com")
    return await _forward(provider, upstream, request)


@app.post("/v1/chat/completions/{endpoint_id}")
async def chat_completions_endpoint(endpoint_id: int, request: Request):
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.get_by_id(endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return await _forward(endpoint.provider, endpoint.upstream_url, request)


def start():
    uvicorn.run("llmguard.proxy.main:app", host="0.0.0.0", port=8000, reload=False)  # nosec B104
