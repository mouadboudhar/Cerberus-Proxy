import asyncio
import base64
import binascii
import difflib
import os
import re
import unicodedata

from cerberus_proxy.guards.base import (
    DEFAULT_GUARD_CONFIG,
    Guard,
    GuardConfig,
    GuardResult,
    ReasonCode,
    Severity,
)
from cerberus_proxy.guards.translator import to_english

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
            r"you\s+are\s+now\s+(?:a\s+)?(?:dan|jailbreak|unrestricted|unfiltered|developer|persona)\b",
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

# Multilingual patterns adapted from prompt-armor/prompt-armor
# (Apache 2.0) — https://github.com/prompt-armor/prompt-armor
# Rule IDs: ML-DE-001, ML-DE-003, ML-DE-004,
#           ML-ES-001, ML-ES-003,
#           ML-FR-001, ML-FR-003 (extended to also catch the formal
#                                "vous êtes" alongside informal "tu es"),
#           ML-PT-001 (third group made required to avoid the
#                     "ignore a/as ..." English false-positive).
#
# These run against the homoglyph-folded original text as a parallel
# detection path to the translation-based scanning. They catch non-English
# attacks without depending on argostranslate succeeding.
MULTILINGUAL_PATTERNS: list[tuple[re.Pattern[str], ReasonCode, Severity, str, str]] = [
    # German
    (
        re.compile(
            r"(vergiss|ignorier[e]?|missacht[e]?|höre?\s+nicht\s+auf)\s+"
            r"(alles?|alle[ns]?|sämtliche)\s*"
            r"(bisherige[n]?|vorherige[n]?|obige[n]?|davor|zuvor\s+gesagte)?",
            _FLAGS,
        ),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "de",
        "forget-previous-instructions",
    ),
    (
        re.compile(
            r"du\s+bist\s+(jetzt|nun|ab\s+sofort)\s+(ein[e]?|der|die|das)",
            _FLAGS,
        ),
        ReasonCode.PERSONA_SWITCH,
        Severity.HIGH,
        "de",
        "you-are-now-persona",
    ),
    (
        re.compile(
            r"(zeig|gib|nenn|drucke?)\s+(mir\s+)?(den|die|das|deinen?)\s*"
            r"(System.?prompt|Anweisungen|Instruktionen)",
            _FLAGS,
        ),
        ReasonCode.SYSTEM_PROBE,
        Severity.MEDIUM,
        "de",
        "show-system-prompt",
    ),
    # Spanish
    (
        re.compile(
            r"(olvida|ignora|desecha|descarta)\s+"
            r"(todo|todas?|los?|las?)\s*"
            r"(anterior|previo|instrucciones?)?",
            _FLAGS,
        ),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "es",
        "forget-previous-instructions",
    ),
    (
        re.compile(r"ahora\s+eres\s+(un[a]?|el|la|mi)", _FLAGS),
        ReasonCode.PERSONA_SWITCH,
        Severity.HIGH,
        "es",
        "you-are-now-persona",
    ),
    # French
    (
        re.compile(
            r"(oublie[zs]?|ignore[zs]?|ne\s+tien[s]?\s+pas\s+compte)\s+"
            r"(de\s+)?(tout|toutes?|les?)\s*"
            r"(instructions?|consignes?|précédent)?",
            _FLAGS,
        ),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "fr",
        "forget-previous-instructions",
    ),
    (
        re.compile(
            r"(tu\s+es|vous\s+êtes)\s+(maintenant|désormais)\s+(un[e]?|le|la)",
            _FLAGS,
        ),
        ReasonCode.PERSONA_SWITCH,
        Severity.HIGH,
        "fr",
        "you-are-now-persona",
    ),
    # Portuguese — modified from prompt-armor in two ways: third group is
    # required (not optional) so the EN/PT homograph "ignore" cannot fire on
    # bare "ignore a request"; and a second article slot is allowed so the
    # natural "todas as instruções" article-noun chain matches end-to-end.
    (
        re.compile(
            r"(esqueça|ignore|descarte|desconsidere)\s+"
            r"(tudo|todas?|os?|as?)"
            r"(?:\s+(?:as?|os?))?\s+"
            r"(anterior|prévi[oa]|instruções?)",
            _FLAGS,
        ),
        ReasonCode.OVERRIDE_ATTEMPT,
        Severity.CRITICAL,
        "pt",
        "forget-previous-instructions",
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
# per deployment with the CERBERUS_TRANSLATE_TIMEOUT env var.
_DEFAULT_TRANSLATE_TIMEOUT = 1.0

_BASE64_CANDIDATE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_WORD = re.compile(r"\b[\w']+\b")

# Edit-distance target vocabulary for typo normalisation. Translation models
# pass typos through verbatim ("ingore" stays "ingore"), so the English
# patterns never match. normalize_typos() rewrites any word within fuzzy
# distance of one of these tokens, so misspelled attacks ("ingore all
# prveious instructons") collapse onto the canonical form before scanning.
ATTACK_KEYWORDS: list[str] = [
    "ignore", "disregard", "forget", "override", "bypass",
    "pretend", "persona", "instructions", "previous",
    "system", "prompt", "restrictions", "unrestricted",
    "jailbreak", "dan", "roleplay", "simulate",
]

_TYPO_MIN_LEN = 4
_TYPO_CUTOFF = 0.75


def normalize_typos(text: str) -> str:
    """Rewrite words within fuzzy distance of an attack keyword to that keyword.

    Words shorter than 4 characters are kept verbatim — at that length almost
    everything fuzzy-matches "dan" — and a 0.75 SequenceMatcher cutoff keeps
    benign English ("forgot" near "forget") from collapsing onto the wrong
    canonical form unless the variant is a near-anagram (one transposition or
    one missing character).
    """
    out: list[str] = []
    for word in text.split():
        if len(word) < _TYPO_MIN_LEN:
            out.append(word)
            continue
        matches = difflib.get_close_matches(
            word.lower(), ATTACK_KEYWORDS, n=1, cutoff=_TYPO_CUTOFF
        )
        out.append(matches[0] if matches else word)
    return " ".join(out)


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


def _scan_text(
    text: str, config: GuardConfig = DEFAULT_GUARD_CONFIG
) -> GuardResult | None:
    """Run every (enabled) detector against one piece of text.

    Returns a blocking GuardResult on the first hit, or None when the text is
    clean. The caller is responsible for any pre-processing (translation,
    NFKC, typo normalisation) and runs this on each candidate variant.

    Rules are keyed by ReasonCode name: any pattern whose category is in
    ``config.disabled_rules`` is skipped silently, as are the base64
    (ENCODED_PAYLOAD) and instruction-density (HIGH_DENSITY) heuristics.
    """
    disabled = config.disabled_rules
    for pattern, reason, severity, desc in PATTERNS:
        if reason.name in disabled:
            continue
        match = pattern.search(text)
        if match:
            return GuardResult(
                passed=False,
                reason_code=reason,
                severity=severity,
                detail=f"Matched pattern: {desc}",
                matched_pattern=match.group(0),
            )

    if ReasonCode.ENCODED_PAYLOAD.name not in disabled:
        decoded_hit = _scan_base64_payloads(text)
        if decoded_hit is not None:
            return decoded_hit

    if ReasonCode.HIGH_DENSITY.name not in disabled:
        return _scan_density(text)

    return None


def _scan_multilingual(text: str) -> GuardResult | None:
    """Scan for non-English injection patterns against the original text.

    Runs as a parallel detection path to translation: even when argostranslate
    fails, times out, or strips the attacker's verb, these patterns still fire
    on the raw German/Spanish/French/Portuguese input.
    """
    for pattern, reason, severity, lang, desc in MULTILINGUAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return GuardResult(
                passed=False,
                reason_code=reason,
                severity=severity,
                detail=f"Multilingual pattern ({lang}): {desc}",
                matched_pattern=f"multilingual-{lang}-{desc}",
            )
    return None


class InputGuard(Guard):
    async def scan(
        self, content: str, config: GuardConfig = DEFAULT_GUARD_CONFIG
    ) -> GuardResult:
        # Custom blocked phrases run first, before any normalisation or pattern
        # matching: an exact (case-insensitive) substring match blocks outright.
        if config.custom_blocked_phrases:
            lowered = content.lower()
            for phrase in config.custom_blocked_phrases:
                if phrase.lower() in lowered:
                    return GuardResult(
                        passed=False,
                        reason_code=ReasonCode.OVERRIDE_ATTEMPT,
                        severity=Severity.HIGH,
                        detail="Custom blocked phrase detected",
                        matched_pattern="custom-phrase",
                    )

        normalised = _normalise(content)

        if "MULTILINGUAL" not in config.disabled_rules:
            ml_hit = _scan_multilingual(normalised)
            if ml_hit is not None:
                return ml_hit

        typo_normalised = normalize_typos(normalised)

        # Translate non-English input to English so the deterministic patterns
        # below can match it. The translated copy is used for matching only;
        # the proxy still forwards the original input to the LLM. Fail open:
        # on timeout or any translation error, fall back to the original text.
        timeout = float(
            os.environ.get("CERBERUS_TRANSLATE_TIMEOUT", _DEFAULT_TRANSLATE_TIMEOUT)
        )
        translation_timed_out = False
        # Only pass the language allowlist when the endpoint set one, so the
        # default path keeps the original single-argument to_english() call.
        translate = (
            to_english(normalised, config.active_languages)
            if config.active_languages
            else to_english(normalised)
        )
        try:
            english_content, detected_lang = await asyncio.wait_for(
                translate, timeout=timeout
            )
        except asyncio.TimeoutError:
            english_content = normalised
            detected_lang = None
            translation_timed_out = True

        # Scan up to four variants: the translated copy (covers non-English
        # payloads), the homoglyph-folded original (covers Latin attacks
        # regardless of translation), and the typo-normalised forms of both
        # (covers misspelled attacks — including ones where translation passes
        # the typo through verbatim, e.g. "ignroe" surviving fr->en). Any hit
        # blocks. Dedup so well-spelled English inputs collapse to one pass.
        suffix = _translation_suffix(detected_lang, translation_timed_out)
        typo_normalised_english = normalize_typos(english_content)
        seen: set[str] = set()
        candidates: list[str] = []
        for candidate in (
            english_content,
            normalised,
            typo_normalised,
            typo_normalised_english,
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
        for candidate in candidates:
            hit = _scan_text(candidate, config)
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
