from abc import ABC, abstractmethod
from dataclasses import dataclass
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


class Guard(ABC):
    @abstractmethod
    async def scan(self, content: str) -> GuardResult:
        """Scan content and return a GuardResult."""
