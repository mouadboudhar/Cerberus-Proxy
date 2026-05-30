from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RetrievedDocument:
    content: str
    source: str
    score: float


class KnowledgeBaseRetriever(ABC):
    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedDocument]:
        ...
