"""Guard configuration API (Stage 12, Component 5).

GET returns the global guard config assembled from env vars; PATCH persists
changes to the live process env and to .env.

NOTE: only CERBERUS_OUTPUT_GUARD_ACTION and CERBERUS_TRANSLATE_TIMEOUT are
actually consumed by the running guards today. The enabled/input-action
toggles are read and persisted here so the dashboard can manage them, but the
guards do not yet honour them (that requires changes to the guard modules).
"""

import os
from enum import Enum

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cerberus_proxy.api.auth import _env_file_path, _update_env_file
from cerberus_proxy.audit.api import verify_dashboard_token
from cerberus_proxy.guards.input_guard import PATTERNS as _INPUT_PATTERNS
from cerberus_proxy.guards.output_guard import HIGH_ENTROPY_NAME
from cerberus_proxy.guards.output_guard import PATTERNS as _OUTPUT_PATTERNS
from cerberus_proxy.guards.translator import SUPPORTED_LANGUAGES

router = APIRouter(
    prefix="/api/guards",
    dependencies=[Depends(verify_dashboard_token)],
)

_INPUT_ENABLED = "CERBERUS_INPUT_GUARD_ENABLED"
_INPUT_ACTION = "CERBERUS_INPUT_GUARD_ACTION"
_OUTPUT_ENABLED = "CERBERUS_OUTPUT_GUARD_ENABLED"
_OUTPUT_ACTION = "CERBERUS_OUTPUT_GUARD_ACTION"
_TRANSLATION_ENABLED = "CERBERUS_TRANSLATION_ENABLED"
_TRANSLATE_TIMEOUT = "CERBERUS_TRANSLATE_TIMEOUT"


class OutputAction(str, Enum):
    redact = "redact"
    block = "block"
    log_only = "log_only"


class InputGuardPatch(BaseModel):
    enabled: bool | None = None
    output_action: str | None = None


class OutputGuardPatch(BaseModel):
    enabled: bool | None = None
    action: OutputAction | None = None


class TranslationPatch(BaseModel):
    enabled: bool | None = None
    timeout_seconds: float | None = None


class GuardConfigPatch(BaseModel):
    input_guard: InputGuardPatch | None = None
    output_guard: OutputGuardPatch | None = None
    translation: TranslationPatch | None = None


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _input_available_rules() -> list[str]:
    # Derived from the Input Guard's ReasonCode categories, plus the two
    # heuristic toggles that aren't part of the regex PATTERNS table.
    rules: list[str] = []
    for _pattern, reason, _severity, _desc in _INPUT_PATTERNS:
        if reason.name not in rules:
            rules.append(reason.name)
    for extra in ("HIGH_DENSITY", "MULTILINGUAL"):
        if extra not in rules:
            rules.append(extra)
    return rules


def _output_available_rules() -> list[str]:
    # Every Output Guard pattern name, plus the high-entropy catch-all.
    rules: list[str] = []
    for pdef in _OUTPUT_PATTERNS:
        if pdef.name not in rules:
            rules.append(pdef.name)
    if HIGH_ENTROPY_NAME not in rules:
        rules.append(HIGH_ENTROPY_NAME)
    return rules


def _supported_languages() -> list[str]:
    # Single source of truth: derive ISO-639-1 codes from the translator's list.
    codes = []
    for lang in SUPPORTED_LANGUAGES:
        try:
            codes.append(lang.iso_code_639_1.name.lower())
        except Exception:  # noqa: BLE001
            codes.append(lang.name.lower())
    return codes


def _current_config() -> dict:
    return {
        "input_guard": {
            "enabled": _bool_env(_INPUT_ENABLED, True),
            "output_action": os.getenv(_INPUT_ACTION, "block"),
            "available_rules": _input_available_rules(),
        },
        "output_guard": {
            "enabled": _bool_env(_OUTPUT_ENABLED, True),
            "action": os.getenv(_OUTPUT_ACTION, "redact").lower(),
            "available_rules": _output_available_rules(),
        },
        "translation": {
            "enabled": _bool_env(_TRANSLATION_ENABLED, True),
            "supported_languages": _supported_languages(),
            "timeout_seconds": float(os.getenv(_TRANSLATE_TIMEOUT, "1.0")),
        },
    }


@router.get(
    "/config",
    summary="Get global guard configuration",
    description=(
        "Return the deployment-wide guard configuration assembled from "
        "environment variables: input/output guard enabled flags and actions, "
        "translation settings and timeout, plus the lists of available input "
        "and output rule names and supported languages the dashboard uses to "
        "build per-endpoint configuration UIs. Requires the dashboard token."
    ),
)
async def get_guard_config() -> dict:
    return _current_config()


@router.patch(
    "/config",
    summary="Update global guard configuration",
    description=(
        "Patch the deployment-wide guard settings. Only the fields provided "
        "are changed; each is applied to the live process environment "
        "immediately and best-effort persisted to the .env file. Note that "
        "today the running guards consume only the output-guard action and "
        "translation timeout; the other flags are stored for the dashboard. "
        "Returns the full effective configuration. Requires the dashboard token."
    ),
)
async def update_guard_config(body: GuardConfigPatch) -> dict:
    updates: dict[str, str] = {}
    if body.input_guard is not None:
        if body.input_guard.enabled is not None:
            updates[_INPUT_ENABLED] = str(body.input_guard.enabled).lower()
        if body.input_guard.output_action is not None:
            updates[_INPUT_ACTION] = body.input_guard.output_action
    if body.output_guard is not None:
        if body.output_guard.enabled is not None:
            updates[_OUTPUT_ENABLED] = str(body.output_guard.enabled).lower()
        if body.output_guard.action is not None:
            updates[_OUTPUT_ACTION] = body.output_guard.action.value
    if body.translation is not None:
        if body.translation.enabled is not None:
            updates[_TRANSLATION_ENABLED] = str(body.translation.enabled).lower()
        if body.translation.timeout_seconds is not None:
            updates[_TRANSLATE_TIMEOUT] = str(body.translation.timeout_seconds)

    path = _env_file_path()
    for key, value in updates.items():
        os.environ[key] = value  # live process env (effective immediately)
        _update_env_file(path, key, value)  # best-effort persistence
    return _current_config()
