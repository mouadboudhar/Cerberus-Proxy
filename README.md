<p align="center">
  <img src="docs/assets/logo.png" alt="Cerberus Proxy" width="300"/>
</p>

<p align="center">
  <strong>Cerberus Proxy</strong><br/>
  Deterministic security gateway for LLM applications.
  Two-line integration. Runs in your infrastructure.
</p>

---

## Why Cerberus

LLM applications send untrusted user input to a provider and stream
untrusted model output back to users. That exposes two risks most apps
never handle: **prompt injection** going in, and **leaked PII or secrets**
coming out. Bolting checks onto every call site is error-prone and easy to
forget.

Cerberus Proxy moves that responsibility out of your application and into a
reverse proxy you control. It sits between your app and any LLM provider,
applies deterministic security guards to every request and response, and
gives you a dashboard and audit log over the whole thing. Your app keeps
talking plain OpenAI-style HTTP — you just point it at Cerberus instead of
the provider.

- **Deterministic by default** — the Input and Output guards are pattern- and
  rule-based, not model-based. Same input, same verdict, every time.
- **Self-hosted** — runs entirely in your infrastructure. No prompts, keys,
  or responses leave your network except the upstream call you already make.
- **Drop-in** — speaks the OpenAI Chat Completions API. Integration is a base
  URL change.

## How it works

Every request flows through a fixed pipeline before it reaches the provider,
and every response is scanned before it returns to your app:

1. **API key auth** — validate the caller's Cerberus key.
2. **Rate limiting & abuse detection** — per-key RPM / RPH / RPD limits.
3. **Input Guard** — deterministic prompt-injection detection (with
   translation of non-English prompts first).
4. **Prompt Guard** *(optional, per-endpoint)* — LLM-as-judge policy check.
5. **Knowledge-base retrieval** *(optional, per-endpoint)* — inject relevant
   documents from a vector store.
6. **Forward upstream** — through a provider adapter.
7. **Output Guard** — redact or block PII and secrets in the response.

Steps 3, 6 and 7 always run. Steps 4 and 5 run only when an endpoint is
configured for them, and both fail open — a guard or retrieval error never
turns a legitimate request into a 5xx.

![Architecture](docs/assets/architecture.png)

## Quick start

```bash
# 1. Clone
git clone <your-repo-url> cerberus-proxy && cd cerberus-proxy

# 2. Configure — set a strong dashboard token and your provider
cp .env.example .env
#    edit .env: CERBERUS_DASHBOARD_TOKEN, CERBERUS_UPSTREAM_URL, CERBERUS_PROVIDER

# 3. Run
docker compose up
```

The proxy is now on `http://localhost:8000` and the dashboard on
`http://localhost:5173` (log in with your `CERBERUS_DASHBOARD_TOKEN`).
See [docs/deployment.md](docs/deployment.md) for the full setup, including
translation-model download for the Input Guard.

## The two-line integration

Point your existing OpenAI-compatible client at Cerberus and use a Cerberus
API key instead of the provider key. Nothing else changes.

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",   # was: https://api.openai.com/v1
    api_key="cbrs_your_cerberus_key",       # was: your provider key
)

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Summarise this ticket..."}],
)
```

Cerberus authenticates the key, runs the guards, forwards to your configured
provider, scans the response, and returns it. Blocked requests come back as
`403`; rate-limited ones as `429`. Full examples — LangChain, per-endpoint
routing, error handling — are in [docs/integration.md](docs/integration.md).

## What the guards detect

| Guard | Type | Catches |
|-------|------|---------|
| **Input Guard** | Deterministic | Prompt injection, persona/jailbreak switches, system-prompt probes, encoded payloads, high-density obfuscation — across 12 languages via local translation. |
| **Output Guard** | Deterministic | PII and secrets in responses (emails, phone numbers, credit cards, API keys, private keys, high-entropy strings, and more) — redacted or blocked. |
| **Prompt Guard** | LLM-as-judge *(optional)* | Custom per-endpoint policy violations evaluated by a model. Non-deterministic; always fails open. |

Each guard is configurable per endpoint — disable individual rules, add custom
blocked phrases, restrict active languages, or choose redact / block / log-only
behaviour. See [docs/guards.md](docs/guards.md) for the full reference.

## Supported providers

OpenAI · Anthropic · Mistral · Ollama · Grok · NVIDIA

Selected per route via `CERBERUS_PROVIDER` (default route) or per endpoint in
the dashboard. Base URLs for each are listed in
[docs/integration.md](docs/integration.md).

## Documentation

- [Architecture](docs/architecture.md) — design principles, full pipeline, data model, limitations
- [Deployment](docs/deployment.md) — prerequisites, env-var reference, production notes
- [Integration](docs/integration.md) — the two-line change, providers, LangChain, error handling
- [Guards](docs/guards.md) — what each guard detects and how to configure it

## Tech stack

- **Proxy** — Python 3.11+, FastAPI, httpx, async SQLAlchemy 2.0 + aiosqlite
- **Input Guard translation** — lingua (detection) + Argos Translate (local, offline)
- **Retrieval** — ChromaDB
- **Dashboard** — React 18 + Vite
- **Deployment** — Docker Compose

## License

Apache-2.0. See [LICENSE](LICENSE).
