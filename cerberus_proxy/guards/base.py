from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReasonCode(str, Enum):
    OVERRIDE_ATTEMPT = "OVERRIDE_ATTEMPT"
    PERSONA_SWITCH = "PERSONA_SWITCH"
    SYSTEM_PROBE = "SYSTEM_PROBE"
    ENCODED_PAYLOAD = "ENCODED_PAYLOAD"
    HIGH_DENSITY = "HIGH_DENSITY"
    PII_DETECTED = "PII_DETECTED"
    SECRET_DETECTED = "SECRET_DETECTED"
    CLEARANCE_DENIED = "CLEARANCE_DENIED"
    CLEAN = "CLEAN"


@dataclass
class GuardResult:
    passed: bool
    reason_code: ReasonCode
    severity: Severity
    detail: str
    matched_pattern: str | None = None


@dataclass
class GuardConfig:
    """Per-endpoint guard tuning. Empty lists mean default behaviour.

    ``disabled_rules`` holds rule identifiers for both guards: Input Guard
    ReasonCode names (e.g. "SYSTEM_PROBE", "MULTILINGUAL") and Output Guard
    pattern names (e.g. "PHONE_US"). The two name spaces don't overlap, so a
    single list drives both.
    """

    disabled_rules: list[str] = field(default_factory=list)
    custom_blocked_phrases: list[str] = field(default_factory=list)
    active_languages: list[str] = field(default_factory=list)


# Shared sentinel for "no customisation" — produces identical behaviour to the
# pre-Stage-14b guards. Never mutated by the guards, so sharing one instance is
# safe.
DEFAULT_GUARD_CONFIG = GuardConfig()


class Guard(ABC):
    @abstractmethod
    async def scan(self, content: str) -> GuardResult:
        """Scan content and return a GuardResult."""
