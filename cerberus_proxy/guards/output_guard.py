"""Deterministic output guard — scans upstream LLM responses for PII and secrets.

Component 1 of Stage 9: pattern library + Luhn validation + Shannon entropy.
The OutputGuard class itself is added in Component 2.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import NamedTuple

from cerberus_proxy.guards.base import Guard, GuardResult, ReasonCode, Severity


class PatternDef(NamedTuple):
    name: str
    regex: re.Pattern[str]
    reason_code: ReasonCode
    severity: Severity


def luhn_check(card_number: str) -> bool:
    """Validate a credit-card number with the Luhn algorithm.

    Spaces and dashes are stripped before checking. Returns True only when
    the digits form a valid Luhn checksum.
    """
    digits = card_number.replace(" ", "").replace("-", "")
    if not digits.isdigit() or len(digits) < 13:
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def calculate_entropy(s: str) -> float:
    """Shannon entropy of a string in bits per char. Higher means more random."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


# Pattern names that require Luhn validation on the matched text before
# being counted as a real hit.
LUHN_REQUIRED: frozenset[str] = frozenset({"CREDIT_CARD"})

# Context-dependent patterns: a match only counts if any of these keywords
# appears within CONTEXT_WINDOW chars on either side of the match
# (case-insensitive substring match).
CONTEXT_WINDOW = 100
CONTEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "PASSPORT": ("passport", "travel document"),
    "AWS_SECRET_ACCESS_KEY": ("aws", "secret", "key", "credential"),
    "AZURE_CLIENT_SECRET": ("azure", "client_secret", "tenant"),
    "SLACK_SIGNING_SECRET": ("slack", "signing_secret"),
    "TWILIO_AUTH_TOKEN": ("twilio", "auth_token"),
    "CIRCLECI_TOKEN": ("circleci", "circle_token"),
    "TRAVIS_TOKEN": ("travis", "travis_token"),
}

# High-entropy catch-all parameters (applied separately in Component 2 — the
# logic is not a single regex match).
HIGH_ENTROPY_MIN_LEN = 32
HIGH_ENTROPY_THRESHOLD = 4.5

_PII = ReasonCode.PII_DETECTED
_SEC = ReasonCode.SECRET_DETECTED


PATTERNS: list[PatternDef] = [
    # --- PII: credit cards (all share name CREDIT_CARD; Luhn required) ---
    PatternDef("CREDIT_CARD",
               re.compile(r"\b4[0-9]{12}(?:[0-9]{3})?\b"),
               _PII, Severity.CRITICAL),
    PatternDef("CREDIT_CARD",
               re.compile(r"\b5[1-5][0-9]{14}\b"),
               _PII, Severity.CRITICAL),
    PatternDef("CREDIT_CARD",
               re.compile(r"\b3[47][0-9]{13}\b"),
               _PII, Severity.CRITICAL),
    PatternDef("CREDIT_CARD",
               re.compile(r"\b6(?:011|5[0-9]{2})[0-9]{12}\b"),
               _PII, Severity.CRITICAL),
    PatternDef("CREDIT_CARD",
               re.compile(r"\b(?:\d[ -]?){13,16}\b"),
               _PII, Severity.CRITICAL),

    # --- PII: identifiers ---
    PatternDef("EMAIL",
               re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
               _PII, Severity.MEDIUM),
    PatternDef("SSN_US",
               re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
               _PII, Severity.CRITICAL),
    PatternDef("PHONE_US",
               re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
               _PII, Severity.LOW),
    PatternDef("PHONE_INTL",
               re.compile(r"\+(?:[0-9]{1,3}[-.\s]){2,}[0-9]{4,}\b"),
               _PII, Severity.LOW),
    PatternDef("IBAN",
               re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?){0,16}\b"),
               _PII, Severity.CRITICAL),
    PatternDef("UK_NIN",
               re.compile(r"\b[A-CEGHJ-PR-TW-Z]{1}[A-CEGHJ-NPR-TW-Z]{1}[0-9]{6}[A-D\s]\b"),
               _PII, Severity.CRITICAL),
    PatternDef("PASSPORT",
               re.compile(r"\b[A-Z]{1,2}[0-9]{6,9}\b"),
               _PII, Severity.HIGH),
    PatternDef("DOB",
               re.compile(
                   r"\b(?:DOB|date.of.birth|born.on|birthday)[:\s]+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
                   re.IGNORECASE,
               ),
               _PII, Severity.MEDIUM),
    PatternDef("IP_PRIVATE",
               re.compile(
                   r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"
               ),
               _PII, Severity.LOW),

    # --- Secrets: OpenAI / Anthropic (project pattern first so longer match wins) ---
    PatternDef("OPENAI_API_KEY",
               re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{32,}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("OPENAI_API_KEY",
               re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("ANTHROPIC_API_KEY",
               re.compile(r"\bsk-ant-api\d{2}-[A-Za-z0-9_\-]{93,}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: AWS ---
    PatternDef("AWS_ACCESS_KEY_ID",
               re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("AWS_SECRET_ACCESS_KEY",
               re.compile(r"\b[A-Za-z0-9/+=]{40}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("AWS_SESSION_TOKEN",
               re.compile(r"\bFQoGZXIvYXdzE[A-Za-z0-9/+=]{100,}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: Google / GCP ---
    PatternDef("GOOGLE_API_KEY",
               re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("GOOGLE_OAUTH_SECRET",
               re.compile(r"\bGOCSPS-[A-Za-z0-9_\-]{24}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("GOOGLE_SA_PRIVATE_KEY_ID",
               re.compile(r'"private_key_id":\s*"[a-f0-9]{40}"'),
               _SEC, Severity.CRITICAL),
    PatternDef("GCP_SA_EMAIL",
               re.compile(r"\b[a-z0-9\-]+@[a-z0-9\-]+\.iam\.gserviceaccount\.com\b"),
               _SEC, Severity.MEDIUM),

    # --- Secrets: Azure ---
    PatternDef("AZURE_CONNECTION_STRING",
               re.compile(
                   r"DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{88}"
               ),
               _SEC, Severity.CRITICAL),
    PatternDef("AZURE_SAS_TOKEN",
               re.compile(r"sv=\d{4}-\d{2}-\d{2}&s[sr]=[a-z]+&sig=[A-Za-z0-9%/+=]+"),
               _SEC, Severity.CRITICAL),
    PatternDef("AZURE_CLIENT_SECRET",
               re.compile(r"\b[A-Za-z0-9~._\-]{34}~[A-Za-z0-9~._\-]{8}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: GitHub ---
    PatternDef("GITHUB_PAT",
               re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("GITHUB_OAUTH",
               re.compile(r"\bgho_[A-Za-z0-9]{36}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("GITHUB_ACTIONS",
               re.compile(r"\bghs_[A-Za-z0-9]{36}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("GITHUB_REFRESH",
               re.compile(r"\bghr_[A-Za-z0-9]{76}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("GITHUB_FINE_GRAINED_PAT",
               re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: GitLab ---
    PatternDef("GITLAB_PAT",
               re.compile(r"\bglpat-[A-Za-z0-9_\-]{20}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("GITLAB_PIPELINE_TRIGGER",
               re.compile(r"\bglptt-[A-Za-z0-9_\-]{20}\b"),
               _SEC, Severity.HIGH),

    # --- Secrets: Stripe ---
    PatternDef("STRIPE_LIVE_KEY",
               re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("STRIPE_TEST_KEY",
               re.compile(r"\bsk_test_[A-Za-z0-9]{24,}\b"),
               _SEC, Severity.MEDIUM),
    PatternDef("STRIPE_WEBHOOK",
               re.compile(r"\bwhsec_[A-Za-z0-9]{32,}\b"),
               _SEC, Severity.HIGH),

    # --- Secrets: Slack ---
    PatternDef("SLACK_TOKEN",
               re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("SLACK_WEBHOOK",
               re.compile(
                   r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"
               ),
               _SEC, Severity.HIGH),
    PatternDef("SLACK_SIGNING_SECRET",
               re.compile(r"\b[a-f0-9]{32}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: Twilio ---
    PatternDef("TWILIO_ACCOUNT_SID",
               re.compile(r"\bAC[a-f0-9]{32}\b"),
               _SEC, Severity.HIGH),
    PatternDef("TWILIO_AUTH_TOKEN",
               re.compile(r"\b[a-f0-9]{32}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: email services ---
    PatternDef("SENDGRID_KEY",
               re.compile(r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("MAILGUN_KEY",
               re.compile(r"\bkey-[A-Za-z0-9]{32}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("MAILCHIMP_KEY",
               re.compile(r"\b[A-Za-z0-9]{32}-us\d{1,2}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: DB connection strings ---
    PatternDef("POSTGRES_URL",
               re.compile(r"postgres(?:ql)?(?:s)?://[^:]+:[^@]+@[^/\s]+"),
               _SEC, Severity.CRITICAL),
    PatternDef("MYSQL_URL",
               re.compile(r"mysql(?:2)?://[^:]+:[^@]+@[^/\s]+"),
               _SEC, Severity.CRITICAL),
    PatternDef("MONGODB_URL",
               re.compile(r"mongodb(?:\+srv)?://[^:]+:[^@]+@\S+"),
               _SEC, Severity.CRITICAL),
    PatternDef("REDIS_URL_WITH_PASSWORD",
               re.compile(r"redis://:([^@]+)@\S+"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: NPM / PyPI ---
    PatternDef("NPM_TOKEN",
               re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("PYPI_TOKEN",
               re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}\b"),
               _SEC, Severity.CRITICAL),

    # --- Secrets: CI/CD ---
    PatternDef("CIRCLECI_TOKEN",
               re.compile(r"\b[a-f0-9]{40}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("TRAVIS_TOKEN",
               re.compile(r"\b[A-Za-z0-9_\-]{22}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("VAULT_TOKEN",
               re.compile(r"\bs\.[A-Za-z0-9]{24}\b"),
               _SEC, Severity.CRITICAL),
    PatternDef("HUGGINGFACE_TOKEN",
               re.compile(r"\bhf_[A-Za-z0-9]{37}\b"),
               _SEC, Severity.HIGH),

    # --- Cryptographic material (full PEM blocks: BEGIN through END) ---
    PatternDef("RSA_PRIVATE_KEY",
               re.compile(
                   r"-----BEGIN\s+RSA\s+PRIVATE\s+KEY-----[\s\S]+?"
                   r"-----END\s+RSA\s+PRIVATE\s+KEY-----",
                   re.DOTALL,
               ),
               _SEC, Severity.CRITICAL),
    PatternDef("EC_PRIVATE_KEY",
               re.compile(
                   r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----[\s\S]+?"
                   r"-----END\s+EC\s+PRIVATE\s+KEY-----",
                   re.DOTALL,
               ),
               _SEC, Severity.CRITICAL),
    PatternDef("PRIVATE_KEY",
               re.compile(
                   r"-----BEGIN\s+PRIVATE\s+KEY-----[\s\S]+?"
                   r"-----END\s+PRIVATE\s+KEY-----",
                   re.DOTALL,
               ),
               _SEC, Severity.CRITICAL),
    PatternDef("PGP_PRIVATE_KEY",
               re.compile(
                   r"-----BEGIN\s+PGP\s+PRIVATE\s+KEY\s+BLOCK-----[\s\S]+?"
                   r"-----END\s+PGP\s+PRIVATE\s+KEY\s+BLOCK-----",
                   re.DOTALL,
               ),
               _SEC, Severity.CRITICAL),
    PatternDef("CERTIFICATE",
               re.compile(r"-----BEGIN\s+CERTIFICATE-----"),
               _SEC, Severity.CRITICAL),
    PatternDef("SSH_PRIVATE_KEY",
               re.compile(
                   r"-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----[\s\S]+?"
                   r"-----END\s+OPENSSH\s+PRIVATE\s+KEY-----",
                   re.DOTALL,
               ),
               _SEC, Severity.CRITICAL),

    # --- JWT (HIGH — not always a secret, but may carry sensitive claims) ---
    PatternDef("JWT",
               re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
               _SEC, Severity.HIGH),
]


HIGH_ENTROPY_NAME = "HIGH_ENTROPY_STRING"

_HIGH_ENTROPY_CANDIDATE = re.compile(r"\S{" + str(HIGH_ENTROPY_MIN_LEN) + r",}")
_URL_PREFIX = re.compile(r"^https?://", re.IGNORECASE)
_PEM_BLOCK = re.compile(r"-----BEGIN[ A-Z]+-----[\s\S]+?-----END[ A-Z]+-----")
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/=]+")


def _has_context(content: str, start: int, end: int, keywords: tuple[str, ...]) -> bool:
    lo = max(0, start - CONTEXT_WINDOW)
    hi = min(len(content), end + CONTEXT_WINDOW)
    window = content[lo:hi].lower()
    return any(kw.lower() in window for kw in keywords)


def _find_high_entropy(content: str) -> list[dict]:
    pem_spans = [(m.start(), m.end()) for m in _PEM_BLOCK.finditer(content)]
    out: list[dict] = []
    for m in _HIGH_ENTROPY_CANDIDATE.finditer(content):
        s = m.group(0)
        if _URL_PREFIX.match(s):
            continue
        if "/" in s or "\\" in s:
            continue
        if len(set(s)) <= 2:
            continue
        # Base64 body lines inside a PEM block are already covered by the
        # full PEM block match — don't double-flag them as high entropy.
        if (
            any(ps <= m.start() and m.end() <= pe for ps, pe in pem_spans)
            and _BASE64_RUN.fullmatch(s)
            and len(s) % 4 == 0
        ):
            continue
        if calculate_entropy(s) <= HIGH_ENTROPY_THRESHOLD:
            continue
        out.append({
            "name": HIGH_ENTROPY_NAME,
            "start": m.start(),
            "end": m.end(),
            "matched_text": s,
            "reason_code": ReasonCode.SECRET_DETECTED,
            "severity": Severity.HIGH,
            "detail": "High-entropy string detected — likely secret or token",
        })
    return out


def _dedup_overlaps(matches: list[dict]) -> list[dict]:
    """Drop matches that overlap a kept span.

    Priority: named matches beat high-entropy catch-all regardless of length;
    among same-priority matches, longer span wins; ties keep input order.
    """
    def _priority(item: tuple[int, dict]) -> tuple[int, int, int]:
        idx, m = item
        is_named = 0 if m["name"] == HIGH_ENTROPY_NAME else 1
        length = m["end"] - m["start"]
        return (is_named, length, -idx)

    ranked = sorted(enumerate(matches), key=_priority, reverse=True)
    kept_spans: list[tuple[int, int]] = []
    keep_idx: set[int] = set()
    for orig_idx, m in ranked:
        s, e = m["start"], m["end"]
        if any(s < ke and e > ks for ks, ke in kept_spans):
            continue
        kept_spans.append((s, e))
        keep_idx.add(orig_idx)
    return [m for i, m in enumerate(matches) if i in keep_idx]


class OutputGuard(Guard):
    """Stateless deterministic guard for upstream LLM responses."""

    async def scan(self, content: str) -> GuardResult:
        matches = self.find_all_matches(content)
        if not matches:
            return GuardResult(
                passed=True,
                reason_code=ReasonCode.CLEAN,
                severity=Severity.LOW,
                detail="No PII or secrets detected",
            )
        first = matches[0]
        return GuardResult(
            passed=False,
            reason_code=first["reason_code"],
            severity=first["severity"],
            detail=first["detail"],
            matched_pattern=first["name"],
        )

    def find_all_matches(self, content: str) -> list[dict]:
        matches: list[dict] = []
        for pdef in PATTERNS:
            for m in pdef.regex.finditer(content):
                text = m.group(0)
                if pdef.name in LUHN_REQUIRED and not luhn_check(text):
                    continue
                if pdef.name in CONTEXT_KEYWORDS and not _has_context(
                    content, m.start(), m.end(), CONTEXT_KEYWORDS[pdef.name]
                ):
                    continue
                detail = (
                    "JWT token detected — may contain sensitive claims"
                    if pdef.name == "JWT"
                    else f"Matched pattern: {pdef.name}"
                )
                matches.append({
                    "name": pdef.name,
                    "start": m.start(),
                    "end": m.end(),
                    "matched_text": text,
                    "reason_code": pdef.reason_code,
                    "severity": pdef.severity,
                    "detail": detail,
                })
        matches.extend(_find_high_entropy(content))
        return _dedup_overlaps(matches)

    def redact(self, content: str) -> tuple[str, list[str]]:
        matches = self.find_all_matches(content)
        for m in sorted(matches, key=lambda x: x["start"], reverse=True):
            content = content[: m["start"]] + f"[REDACTED:{m['name']}]" + content[m["end"]:]
        names = sorted({m["name"] for m in matches})
        return content, names
