from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AdapterConfig:
    upstream_url: str
    timeout_seconds: int = 30


class LLMAdapter(ABC):
    @abstractmethod
    async def forward(
        self,
        request_body: dict[str, Any],
        headers: dict[str, Any],
    ) -> dict[str, Any]:
        """Forward the incoming request to the upstream LLM and return its response body."""
