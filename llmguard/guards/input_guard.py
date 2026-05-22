import asyncio
import base64
import binascii
import os
import re
import unicodedata

from llmguard.guards.base import Guard, GuardResult, ReasonCode, Severity
from llmguard.guards.translator import to_english

_FLAGS = re.IGNORECASE | re.MULTILINE

PATTERNS: list[tuple[re.Pattern[str], ReasonCode, Severity, str]] = [
    # Override attempts (CRITICAL)
    (
        re.compile(
            r"ignore\s+((?:all|your|the|my)\s+)?(previous|prior|above)\s+instructions?",
            _FLAGS,
        ),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "ignore-previous-instructions",
    ),
    (
        re.compile(
            r"disregard\s+((?:all|your|the|my)\s+)?(previous|prior|above)\s+instructions?",
            _FLAGS,
        ),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "disregard-previous-instructions",
    ),
    (
        re.compile(
            r"forget\s+((?:all|your|the|my)\s+)?(previous|prior|above)\s+instructions?",
            _FLAGS,
        ),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "forget-previous-instructions",
    ),
    (
        re.compile(r"you\s+are\s+now\s+in\s+(developer|jailbreak|dan)\s+mode", _FLAGS),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "developer-mode-switch",
    ),
    # Persona switches (HIGH)
    (
        re.compile(
            r"you\s+are\s+now\s+(?:dan|jailbreak|unrestricted|unfiltered|developer)\b",
            _FLAGS,
        ),
        ReasonCode.PERSONA_SWITCH,
        Severity.HIGH,
        "you-are-now-jailbreak-persona",
    ),
    (
        re.compile(
            r"you\s+are\s+now\s+(a\s+)?(?!an?\s+ai|a\s+language)([\w\s]+bot|[\w\s]+ai|[\w\s]+assistant)",
            _FLAGS,
        ),
        ReasonCode.PERSONA_SWITCH,
        Severity.HIGH,
        "you-are-now-persona",
    ),
    (
        re.compile(r"act\s+as\s+(a\s+)?(?:dan|jailbreak|unrestricted|unfiltered)", _FLAGS),
        ReasonCode.PERSONA_SWITCH,
        Severity.HIGH,
        "act-as-jailbreak",
    ),
    (
        re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(?:dan|jailbreak|unrestricted)", _FLAGS),
        ReasonCode.PERSONA_SWITCH,
        Severity.HIGH,
        "pretend-jailbreak",
    ),
    # System probes (MEDIUM)
    (
        re.compile(
            r"(print|show|display|reveal|output)\s+(me\s+)?(your\s+)?(system\s+prompt|instructions|prompt)",
            _FLAGS,
        ),
        ReasonCode.SYSTEM_PROBE,
        Severity.MEDIUM,
        "show-system-prompt",
    ),
    (
        re.compile(
            r"what\s+(are\s+your|is\s+your)\s+(instructions?|system\s+prompt|rules?)",
            _FLAGS,
        ),
        ReasonCode.SYSTEM_PROBE,
        Severity.MEDIUM,
        "what-are-your-instructions",
    ),
    # Encoded payloads (HIGH)
    (
        re.compile(r"base64[:\s]+[A-Za-z0-9+/]{20,}={0,2}", _FLAGS),
        ReasonCode.ENCODED_PAYLOAD,
        Severity.HIGH,
        "base64-prefixed-blob",
    ),
    (
        re.compile(r"(?:decode|eval|exec)\s*\(['\"]", _FLAGS),
        ReasonCode.ENCODED_PAYLOAD,
        Severity.HIGH,
        "decode-eval-exec-call",
    ),
]

# Cyrillic homoglyphs that NFKC does not fold to Latin. Applied after NFKC so
# regex matching sees the Latin form. Coverage is deliberately narrow — common
# letters reused in jailbreak payloads.
_CONFUSABLES: dict[str, str] = {
    "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "х": "x", "і": "i", "є": "e",
    "у": "y", "ү": "y",
    "А": "A", "В": "B", "Е": "E", "К": "K",
    "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "Х": "X", "Ј": "J",
    "Ѕ": "S",
}

IMPERATIVE_VERBS: frozenset[str] = frozenset({
    "ignore", "forget", "disregard", "override", "bypass",
    "pretend", "act", "roleplay", "simulate", "imagine",
    "assume", "suppose", "consider", "treat", "behave",
})

_DENSITY_THRESHOLD = 0.15
_DENSITY_MIN_WORDS = 8

# Translation pre-processing budget, in seconds. The translated copy is used
# for pattern matching only; the original input is always forwarded untouched.
# 1.0s covers steady-state translation (~0.4s with several models resident);
# cold ~1.5s model loads are avoided by warming up at proxy startup. Override
# per deployment with the LLMGUARD_TRANSLATE_TIMEOUT env var.
_DEFAULT_TRANSLATE_TIMEOUT = 1.0

_BASE64_CANDIDATE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_WORD = re.compile(r"\b[\w']+\b")

# Common misspellings of attack keywords. Translation models pass typos
# through verbatim ("ignroe" stays "ignroe"), so the English regexes never
# match. These corrections are applied per-word before pattern matching;
# coverage is deliberately narrow — only typos of override/persona verbs.
_TYPO_CORRECTIONS: dict[str, str] = {
    "ignroe": "ignore",
    "isntructions": "instructions",
    "previuos": "previous",
    "disreguard": "disregard",
    "froget": "forget",
}

_TYPO_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _TYPO_CORRECTIONS) + r")\b",
    re.IGNORECASE,
)


def _correct_typos(text: str) -> str:
    """Replace known attack-keyword typos with their correct spelling."""
    return _TYPO_RE.sub(lambda m: _TYPO_CORRECTIONS[m.group(0).lower()], text)


def _normalise(content: str) -> str:
    nfkc = unicodedata.normalize("NFKC", content)
    return "".join(_CONFUSABLES.get(ch, ch) for ch in nfkc)


def _translation_suffix(detected_lang: str | None, timed_out: bool) -> str:
    """Annotation appended to a blocked result's detail line."""
    suffix = ""
    if detected_lang is not None:
        suffix += f" (translated from: {detected_lang})"
    if timed_out:
        suffix += " (TRANSLATION_TIMEOUT)"
    return suffix


def _scan_text(text: str) -> GuardResult | None:
    """Run every detector against one piece of text.

    Returns a blocking GuardResult on the first hit, or None when the text is
    clean. Typo correction is applied up front so misspelled attack keywords
    ("ignroe all previous instructions") still match the English patterns.
    The caller runs this on both the translated copy and the original input.
    """
    text = _correct_typos(text)

    for pattern, reason, severity, desc in PATTERNS:
        match = pattern.search(text)
        if match:
            return GuardResult(
                passed=False,
                reason_code=reason,
                severity=severity,
                detail=f"Matched pattern: {desc}",
                matched_pattern=match.group(0),
            )

    decoded_hit = _scan_base64_payloads(text)
    if decoded_hit is not None:
        return decoded_hit

    return _scan_density(text)


class InputGuard(Guard):
    async def scan(self, content: str) -> GuardResult:
        normalised = _normalise(content)

        # Translate non-English input to English so the deterministic patterns
        # below can match it. The translated copy is used for matching only;
        # the proxy still forwards the original input to the LLM. Fail open:
        # on timeout or any translation error, fall back to the original text.
        timeout = float(
            os.environ.get("LLMGUARD_TRANSLATE_TIMEOUT", _DEFAULT_TRANSLATE_TIMEOUT)
        )
        translation_timed_out = False
        try:
            english_content, detected_lang = await asyncio.wait_for(
                to_english(normalised), timeout=timeout
            )
        except asyncio.TimeoutError:
            english_content = normalised
            detected_lang = None
            translation_timed_out = True

        # Scan the translated copy *and* the original: translation can fail
        # open, be skipped on low detection confidence, or drop a pattern in
        # the process, yet the original may still carry a detectable payload.
        # Either hit blocks the request.
        suffix = _translation_suffix(detected_lang, translation_timed_out)
        candidates = [english_content]
        if normalised != english_content:
            candidates.append(normalised)
        for candidate in candidates:
            hit = _scan_text(candidate)
            if hit is not None:
                hit.detail += suffix
                return hit

        return GuardResult(
            passed=True,
            reason_code=ReasonCode.CLEAN,
            severity=Severity.LOW,
            detail="No threats detected",
        )


def _scan_base64_payloads(content: str) -> GuardResult | None:
    for match in _BASE64_CANDIDATE.finditer(content):
        candidate = match.group(0)
        # Base64 length must be a multiple of 4 to decode cleanly.
        if len(candidate) % 4 != 0:
            continue
        try:
            decoded = base64.b64decode(candidate, validate=True).decode("utf-8", errors="ignore")
        except (binascii.Error, ValueError):
            continue
        lowered = decoded.lower()
        if "ignore" in lowered or "instructions" in lowered:
            return GuardResult(
                passed=False,
                reason_code=ReasonCode.ENCODED_PAYLOAD,
                severity=Severity.HIGH,
                detail="Base64 payload decodes to injection-like content",
                matched_pattern=candidate,
            )
    return None


def _scan_density(content: str) -> GuardResult | None:
    words = _WORD.findall(content)
    word_count = len(words)
    if word_count <= _DENSITY_MIN_WORDS:
        return None
    imperative_count = sum(1 for w in words if w.lower() in IMPERATIVE_VERBS)
    density = imperative_count / word_count
    if density > _DENSITY_THRESHOLD:
        return GuardResult(
            passed=False,
            reason_code=ReasonCode.HIGH_DENSITY,
            severity=Severity.MEDIUM,
            detail=f"Instruction density {density:.1%} exceeds threshold",
        )
    return None
