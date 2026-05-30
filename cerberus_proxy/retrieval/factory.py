import logging

from cerberus_proxy.retrieval.base import KnowledgeBaseRetriever
from cerberus_proxy.retrieval.chroma import ChromaRetriever

logger = logging.getLogger("cerberus_proxy.retrieval.factory")


def get_retriever(
    kb_type: str | None,
    kb_url: str | None,
    kb_collection: str | None,
) -> KnowledgeBaseRetriever | None:
    if not kb_type or not kb_url:
        return None
    if kb_type == "chroma":
        return ChromaRetriever(kb_url, kb_collection or "default")
    logger.warning("Unknown kb_type '%s' — skipping", kb_type)
    return None
