# Architecture

This document explains how Cerberus Proxy is built and why. It covers the
design principles, the full request pipeline, the internals of the Input and
Output guards, the data model, and the system's known limitations.

## Design principles

**Deterministic security first.** The two guards that run on every request —
Input and Output — are pattern- and rule-based, never model-based. A given
input always produces the same verdict. This is what makes the gateway
auditable: you can point at the exact pattern that blocked a request. The
optional Prompt Guard is the one model-based component, and it is explicitly
scoped as *policy* enforcement, not security, precisely because it is
non-deterministic.

**Fail open on auxiliary paths, fail closed on the core.** The deterministic
Input and Output guards are mandatory and block when they fire. Everything
that depends on an external system or a model — translation, knowledge-base
retrieval, the Prompt Guard — *fails open*: if it errors or times out, the
request proceeds rather than returning a 5xx. The reasoning is that a
translation outage or a vector-store hiccup should degrade detection, not take
down the customer's application. Crucially, the Input Guard's multilingual
detection is designed so that even when translation fails, a parallel set of
non-English patterns still runs against the raw text.

**The proxy owns security, the application stays simple.** Customers should
not have to write or maintain security code at every call site. Integration is
a base-URL change; all policy lives in the proxy and its dashboard.

**Self-hosted, no data exfiltration.** Nothing leaves the customer's network
except the upstream LLM call they already intended to make. There is no
telemetry, no external policy service, no cloud dependency.

**Single deployable unit.** SQLite, an embedded translation engine, and a
static dashboard mean the whole system is `docker compose up` with no external
database, queue, or cache to operate.

## Request pipeline

Every chat-completion request flows through `_forward()` in
`cerberus_proxy/proxy/main.py`. The order is fixed:

1. **API key authentication** (`ApiKeyAuthMiddleware`) — the caller's Cerberus
   key is hashed and looked up; revoked or unknown keys are rejected before any
   work happens.
2. **Rate limiting** (`check_rate_limits`) — per-key RPM / RPH / RPD counters.
   Over-limit requests return `429`.
3. **Abuse detection** (`AbuseDetector`) — heuristic signals over the key's
   recent request history; signals are audited but do not block.
4. **Input Guard** (`InputGuard.scan`) — deterministic prompt-injection
   detection. A hit returns `403` with a structured `blocked_by_guard` body.
5. **Prompt Guard** *(optional, per-endpoint)* — LLM-as-judge policy check.
   Runs only when the endpoint enables it. Action is configurable: `block`
   (`403`), `warn` (forward with an `X-Cerberus-Policy-Warning` header), or
   `log_only`. Always fails open.
6. **Knowledge-base retrieval** *(optional, per-endpoint)* — when the endpoint
   has a configured vector store, relevant documents are fetched and injected
   as additional context. Fails open: a retrieval error forwards the request
   without injected context, and the original messages are never mutated.
7. **Upstream forward** — the request is handed to a provider adapter
   (`get_adapter`) and sent to the configured LLM provider. Upstream errors are
   audited and surfaced.
8. **Output Guard** (`_apply_output_guard`) — the assistant's response is
   scanned for PII and secrets and either redacted, blocked, or logged
   depending on `CERBERUS_OUTPUT_GUARD_ACTION`.

Steps 1–4, 7 and 8 always run. Steps 5 and 6 are per-endpoint opt-in and are
skipped entirely on the default route (`endpoint is None`).

Every step emits an audit event through `emit()`, which persists to SQLite and
broadcasts over a WebSocket so the dashboard sees activity live.

## Input Guard pipeline

The Input Guard (`cerberus_proxy/guards/input_guard.py`) is the most involved
component because prompt injection arrives obfuscated, misspelled, encoded, and
in many languages. `InputGuard.scan` runs these stages in order:

1. **Custom blocked phrases.** If the endpoint defines phrases, an exact
   case-insensitive substring match blocks immediately — before any
   normalisation or pattern matching. This is the customer's escape hatch for
   domain-specific terms.
2. **Normalisation** (`_normalise`). NFKC Unicode normalisation, then a narrow
   Cyrillic-homoglyph fold (e.g. Cyrillic `а` → Latin `a`) so confusable
   characters cannot smuggle a payload past the regexes.
3. **Multilingual fast path** (`_scan_multilingual`). A parallel set of
   non-English injection patterns (German, Spanish, French, Portuguese) runs
   directly against the normalised original text. This path exists so that
   non-English attacks are still caught even if translation fails or strips the
   attacker's verb.
4. **Typo normalisation** (`normalize_typos`). Words within fuzzy edit distance
   of a known attack keyword (`ignore`, `disregard`, `instructions`, …) are
   rewritten to the canonical token, so `"ingore all prveious instructons"`
   collapses onto a form the patterns match. A length floor and a 0.75
   similarity cutoff keep benign English from being rewritten.
5. **Translation to English** (`to_english`). lingua detects the source
   language; if it is non-English (and, when the endpoint restricts active
   languages, in the allowlist), Argos Translate translates locally to English.
   The translated copy is used *only* for pattern matching — the original input
   is always what gets forwarded upstream. This stage has a hard timeout
   (`CERBERUS_TRANSLATE_TIMEOUT`, default 1.0s) and fails open to the original
   text.
6. **Deterministic scan over variants** (`_scan_text`). The guard scans up to
   four de-duplicated variants — the translated copy, the homoglyph-folded
   original, and the typo-normalised forms of each — against:
   - the **regex pattern library** (override attempts, persona/jailbreak
     switches, system-prompt probes, encoded-payload markers),
   - **base64 payload decoding** (`_scan_base64_payloads`) — decodes embedded
     base64 and checks the plaintext for injection markers,
   - **instruction density** (`_scan_density`) — blocks text whose share of
     imperative verbs exceeds a threshold, catching command-stuffing that no
     single pattern covers.

   The first hit on any variant blocks. Each rule category can be disabled per
   endpoint by `ReasonCode` name.

Translation supports detection across 12 languages (English, French, Spanish,
Arabic, German, Portuguese, Italian, Dutch, Russian, Chinese, Japanese,
Turkish). Models are downloaded once and run fully offline.

## Output Guard pipeline

The Output Guard (`cerberus_proxy/guards/output_guard.py`) scans the
assistant's response text for PII and secrets. It is a pattern library of
`PatternDef` entries, each with a name, regex, reason code, and severity, plus
two refinements that cut false positives:

- **Validation.** Credit-card matches must pass a Luhn checksum
  (`luhn_check`) before counting as a hit.
- **Context gating.** Some patterns (passports, cloud provider secrets such as
  AWS/Azure/Slack/Twilio) only count when a relevant keyword appears within a
  100-character window of the match, so a bare random string is not flagged as
  an AWS secret without "aws"/"secret"/"key" nearby.
- **High-entropy catch-all.** Strings at least 32 characters long whose Shannon
  entropy (`calculate_entropy`) exceeds 4.5 bits/char are flagged as likely
  secrets, catching credentials no explicit pattern covers.

The guard runs in one of three modes set by `CERBERUS_OUTPUT_GUARD_ACTION`:

- **`redact`** (default) — matched spans are replaced with a typed placeholder
  and the response is returned with an `X-Cerberus-Redacted` header listing the
  redacted types.
- **`block`** — any hit returns `403` instead of the response.
- **`log_only`** — hits are logged and audited, but the response passes through
  unchanged. Useful for tuning before enforcing.

Individual output rules can be disabled per endpoint by pattern name, and the
high-entropy heuristic can be toggled independently.

## Data model

Cerberus stores configuration and audit data in **SQLite**, accessed
asynchronously via SQLAlchemy 2.0 + aiosqlite.

### Why SQLite

The deployment target is a single self-hosted gateway, not a horizontally
scaled fleet. SQLite removes an entire operational dependency: there is no
separate database server to provision, back up, secure, or keep on the network
path of every request. A single file on a Docker volume is the whole state. The
write volume — endpoint/key configuration plus an append-only audit log — is
well within SQLite's comfort zone, and reads are local-disk fast. If a
deployment ever outgrows it, the async-SQLAlchemy data layer means the schema
and queries are portable to Postgres without touching application logic.

Schema migrations are handled by small idempotent `ALTER TABLE` routines in
`db.py` (guarded by `PRAGMA table_info`), so new columns roll forward on
startup without a migration framework.

### Endpoint vs API key model

These are two distinct concepts, deliberately decoupled:

- An **Endpoint** (`config/models.py:Endpoint`) is a named *upstream
  configuration*: which provider, which upstream URL, default model, and all
  per-endpoint guard settings — disabled rules, custom blocked phrases, active
  languages, knowledge-base connection, and Prompt Guard policy. Endpoints are
  reached at `POST /v1/chat/completions/{endpoint_id}`.
- An **API key** (`auth/models.py:ApiKey`) is a *credential* for calling the
  proxy. It carries its own rate limits and a soft reference to an endpoint.
  Keys are stored only as SHA-256 hashes (the plaintext `llmg_…` value is shown
  once at creation and never persisted).

The default route `POST /v1/chat/completions` has no endpoint: it uses the
process-level `CERBERUS_PROVIDER` / `CERBERUS_UPSTREAM_URL` and the all-rules-on
default guard config. This keeps the simplest possible integration working with
zero dashboard configuration, while endpoints layer on per-tenant routing and
policy when needed.

The separation means one key can be scoped to a specific endpoint, multiple
keys can share an endpoint with different rate limits, and an endpoint's
security policy can change without reissuing keys.

## Known limitations

We would rather state these plainly than have them discovered in production:

- **Translation quality is uneven.** Argos Translate is local and free but not
  state of the art. Some language pairs translate awkwardly, which can blunt
  the translation-based detection path. The multilingual fast-path patterns
  (DE/ES/FR/PT) exist precisely to backstop this, but the other supported
  languages rely on translation succeeding. The Spanish model in particular has
  been the weakest in testing.
- **The Prompt Guard is non-deterministic.** It calls an LLM to judge policy
  compliance. Verdicts can vary between identical runs, it adds latency and
  cost (one extra LLM round-trip), and it always fails open. It is a policy
  convenience, not a security boundary — never rely on it to stop an attack the
  deterministic guards should catch.
- **Pattern-based detection is bypassable in principle.** Deterministic guards
  catch known shapes of injection and known shapes of secrets. A sufficiently
  novel obfuscation or an unusual secret format can evade them. The guards
  reduce risk; they do not eliminate it.
- **No structured-address / name PII detection.** The Output Guard targets
  high-precision identifiers (emails, phone numbers, card numbers, keys). It
  does not attempt to detect physical addresses or personal names, which are
  too ambiguous for deterministic matching without unacceptable false-positive
  rates.
- **SQLite is single-writer.** This is the right trade for a single-node
  gateway but is not built for a multi-node, shared-database deployment.
- **The Output Guard inspects non-streaming JSON responses.** Responses are
  scanned after the full upstream reply is received.
