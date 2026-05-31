from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from functools import lru_cache

import argostranslate.package
import argostranslate.translate
from lingua import Language, LanguageDetectorBuilder

logger = logging.getLogger(__name__)

# Languages the Input Guard understands. Detection is restricted to this set so
# the detector stays fast and predictable; anything outside it is treated as
# undetectable and left untranslated.
SUPPORTED_LANGUAGES = [
    Language.ENGLISH,
    Language.FRENCH,
    Language.SPANISH,
    Language.ARABIC,
    Language.GERMAN,
    Language.PORTUGUESE,
    Language.ITALIAN,
    Language.DUTCH,
    Language.RUSSIAN,
    Language.CHINESE,
    Language.JAPANESE,
    Language.TURKISH,
]

# Module-level singleton. Low-accuracy mode keeps per-request detection cheap,
# which matters under the Input Guard's sub-second translation budget.
_detector = (
    LanguageDetectorBuilder.from_languages(*SUPPORTED_LANGUAGES)
    .with_low_accuracy_mode()
    .build()
)

# Translation is skipped when language detection is less certain than this.
# 0.5 is lingua's standard production threshold: high enough to reject noise,
# low enough that long mixed-language input and typo-laden prompts — which
# legitimately score lower — still get translated and scanned rather than
# slipping through untranslated.
_MIN_CONFIDENCE = 0.5

# When English wins detection but a non-English language scores at least this
# fraction of the winner, English is treated as a misdetection — typos and
# mixed wording depress the true language's score while inflating English — so
# translation runs from that runner-up rather than being skipped.
_RUNNER_UP_RATIO = 0.7

# argostranslate models occasionally emit degenerate output: a token repeated
# hundreds of times, or "@@" subword-merge artefacts. Such output is discarded
# and the guard matches the original text instead.
_CORRUPTION_RE = re.compile(r"^(\w+@@\s*){3,}")
_MAX_WORD_REPEATS = 5
_MAX_LENGTH_RATIO = 3


def _looks_corrupted(original: str, translated: str) -> bool:
    """Return True when ``translated`` shows signs of a degenerate model run."""
    if len(translated) > _MAX_LENGTH_RATIO * len(original):
        return True
    if _CORRUPTION_RE.match(translated):
        return True
    words = translated.split()
    if words and max(Counter(words).values()) > _MAX_WORD_REPEATS:
        return True
    return False


@lru_cache(maxsize=1000)
def _cached_translate(text: str, from_code: str) -> str:
    """Translate ``text`` into English, returning it unchanged on any failure.

    Fail open: if the language model is missing, argostranslate raises, or the
    output fails the quality check, the caller runs its English patterns
    against the original text rather than blocking. Results (including
    fail-open passthroughs) are cached.
    """
    try:
        translated = argostranslate.translate.translate(text, from_code, "en")
    except Exception:
        return text
    if not translated or _looks_corrupted(text, translated):
        logger.warning("Translation quality check failed for %s", from_code)
        return text
    return translated


async def to_english(
    text: str, active_languages: list[str] | None = None
) -> tuple[str, str | None]:
    """Return ``text`` as English plus the detected source language code.

    The second element is the ISO 639-1 code the text was translated from, or
    ``None`` when the input is English, undetectable, detected too weakly to
    risk a mistranslation, or translated to no usable change. When English
    wins detection but a non-English language is a close runner-up, the input
    is treated as that runner-up (see ``_RUNNER_UP_RATIO``): typo-laden and
    mixed-language prompts routinely misdetect as English. The translation
    runs in a worker thread so the event loop stays responsive and an
    ``asyncio.wait_for`` timeout around this coroutine can actually fire.

    ``active_languages`` (Stage 14b, per-endpoint): when a non-empty list of
    ISO 639-1 codes is given, only those source languages are translated;
    input detected as any other language is left untranslated and its
    patterns are matched on the original text.
    """
    confidences = _detector.compute_language_confidence_values(text)
    if not confidences:
        return (text, None)

    best = confidences[0]
    if best.language == Language.ENGLISH:
        # Trust English only when no non-English language comes close; a
        # strong runner-up means English is likely a misdetection of a
        # typo'd or mixed-language prompt, which must still be translated.
        runner_up = next(
            (c for c in confidences[1:] if c.language != Language.ENGLISH), None
        )
        if runner_up is None or runner_up.value < _RUNNER_UP_RATIO * best.value:
            return (text, None)
        logger.warning(
            "English (%.2f) treated as misdetected %s (%.2f); translating",
            best.value,
            runner_up.language.name,
            runner_up.value,
        )
        detected = runner_up.language
    else:
        detected = best.language
        # Below the threshold the guess is too shaky to risk a
        # mistranslation, so the original text is matched instead.
        if best.value < _MIN_CONFIDENCE:
            logger.warning(
                "Language confidence %.2f for %s below %.2f; skipping translation",
                best.value,
                detected.name,
                _MIN_CONFIDENCE,
            )
            return (text, None)

    from_code = detected.iso_code_639_1.name.lower()

    # Endpoint-scoped language allowlist: skip translation for inactive
    # languages and match patterns against the original text instead.
    if active_languages and from_code not in active_languages:
        logger.warning(
            "Language %s not in active set %s; skipping translation",
            from_code,
            active_languages,
        )
        return (text, None)

    translated = await asyncio.to_thread(_cached_translate, text, from_code)
    if not translated or translated == text:
        return (text, None)
    return (translated, from_code)


def ensure_language_models_installed(from_code: str) -> None:
    """Install the ``from_code`` -> ``en`` argostranslate model if missing.

    Safe to call repeatedly: once a pair is installed this returns early. The
    download happens once per language pair, then the model is cached on disk.
    """
    if from_code == "en":
        return

    installed = argostranslate.package.get_installed_packages()
    if any(p.from_code == from_code and p.to_code == "en" for p in installed):
        return

    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    package = next(
        (p for p in available if p.from_code == from_code and p.to_code == "en"),
        None,
    )
    if package is None:
        return
    argostranslate.package.install_from_path(package.download())


def warm_up() -> None:
    """Load every installed ``<lang> -> en`` model into memory.

    Call once at process start (the proxy does this in its lifespan hook).
    A cold argostranslate model load takes ~1.5s — long enough to lose the
    Input Guard's per-request translation timeout and fail open, letting a
    non-English injection through unscanned. Warming here moves that cost to
    startup so every request hits an already-loaded model (~55ms).
    """
    for package in argostranslate.package.get_installed_packages():
        if package.to_code != "en" or package.from_code == "en":
            continue
        try:
            argostranslate.translate.translate("warm up", package.from_code, "en")
        except Exception:
            logger.warning("Warm-up failed for %s -> en", package.from_code)
    logger.info("Translation models warmed up")
