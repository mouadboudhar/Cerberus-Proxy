# Integration

Cerberus Proxy speaks the OpenAI Chat Completions API. Integrating it means
pointing your existing client at the proxy and using a Cerberus API key. No
SDK, no client-side security code, no request reshaping.

## The two-line change

Whatever OpenAI-compatible client you already use, change two things:

1. the **base URL** → your Cerberus proxy
2. the **API key** → a Cerberus key (`llmg_…`), created in the dashboard

### Before

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.openai.com/v1",
    api_key="sk-...your-openai-key...",
)

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Summarise this support ticket..."}],
)
```

### After

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",   # ← Cerberus proxy
    api_key="llmg_...your-cerberus-key...", # ← Cerberus key
)

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Summarise this support ticket..."}],
)
```

Your provider key never leaves the proxy configuration; the application only
ever holds a Cerberus key. Cerberus authenticates the key, runs the guards,
forwards to the configured provider, scans the response, and returns it in the
same shape your client already expects.

## Supported providers

The default route's provider is set with `CERBERUS_PROVIDER` and its upstream
with `CERBERUS_UPSTREAM_URL`; per-endpoint routes set both in the dashboard.
Use the provider's API **base URL** as the upstream — the adapter appends the
correct path itself.

| Provider | `CERBERUS_PROVIDER` | Upstream base URL |
|----------|---------------------|-------------------|
| OpenAI | `openai` | `https://api.openai.com` |
| Anthropic | `anthropic` | `https://api.anthropic.com/v1` |
| Mistral | `mistral` | `https://api.mistral.ai` |
| Ollama | `ollama` | `http://<your-ollama-host>:11434` |
| Grok (x.ai) | `grok` | `https://api.x.ai` |
| NVIDIA | `nvidia` | `https://integrate.api.nvidia.com` |

Grok and NVIDIA use the OpenAI-compatible adapter. The Anthropic adapter
translates between the OpenAI Chat Completions shape your client sends and
Anthropic's Messages API, so your client code stays identical regardless of the
provider behind the endpoint.

## LangChain

LangChain's OpenAI integration takes the same two parameters:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o-mini",
    base_url="http://localhost:8000/v1",   # ← Cerberus proxy
    api_key="llmg_...your-cerberus-key...", # ← Cerberus key
)

llm.invoke("Summarise this support ticket...")
```

Everything downstream — chains, agents, retrievers — works unchanged, since the
proxy preserves the request/response contract.

## Per-endpoint routing

The default route `POST /v1/chat/completions` uses the process-level provider
and the all-rules-on guard config. To apply per-tenant routing or per-endpoint
guard policy (disabled rules, custom blocked phrases, active languages, a
knowledge base, or the Prompt Guard), create an **endpoint** in the dashboard
and call it by id:

```
POST /v1/chat/completions/{endpoint_id}
```

Point your client's base URL at it:

```python
client = OpenAI(
    base_url="http://localhost:8000/v1/chat/completions/3",  # endpoint #3
    api_key="llmg_...",
)
```

Each endpoint carries its own provider, upstream URL, and guard configuration,
so you can route different applications or tenants through different policies
without changing any client code beyond the URL.

## Handling blocked responses (403)

When a guard blocks a request, Cerberus returns **HTTP 403** with a structured
body identifying which guard fired and why:

```json
{
  "error": "blocked_by_guard",
  "guard": "input_guard",
  "reason_code": "OVERRIDE_ATTEMPT",
  "severity": "CRITICAL",
  "detail": "Matched pattern: ignore-previous-instructions"
}
```

`guard` is one of `input_guard`, `prompt_guard`, or `output_guard` (the last
only when the Output Guard is in `block` mode). Handle it explicitly rather
than treating it as a transport error:

```python
import httpx
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="llmg_...")

try:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": user_input}],
    )
except httpx.HTTPStatusError as e:
    if e.response.status_code == 403:
        body = e.response.json()
        # body["guard"], body["reason_code"], body["detail"]
        show_user("That request was blocked by a security policy.")
    else:
        raise
```

> The OpenAI SDK raises its own error types (e.g. `openai.PermissionDeniedError`
> for 403). Catch whatever your client surfaces for a 403 — the JSON body shape
> above is the same regardless.

When the Output Guard runs in **redact** mode (the default), the request is not
blocked: the response is returned with sensitive spans replaced and an
`X-Cerberus-Redacted` header listing the redacted types. In **warn** mode the
Prompt Guard forwards the response and sets `X-Cerberus-Policy-Warning: true`.
Read those headers if you want to surface or log that something was modified or
flagged.

## Handling rate limits (429)

Per-key rate limits (RPM / RPH / RPD) return **HTTP 429** with a `Retry-After`
header and a body naming the window that was exceeded:

```json
{
  "error": "rate_limit_exceeded",
  "window": "rpm",
  "limit": 60,
  "retry_after": 42
}
```

Respect `Retry-After` (seconds) and back off:

```python
import time, httpx

def call_with_retry(client, **kwargs):
    for attempt in range(3):
        try:
            return client.chat.completions.create(**kwargs)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < 2:
                time.sleep(int(e.response.headers.get("Retry-After", 1)))
                continue
            raise
```

Tune per-key limits in the dashboard, or the deployment-wide defaults via
`CERBERUS_DEFAULT_RPM` / `_RPH` / `_RPD` (see [deployment.md](deployment.md)).
