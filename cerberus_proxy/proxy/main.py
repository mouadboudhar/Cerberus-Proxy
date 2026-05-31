import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cerberus_proxy import db
from cerberus_proxy.adapters.base import AdapterConfig
from cerberus_proxy.adapters.factory import get_adapter
from cerberus_proxy.api.auth import router as auth_router
from cerberus_proxy.api.endpoints import router as endpoints_router
from cerberus_proxy.api.guards import router as guards_router
from cerberus_proxy.api.keys import router as keys_router
from cerberus_proxy.api.server import router as server_router
from cerberus_proxy.audit.api import router as audit_api_router
from cerberus_proxy.audit.broadcaster import broadcaster
from cerberus_proxy.audit.emitter import emit, init_emitter
from cerberus_proxy.audit.models import EventType
from cerberus_proxy.audit.repository import SQLiteAuditRepository
from cerberus_proxy.audit.request_context import RequestContextMiddleware
from cerberus_proxy.audit.ws import router as ws_router
from cerberus_proxy.auth.middleware import ApiKeyAuthMiddleware
from cerberus_proxy.config.models import Endpoint
from cerberus_proxy.config.repository import SQLiteEndpointRepository
from cerberus_proxy.guards.base import DEFAULT_GUARD_CONFIG, GuardConfig
from cerberus_proxy.db import init_db
from cerberus_proxy.guards.input_guard import InputGuard
from cerberus_proxy.guards.output_guard import OutputGuard
from cerberus_proxy.guards.prompt_guard import PromptGuard
from cerberus_proxy.guards.translator import warm_up
from cerberus_proxy.ratelimit.abuse import AbuseDetector
from cerberus_proxy.ratelimit.middleware import check_rate_limits
from cerberus_proxy.retrieval.factory import get_retriever
from cerberus_proxy.retrieval.injector import inject_context

logger = logging.getLogger("cerberus_proxy.proxy")

_input_guard = InputGuard()
_output_guard = OutputGuard()
_prompt_guard = PromptGuard()
_abuse_detector = AbuseDetector()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    upstream = os.getenv("CERBERUS_UPSTREAM_URL", "https://api.openai.com")
    provider = os.getenv("CERBERUS_PROVIDER", "openai")
    audit_repo = SQLiteAuditRepository(db.AsyncSessionLocal)
    init_emitter(audit_repo, broadcaster)
    if not os.getenv("CERBERUS_DASHBOARD_TOKEN"):
        logger.warning(
            "CERBERUS_DASHBOARD_TOKEN not set — dashboard WS and audit API will reject all clients"
        )
    # Load translation models before serving traffic. A cold model load takes
    # ~1.5s — long enough to lose the input guard's per-request translation
    # timeout and fail open, letting a non-English injection through unscanned.
    logger.info("Warming up translation models...")
    await asyncio.to_thread(warm_up)
    logger.info("Cerberus Proxy proxy listening — provider: %s, upstream: %s", provider, upstream)
    yield


app = FastAPI(title="Cerberus Proxy", version="0.1.0", lifespan=lifespan)
app.add_middleware(ApiKeyAuthMiddleware)
app.add_middleware(RequestContextMiddleware)
# Added last => outermost layer, so CORS preflight (OPTIONS) is answered before
# the auth middleware runs. Origins are overridable via CERBERUS_CORS_ORIGINS.
_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CERBERUS_CORS_ORIGINS", "http://localhost:5173,http://localhost:4173"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Dashboard-Token",
        "X-Cerberus-Key",
        "X-User-Clearance",
    ],
    expose_headers=["X-Cerberus-Redacted"],
)
app.include_router(ws_router)
app.include_router(audit_api_router)
app.include_router(endpoints_router, prefix="", tags=["Endpoints"])
app.include_router(keys_router, prefix="", tags=["Keys"])
app.include_router(auth_router, prefix="", tags=["Auth"])
app.include_router(server_router, prefix="", tags=["Server"])
app.include_router(guards_router, prefix="", tags=["Guards"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


async def _forward(
    provider: str,
    upstream_url: str,
    request: Request,
    endpoint_id: int | None = None,
    endpoint: Endpoint | None = None,
) -> JSONResponse:
    body = await request.json()
    request_id = getattr(request.state, "request_id", None)
    key_id = getattr(request.state, "key_id", None)

    key_record = getattr(request.state, "key_record", None)
    if key_record is not None:
        async with db.AsyncSessionLocal() as session:
            rate_response = await check_rate_limits(request, key_record, session)
            await session.commit()
        if rate_response is not None:
            return rate_response

        _abuse_detector.record_request(key_record.id)
        signals = _abuse_detector.check(
            key_record.id,
            list(_abuse_detector.history(key_record.id)),
            body,
        )
        for signal in signals:
            logger.warning("abuse signal %s for key %s", signal, key_record.id)
        if signals:
            await emit(
                EventType.ABUSE_SIGNAL,
                severity="MEDIUM",
                key_id=key_record.id,
                endpoint_id=endpoint_id,
                detail={"signals": signals},
                request_id=request_id,
            )

    # Per-endpoint guard config (Stage 14b). The default route (no endpoint)
    # uses the all-rules-on default, preserving prior behaviour.
    if endpoint is not None:
        guard_config = GuardConfig(
            disabled_rules=endpoint.get_disabled_input_rules,
            custom_blocked_phrases=endpoint.get_custom_blocked_phrases,
            active_languages=endpoint.get_active_languages,
        )
    else:
        guard_config = DEFAULT_GUARD_CONFIG

    user_content = " ".join(
        m["content"]
        for m in body.get("messages", [])
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    )
    guard_result = await _input_guard.scan(user_content, guard_config)
    if not guard_result.passed:
        await emit(
            EventType.INPUT_GUARD_BLOCKED,
            severity="HIGH",
            key_id=key_id,
            endpoint_id=endpoint_id,
            detail={
                "reason_code": guard_result.reason_code.value,
                "severity": guard_result.severity.value,
                "detail": guard_result.detail,
            },
            request_id=request_id,
        )
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
    await emit(
        EventType.INPUT_GUARD_PASSED,
        key_id=key_id,
        endpoint_id=endpoint_id,
        request_id=request_id,
    )

    # Custom Prompt Guard (Stage 14c) — OPTIONAL, NON-DETERMINISTIC policy
    # layer. Runs only when the endpoint enables it; adds one LLM round-trip
    # (latency + cost). Always fails open: PromptGuard.evaluate never raises,
    # so a guard failure can never block a legitimate request.
    policy_warning = False
    if endpoint is not None and endpoint.has_prompt_guard:
        provider_key = request.headers.get("authorization", "")
        if provider_key.lower().startswith("bearer "):
            provider_key = provider_key[7:]
        try:
            allowed, reason = await _prompt_guard.evaluate(
                user_content,
                endpoint.prompt_guard_prompt,
                endpoint.prompt_guard_model or "gpt-4o-mini",
                endpoint.upstream_url,
                provider_key,
            )
        except Exception as e:  # noqa: BLE001 — defence in depth, always fail open
            logger.warning("Prompt guard evaluation error: %s", e)
            allowed, reason = True, "prompt_guard_error"
        action = endpoint.prompt_guard_action or "block"
        if allowed:
            await emit(
                EventType.PROMPT_GUARD_PASSED,
                key_id=key_id,
                endpoint_id=endpoint_id,
                request_id=request_id,
            )
        else:
            # Policy violation detected — always audit it; whether the request
            # is actually blocked depends on the endpoint's configured action.
            await emit(
                EventType.PROMPT_GUARD_BLOCKED,
                severity="MEDIUM",
                key_id=key_id,
                endpoint_id=endpoint_id,
                detail={
                    "reason_code": "POLICY_VIOLATION",
                    "action": action,
                    "detail": reason,
                },
                request_id=request_id,
            )
            if action == "block":
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "blocked_by_guard",
                        "guard": "prompt_guard",
                        "reason_code": "POLICY_VIOLATION",
                        "severity": "MEDIUM",
                        "detail": reason,
                    },
                )
            if action == "warn":
                logger.warning("Prompt guard warning: %s", reason)
                policy_warning = True
            elif action == "log_only":
                logger.info("Prompt guard (log only): %s", reason)

    # Knowledge-base retrieval: only endpoints with a configured KB trigger
    # this. The default route passes endpoint=None and is skipped. A failing
    # KB must never break the request — forward without injected context.
    if endpoint is not None and endpoint.has_knowledge_base:
        retriever = get_retriever(
            endpoint.kb_type, endpoint.kb_url, endpoint.kb_collection
        )
        if retriever:
            try:
                docs = await retriever.retrieve(
                    user_content, endpoint.kb_top_k or 4
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Retrieval failed: %s", e)
                docs = []
            if docs:
                body["messages"] = inject_context(body["messages"], docs)

    headers = dict(request.headers)
    adapter = get_adapter(provider, AdapterConfig(upstream_url=upstream_url))
    upstream_start = time.monotonic()
    try:
        result = await adapter.forward(body, headers)
    except HTTPException as exc:
        await emit(
            EventType.UPSTREAM_ERROR,
            severity="HIGH",
            key_id=key_id,
            endpoint_id=endpoint_id,
            detail={"status": exc.status_code},
            request_id=request_id,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        await emit(
            EventType.UPSTREAM_ERROR,
            severity="HIGH",
            key_id=key_id,
            endpoint_id=endpoint_id,
            detail={"status": 500, "error": str(exc)},
            request_id=request_id,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    upstream_latency = int((time.monotonic() - upstream_start) * 1000)
    await emit(
        EventType.UPSTREAM_REQUEST,
        key_id=key_id,
        endpoint_id=endpoint_id,
        detail={"provider": provider, "model": body.get("model")},
        latency_ms=upstream_latency,
        request_id=request_id,
    )
    response = await _apply_output_guard(
        result,
        key_id=key_id,
        endpoint_id=endpoint_id,
        request_id=request_id,
        config=guard_config,
    )
    if policy_warning:
        # warn action: the policy flagged the message but we forwarded it.
        response.headers["X-Cerberus-Policy-Warning"] = "true"
    return response


def _extract_assistant_content(result: dict) -> str | None:
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) else None


async def _apply_output_guard(
    result: dict,
    key_id: int | None = None,
    endpoint_id: int | None = None,
    request_id: str | None = None,
    config: GuardConfig = DEFAULT_GUARD_CONFIG,
) -> JSONResponse:
    action = os.getenv("CERBERUS_OUTPUT_GUARD_ACTION", "redact").lower()
    content = _extract_assistant_content(result)
    if not content:
        await emit(
            EventType.OUTPUT_GUARD_PASSED,
            key_id=key_id,
            endpoint_id=endpoint_id,
            request_id=request_id,
        )
        return JSONResponse(content=result)

    if action == "block":
        scan = await _output_guard.scan(content, config)
        if not scan.passed:
            await emit(
                EventType.OUTPUT_GUARD_BLOCKED,
                severity="HIGH",
                key_id=key_id,
                endpoint_id=endpoint_id,
                detail={
                    "reason_code": scan.reason_code.value,
                    "severity": scan.severity.value,
                    "detail": scan.detail,
                },
                request_id=request_id,
            )
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
        await emit(
            EventType.OUTPUT_GUARD_PASSED,
            key_id=key_id,
            endpoint_id=endpoint_id,
            request_id=request_id,
        )
        return JSONResponse(content=result)

    if action == "log_only":
        scan = await _output_guard.scan(content, config)
        if not scan.passed:
            logger.warning(
                "output_guard log_only — would block: %s/%s — %s",
                scan.reason_code.value,
                scan.severity.value,
                scan.detail,
            )
        await emit(
            EventType.OUTPUT_GUARD_PASSED,
            key_id=key_id,
            endpoint_id=endpoint_id,
            request_id=request_id,
        )
        return JSONResponse(content=result)

    # default action: redact
    redacted, names = _output_guard.redact(content, config)
    if names:
        result["choices"][0]["message"]["content"] = redacted
        await emit(
            EventType.OUTPUT_GUARD_REDACTED,
            severity="MEDIUM",
            key_id=key_id,
            endpoint_id=endpoint_id,
            detail={"redacted_types": names},
            request_id=request_id,
        )
        return JSONResponse(
            content=result,
            headers={"X-Cerberus-Redacted": ",".join(names)},
        )
    await emit(
        EventType.OUTPUT_GUARD_PASSED,
        key_id=key_id,
        endpoint_id=endpoint_id,
        request_id=request_id,
    )
    return JSONResponse(content=result)


@app.post("/v1/chat/completions")
async def chat_completions_default(request: Request):
    provider = os.getenv("CERBERUS_PROVIDER", "openai")
    upstream = os.getenv("CERBERUS_UPSTREAM_URL", "https://api.openai.com")
    return await _forward(provider, upstream, request)


@app.post("/v1/chat/completions/{endpoint_id}")
async def chat_completions_endpoint(endpoint_id: int, request: Request):
    async with db.AsyncSessionLocal() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.get_by_id(endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return await _forward(
        endpoint.provider,
        endpoint.upstream_url,
        request,
        endpoint_id=endpoint_id,
        endpoint=endpoint,
    )


def start():
    uvicorn.run("cerberus_proxy.proxy.main:app", host="0.0.0.0", port=8000, reload=False)  # nosec B104
