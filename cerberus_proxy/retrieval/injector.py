from cerberus_proxy.retrieval.base import RetrievedDocument


def inject_context(
    messages: list[dict],
    documents: list[RetrievedDocument],
) -> list[dict]:
    if not documents:
        return messages

    parts = []
    for i, doc in enumerate(documents, 1):
        parts.append(f"[Document {i}: {doc.source}]\n{doc.content}")
    context = "\n\n".join(parts)

    # Never mutate the caller's list or dicts — build fresh copies throughout.
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        first["content"] = f"{first.get('content', '')}\n\nContext:\n{context}"
        return [first, *(dict(m) for m in messages[1:])]

    system_msg = {"role": "system", "content": f"Relevant context:\n{context}"}
    return [system_msg, *(dict(m) for m in messages)]
