import asyncio
import logging
from urllib.parse import urlparse

from cerberus_proxy.retrieval.base import KnowledgeBaseRetriever, RetrievedDocument

logger = logging.getLogger("cerberus_proxy.retrieval.chroma")


class ChromaRetriever(KnowledgeBaseRetriever):
    def __init__(self, url: str, collection: str) -> None:
        self._url = url
        self._collection_name = collection
        # Connect lazily on first retrieve() so a slow/unreachable KB never
        # blocks proxy startup.
        self._collection = None

    def _connect_blocking(self):
        # chromadb's HttpClient is synchronous; this runs inside a worker thread.
        import chromadb

        parsed = urlparse(self._url)
        ssl = parsed.scheme == "https"
        host = parsed.hostname or self._url
        port = parsed.port or (443 if ssl else 80)
        client = chromadb.HttpClient(host=host, port=port, ssl=ssl)
        return client.get_or_create_collection(name=self._collection_name)

    def _query_blocking(self, query: str, top_k: int) -> list[RetrievedDocument]:
        if self._collection is None:
            self._collection = self._connect_blocking()
        result = self._collection.query(query_texts=[query], n_results=top_k)

        # chromadb returns parallel lists nested one level per query string.
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        docs: list[RetrievedDocument] = []
        for i, content in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
            score = distances[i] if i < len(distances) else 0.0
            docs.append(
                RetrievedDocument(
                    content=content,
                    source=meta.get("source", "unknown"),
                    score=score,
                )
            )
        return docs

    async def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedDocument]:
        try:
            # Offload the blocking connect + query to a worker thread so the
            # proxy event loop is never stalled by a slow KB.
            return await asyncio.to_thread(self._query_blocking, query, top_k)
        except Exception as e:  # noqa: BLE001
            logger.warning("ChromaDB retrieval failed: %s", e)
            # Never raise — the proxy must keep working if the KB is unreachable.
            self._collection = None
            return []
