#!/usr/bin/env python3
"""Retrieval-Augmented Generation (RAG) with Cerberus Proxy.

This example contrasts a *traditional* client-side RAG pipeline with the
Cerberus approach, where retrieval is configured once per endpoint in the
dashboard and the proxy injects context automatically.

Usage:
    python examples/rag_integration.py <cerberus_key> <provider_key> <endpoint_id>

Env overrides:
    CERBERUS_URL    base URL of the proxy (default: http://localhost:8000)
    CERBERUS_MODEL  model name sent in the request (default: gpt-4o-mini)

Prerequisite for the live call:
    The endpoint <endpoint_id> must have a knowledge base configured in the
    dashboard (kb_type=chroma, kb_url=..., kb_collection=...). Without it, the
    proxy simply forwards the query unchanged — no retrieval happens.
"""
from __future__ import annotations

import os
import sys

import httpx

# ─────────────────────────────────────────────────────────────────────────────
# BEFORE — Traditional client-side RAG (no security gateway)
# ─────────────────────────────────────────────────────────────────────────────
#
# The application owns the entire retrieval pipeline. It embeds the query,
# searches a vector store, formats the documents, stitches them into the prompt,
# and calls the LLM directly. Every app that talks to the model must reimplement
# this — and there is no central place to scan inputs, redact outputs, enforce
# rate limits, or audit what was retrieved.
#
#     docs = vectorstore.similarity_search(query, k=4)
#     context = format_docs(docs)
#     response = llm.invoke(prompt + context)
#
# The LLM credentials, the vector store, and the prompt assembly all live in the
# client. There is no guard between the user's query and the provider.


# ─────────────────────────────────────────────────────────────────────────────
# AFTER — Let Cerberus handle retrieval
# ─────────────────────────────────────────────────────────────────────────────
#
# Configure the knowledge base ONCE on the endpoint in the dashboard:
#     kb_type       = "chroma"
#     kb_url        = "http://chroma:8000"
#     kb_collection = "company-docs"
#     kb_top_k      = 4
#
# Then point the application at the per-endpoint URL and send a PLAIN query.
# Cerberus retrieves the relevant documents and injects them as context before
# forwarding upstream. The client needs ZERO retrieval code — no vector store,
# no embeddings, no prompt stitching. It only changes its base_url.
#
# As a bonus, every request still flows through the Input/Output guards, rate
# limiting, and the audit log — the same protections as any other Cerberus call.
def ask_with_cerberus_rag(
    base_url: str,
    cerberus_key: str,
    provider_key: str,
    endpoint_id: str,
    model: str,
    query: str,
) -> str:
    # Per-endpoint route — this is what triggers KB retrieval. The plain
    # /v1/chat/completions route (no endpoint id) never retrieves.
    url = f"{base_url}/v1/chat/completions/{endpoint_id}"

    headers = {
        "X-Cerberus-Key": cerberus_key,
        "Authorization": f"Bearer {provider_key}",
        "Content-Type": "application/json",
    }

    # Note: just the user's question. No documents, no context — Cerberus adds
    # those server-side based on the endpoint's knowledge-base configuration.
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2

    cerberus_key, provider_key, endpoint_id = sys.argv[1], sys.argv[2], sys.argv[3]
    base_url = os.environ.get("CERBERUS_URL", "http://localhost:8000").rstrip("/")
    model = os.environ.get("CERBERUS_MODEL", "gpt-4o-mini")

    query = "What is our company's data retention policy?"
    print(f"Query: {query}\n")

    reply = ask_with_cerberus_rag(
        base_url=base_url,
        cerberus_key=cerberus_key,
        provider_key=provider_key,
        endpoint_id=endpoint_id,
        model=model,
        query=query,
    )
    print(f"Answer (with KB context injected by Cerberus):\n{reply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
