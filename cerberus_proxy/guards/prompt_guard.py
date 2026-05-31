"""Custom Prompt Guard — an OPTIONAL LLM-as-judge POLICY layer (Stage 14c).

⚠️  NON-DETERMINISTIC. Unlike the Input/Output guards (deterministic regex +
    validation), this guard asks an LLM to judge a message against a customer-
    defined policy. That means:
      • It adds latency — one extra LLM round-trip per request.
      • It adds cost — one extra completion billed to the customer's provider.
      • It can vary between runs — the same input may not always decide the same.

    Treat it as a *business-policy* layer ("never discuss competitor products",
    "only answer HR questions"), NOT a security control. The deterministic
    guards remain the security foundation; this guard never weakens them.

    It ALWAYS fails open: any timeout, transport error, HTTP error, or
    unparseable/ambiguous response results in the request being ALLOWED. A
    flaky or unreachable evaluator must never block legitimate traffic.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger("cerberus_proxy.guards.prompt_guard")


class PromptGuard:
    """Evaluate a user message against a policy prompt using an LLM judge.

    Stateless. Calls the upstream LLM directly with httpx — never through the
    Cerberus proxy itself — to avoid a circular request loop (the proxy calling
    itself calling the proxy ...).
    """

    NON_DETERMINISTIC_WARNING = (
        "PromptGuard uses an LLM for evaluation. "
        "It is non-deterministic and adds latency + API cost. "
        "Use deterministic guards for security guarantees."
    )

    # Hard cap on the evaluation call. Exceeding it fails open (ALLOW).
    TIMEOUT_SECONDS = 5.0

    async def evaluate(
        self,
        user_message: str,
        policy_prompt: str,
        model: str,
        upstream_url: str,
        provider_key: str,
    ) -> tuple[bool, str]:
        """Return ``(allowed, reason_text)``.

        ``allowed`` is True when the policy permits the message (or when the
        guard fails open). ``reason_text`` is the judge's raw reply, or
        ``"prompt_guard_error"`` on failure.
        """
        messages = [
            {"role": "system", "content": policy_prompt},
            {
                "role": "user",
                "content": f"Evaluate this message:\n\n{user_message}",
            },
        ]

        try:
            # Hard 5s ceiling around the whole call, independent of httpx's own
            # per-phase timeouts — guarantees we never hang a request.
            text = await asyncio.wait_for(
                self._call_judge(messages, model, upstream_url, provider_key),
                timeout=self.TIMEOUT_SECONDS,
            )
        except Exception as e:  # noqa: BLE001 — fail open on ANY failure
            logger.warning("Prompt guard failed: %s", e)
            return (True, "prompt_guard_error")

        decision = text.upper()
        if decision.startswith("ALLOW"):
            return (True, text)
        if decision.startswith("BLOCK"):
            return (False, text)

        # Neither verdict — don't guess. Fail open and surface it for tuning.
        logger.warning("Ambiguous prompt guard response: %s", text)
        return (True, text)

    async def _call_judge(
        self,
        messages: list[dict],
        model: str,
        upstream_url: str,
        provider_key: str,
    ) -> str:
        url = upstream_url.rstrip("/") + "/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0,
        }
        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()
