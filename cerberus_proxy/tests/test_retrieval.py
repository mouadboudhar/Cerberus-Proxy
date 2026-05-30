import json
import sys
import types

import httpx
import pytest
import respx

from cerberus_proxy.config.repository import SQLiteEndpointRepository
from cerberus_proxy.retrieval.base import RetrievedDocument
from cerberus_proxy.retrieval.chroma import ChromaRetriever
from cerberus_proxy.retrieval.factory import get_retriever
from cerberus_proxy.retrieval.injector import inject_context

UPSTREAM_URL = "https://api.openai.com/v1/chat/completions"

FAKE_COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
}


def _install_fake_chromadb(monkeypatch, *, query_result=None, connect_error=None):
    """Inject a stand-in `chromadb` module so ChromaRetriever runs without a server."""
    fake = types.ModuleType("chromadb")

    class FakeCollection:
        def query(self, query_texts, n_results):
            return query_result

    class FakeClient:
        def get_or_create_collection(self, name):
            return FakeCollection()

    def HttpClient(host, port, ssl=False):
        if connect_error is not None:
            raise connect_error
        return FakeClient()

    fake.HttpClient = HttpClient
    monkeypatch.setitem(sys.modules, "chromadb", fake)


async def _make_endpoint(session_factory, **kwargs) -> int:
    async with session_factory() as session:
        repo = SQLiteEndpointRepository(session)
        endpoint = await repo.create(
            name=kwargs.get("name", "kb-endpoint"),
            provider=kwargs.get("provider", "openai"),
            upstream_url=kwargs.get("upstream_url", "https://api.openai.com"),
            kb_type=kwargs.get("kb_type"),
            kb_url=kwargs.get("kb_url"),
            kb_collection=kwargs.get("kb_collection"),
        )
        await session.commit()
        return endpoint.id


# ── RetrievedDocument ───────────────────────────────────────────────────────


def test_retrieved_document_fields():
    doc = RetrievedDocument(content="text", source="f.pdf", score=0.9)
    assert doc.content == "text"
    assert doc.source == "f.pdf"
    assert doc.score == 0.9


# ── ChromaRetriever ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chroma_retriever_returns_documents(monkeypatch):
    _install_fake_chromadb(
        monkeypatch,
        query_result={
            "documents": [["policy text", "security text"]],
            "metadatas": [[{"source": "policy.pdf"}, {"source": "security.pdf"}]],
            "distances": [[0.12, 0.34]],
        },
    )
    retriever = ChromaRetriever("http://localhost:8001", "docs")
    docs = await retriever.retrieve("question", top_k=2)

    assert isinstance(docs, list)
    assert all(isinstance(d, RetrievedDocument) for d in docs)
    assert [d.content for d in docs] == ["policy text", "security text"]
    assert docs[0].source == "policy.pdf"
    assert docs[0].score == 0.12


@pytest.mark.asyncio
async def test_chroma_retriever_fails_gracefully(monkeypatch):
    _install_fake_chromadb(monkeypatch, connect_error=ConnectionError("kb down"))
    retriever = ChromaRetriever("http://localhost:8001", "docs")
    docs = await retriever.retrieve("question", top_k=4)
    assert docs == []


# ── Factory ─────────────────────────────────────────────────────────────────


def test_factory_returns_chroma_for_chroma_type():
    retriever = get_retriever("chroma", "http://localhost:8001", "test")
    assert isinstance(retriever, ChromaRetriever)


def test_factory_returns_none_for_no_type():
    assert get_retriever(None, None, None) is None


def test_factory_returns_none_for_unknown_type():
    assert get_retriever("pinecone", "http://localhost:8001", "test") is None


# ── Context injector ────────────────────────────────────────────────────────


def test_inject_context_no_system_message():
    messages = [{"role": "user", "content": "hello"}]
    docs = [RetrievedDocument("policy", "policy.pdf", 0.9)]
    result = inject_context(messages, docs)
    assert result[0]["role"] == "system"
    assert "policy" in result[0]["content"]
    assert result[1]["role"] == "user"


def test_inject_context_existing_system_message():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hello"},
    ]
    docs = [RetrievedDocument("policy", "policy.pdf", 0.9)]
    result = inject_context(messages, docs)
    assert len(result) == 2
    assert "policy" in result[0]["content"]
    assert "You are helpful." in result[0]["content"]


def test_inject_context_empty_docs():
    messages = [{"role": "user", "content": "hello"}]
    assert inject_context(messages, []) == messages


def test_inject_context_no_mutation():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hello"},
    ]
    original = [dict(m) for m in messages]
    docs = [RetrievedDocument("policy", "policy.pdf", 0.9)]
    inject_context(messages, docs)
    # Neither the list length nor any dict content changed.
    assert messages == original


# ── Proxy wiring ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_proxy_injects_context_for_kb_endpoint(
    session_factory, client, create_key, monkeypatch
):
    endpoint_id = await _make_endpoint(
        session_factory,
        kb_type="chroma",
        kb_url="http://chroma:8000",
        kb_collection="docs",
    )

    async def fake_retrieve(self, query, top_k=4):
        return [
            RetrievedDocument("Data retention is 90 days.", "policy.pdf", 0.9),
            RetrievedDocument("Encryption at rest is on.", "security.pdf", 0.8),
        ]

    monkeypatch.setattr(ChromaRetriever, "retrieve", fake_retrieve)

    api_key, _ = await create_key("kb-test")
    route = respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is our retention policy?"}],
        },
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 200
    assert route.called

    forwarded = json.loads(route.calls.last.request.content)
    system_msgs = [m for m in forwarded["messages"] if m["role"] == "system"]
    assert system_msgs, "expected an injected system message"
    assert "Data retention is 90 days." in system_msgs[0]["content"]


@pytest.mark.asyncio
@respx.mock
async def test_proxy_skips_retrieval_for_plain_endpoint(
    session_factory, client, create_key, monkeypatch
):
    endpoint_id = await _make_endpoint(session_factory, kb_type=None)

    async def fail_if_called(self, query, top_k=4):  # pragma: no cover
        raise AssertionError("retrieval should not run for a plain endpoint")

    monkeypatch.setattr(ChromaRetriever, "retrieve", fail_if_called)

    api_key, _ = await create_key("plain-test")
    route = respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        },
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 200

    forwarded = json.loads(route.calls.last.request.content)
    assert all(m["role"] != "system" for m in forwarded["messages"])


@pytest.mark.asyncio
@respx.mock
async def test_proxy_continues_on_retrieval_failure(
    session_factory, client, create_key, monkeypatch
):
    endpoint_id = await _make_endpoint(
        session_factory,
        kb_type="chroma",
        kb_url="http://chroma:8000",
        kb_collection="docs",
    )

    async def boom(self, query, top_k=4):
        raise RuntimeError("kb exploded")

    monkeypatch.setattr(ChromaRetriever, "retrieve", boom)

    api_key, _ = await create_key("kb-fail-test")
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=FAKE_COMPLETION)
    )
    response = await client.post(
        f"/v1/chat/completions/{endpoint_id}",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        },
        headers={"X-Cerberus-Key": api_key, "Authorization": "Bearer sk-x"},
    )
    assert response.status_code == 200
