# Deployment

How to deploy and operate Cerberus Proxy. The supported deployment is Docker
Compose; a local Python install is also documented for development.

## Prerequisites

- **Docker** and the **Docker Compose** plugin (`docker compose`, v2).
- An **upstream LLM provider** and a provider API key for it (OpenAI,
  Anthropic, Mistral, Ollama, Grok, or NVIDIA). For self-hosted Ollama, the
  reachable base URL of your Ollama server.
- A free **port 8000** (proxy) and **5173** (dashboard) on the host, or edit
  the published ports in `docker-compose.yml`.

For a local (non-Docker) install only: **Python 3.11+**.

## Quick start

```bash
git clone <your-repo-url> cerberus-proxy && cd cerberus-proxy
cp .env.example .env
# edit .env — at minimum set CERBERUS_DASHBOARD_TOKEN, CERBERUS_UPSTREAM_URL,
# and CERBERUS_PROVIDER
docker compose up -d
```

This starts two containers:

- **cerberus-proxy** on `http://localhost:8000` — the gateway and admin API.
- **cerberus-dashboard** on `http://localhost:5173` — the admin UI, which waits
  for the proxy to report healthy before starting.

Open the dashboard and log in with the value of `CERBERUS_DASHBOARD_TOKEN`.

State (the SQLite database) lives in the named Docker volume `cerberus-data`,
mounted at `/app/data` in the proxy container, so it survives container
restarts and recreation.

## Environment variables

Set these in `.env` (read by `docker compose`). All have defaults except the
dashboard token, which you must change before exposing the service.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CERBERUS_DASHBOARD_TOKEN` | **Yes** | `change-me` | Shared secret for the dashboard, audit API, and event WebSocket. If unset, those endpoints reject all clients. **Set a strong random value.** |
| `CERBERUS_UPSTREAM_URL` | No | `https://api.openai.com` | Upstream base URL for the **default route** (`/v1/chat/completions`). |
| `CERBERUS_PROVIDER` | No | `openai` | Provider adapter for the default route: `openai`, `anthropic`, `mistral`, `ollama`, `grok`, or `nvidia`. |
| `CERBERUS_DEFAULT_RPM` | No | `60` | Default per-key requests per minute. Overridable per key. |
| `CERBERUS_DEFAULT_RPH` | No | `1000` | Default per-key requests per hour. |
| `CERBERUS_DEFAULT_RPD` | No | `10000` | Default per-key requests per day. |
| `CERBERUS_OUTPUT_GUARD_ACTION` | No | `redact` | Output Guard mode: `redact`, `block`, or `log_only`. |
| `CERBERUS_TRANSLATE_TIMEOUT` | No | `1.0` | Per-request translation budget (seconds) for the Input Guard. On timeout the guard falls back to scanning the original text. |
| `CERBERUS_DB_PATH` | No | `cerberus.db` (Docker: `/app/data/cerberus.db`) | SQLite database path. Compose sets the Docker value; a bare path is resolved relative to the working directory. |
| `CERBERUS_CORS_ORIGINS` | No | `http://localhost:5173,http://localhost:4173` | Comma-separated origins allowed to call the API cross-origin. Not needed when the dashboard is same-origin. |
| `CERBERUS_DEFAULT_CLEARANCE` | No | `INTERNAL` | **Reserved / currently unused.** Left over from the descoped Retrieval AuthZ feature; present in `.env.example` but read by no current code. Safe to ignore. |

Per-key rate limits and all per-endpoint guard configuration (disabled rules,
custom phrases, active languages, knowledge base, Prompt Guard) are set in the
**dashboard**, not via environment variables.

## First-run checklist

1. **Set a strong `CERBERUS_DASHBOARD_TOKEN`.** Generate one, e.g.
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Without it
   the dashboard and audit API reject every request.
2. **Point the default route at your provider** via `CERBERUS_UPSTREAM_URL` and
   `CERBERUS_PROVIDER`.
3. **Bring the stack up:** `docker compose up -d`.
4. **Confirm health:** `curl http://localhost:8000/health` returns
   `{"status":"ok",...}`.
5. **Log in** to the dashboard at `http://localhost:5173` with the token.
6. **Create an API key** in the dashboard. The plaintext `llmg_…` value is
   shown **once** — copy it now; only its hash is stored.
7. **(Optional) Create endpoints** for per-tenant routing and per-endpoint
   guard policy, knowledge bases, or the Prompt Guard.
8. **Send a test request** through the proxy (see
   [integration.md](integration.md)) and watch it appear live in the dashboard
   event stream.

## Language model setup

The Input Guard detects non-English prompts and translates them locally (via
Argos Translate) before running its pattern checks. Detection covers 12
languages: English, French, Spanish, Arabic, German, Portuguese, Italian,
Dutch, Russian, Chinese, Japanese, Turkish.

**Local / pip install.** Download the translation models once after install:

```bash
python scripts/download_models.py
```

Each `<lang> → en` model is fetched and cached locally (~100 MB per pair). The
script is idempotent — re-running installs only what is missing — and once
installed, no internet connection is needed.

**Docker.** The shipped image does **not** bake in the translation models, and
the `scripts/` directory is not part of the image. Without the models present,
the Input Guard still works but with reduced multilingual coverage: it relies
on the built-in non-English fast-path patterns (German, Spanish, French,
Portuguese) plus the English patterns, and the translation step fails open. The
deterministic English detection and the Output Guard are unaffected. If you
need full translation-based coverage in Docker, extend the image to install the
models at build time — note that Argos models are stored in the library's data
directory, which is not the persisted `/app/data` volume, so baking them into
the image is the durable approach.

## Updating the deployment

```bash
git pull
docker compose build
docker compose up -d
```

Schema changes are applied automatically on startup by idempotent migrations,
so the `cerberus-data` volume carries forward across updates with no manual
step. Your endpoints, keys, and audit history are preserved. To inspect what
changed before updating, review the release notes / commit log.

## Production considerations

- **Terminate TLS in front of Cerberus.** The proxy serves plain HTTP on 8000.
  Put it behind a reverse proxy / load balancer (nginx, Caddy, a cloud LB) that
  terminates HTTPS, and do not expose port 8000 directly to the internet.
- **Protect the dashboard token.** It grants full admin and audit access. Keep
  it in a secrets manager, rotate it periodically, and restrict who can reach
  the dashboard port.
- **Restrict `CERBERUS_CORS_ORIGINS`** to the exact origins that need
  cross-origin API access; do not widen it to `*`.
- **Back up the data volume.** Snapshot `cerberus-data` (or the
  `CERBERUS_DB_PATH` file) on a schedule — it holds your endpoints, key hashes,
  and the audit log.
- **Set rate limits deliberately.** The defaults are generous; tune
  `CERBERUS_DEFAULT_*` and per-key limits to your traffic and cost ceiling.
- **Choose the Output Guard mode for your risk posture.** `redact` (default) is
  safest for most apps; use `log_only` while tuning rules, and `block` when any
  leak must hard-fail.
- **Single-node by design.** Cerberus uses SQLite and is built to run as one
  gateway instance. Scale vertically; it is not designed for multiple instances
  sharing one database.
- **Persist translation models** if you depend on multilingual detection (see
  above) — otherwise non-English coverage falls back to the fast-path patterns.
- **Monitor `/health`.** The compose healthcheck already polls it; wire it into
  your external monitoring too.
