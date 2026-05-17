import copy

import httpx
import pytest
import respx

from llmguard.guards.base import ReasonCode, Severity
from llmguard.guards.output_guard import (
    OutputGuard,
    calculate_entropy,
    luhn_check,
)

UPSTREAM_URL = "https://api.openai.com/v1/chat/completions"


def _completion(content: str) -> dict:
    return {
        "id": "chatcmpl-out",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


# ---------- unit tests ----------


def test_luhn_valid_and_invalid():
    assert luhn_check("4242424242424242") is True
    assert luhn_check("4242 4242 4242 4242") is True
    assert luhn_check("4242-4242-4242-4242") is True
    assert luhn_check("4242424242424241") is False
    assert luhn_check("not-a-number") is False


def test_entropy_low_and_high():
    assert calculate_entropy("") == 0.0
    assert calculate_entropy("aaaaaaaa") == 0.0
    assert calculate_entropy("Xk8mN3qP7vL2wR5jY9tH6bF4cZ1nGsDaEzMqUiPo") > 4.5


@pytest.mark.asyncio
async def test_clean_response_passes():
    result = await OutputGuard().scan("The weather today is sunny and mild.")
    assert result.passed is True
    assert result.reason_code == ReasonCode.CLEAN


@pytest.mark.asyncio
async def test_credit_card_valid_luhn_detected():
    result = await OutputGuard().scan("Card on file: 4242424242424242")
    assert result.passed is False
    assert result.reason_code == ReasonCode.PII_DETECTED
    assert result.severity == Severity.CRITICAL
    assert result.matched_pattern == "CREDIT_CARD"


@pytest.mark.asyncio
async def test_credit_card_invalid_luhn_not_flagged():
    matches = OutputGuard().find_all_matches("Reference number: 4242424242424241")
    cc = [m for m in matches if m["name"] == "CREDIT_CARD"]
    assert cc == []


@pytest.mark.asyncio
async def test_email_detected():
    result = await OutputGuard().scan("Contact me at alice.smith@example.com.")
    assert result.passed is False
    assert result.matched_pattern == "EMAIL"
    assert result.reason_code == ReasonCode.PII_DETECTED


@pytest.mark.asyncio
async def test_ssn_detected():
    result = await OutputGuard().scan("Her SSN is 123-45-6789.")
    assert result.passed is False
    assert result.matched_pattern == "SSN_US"
    assert result.severity == Severity.CRITICAL


@pytest.mark.asyncio
async def test_iban_detected():
    result = await OutputGuard().scan("Account: GB82WEST12345698765432")
    assert result.passed is False
    assert result.matched_pattern == "IBAN"


@pytest.mark.asyncio
async def test_openai_key_detected():
    result = await OutputGuard().scan(
        "Use sk-abcdefghijklmnopqrstuvwxyz123456 as your key"
    )
    assert result.passed is False
    assert result.matched_pattern == "OPENAI_API_KEY"
    assert result.reason_code == ReasonCode.SECRET_DETECTED


@pytest.mark.asyncio
async def test_anthropic_key_detected():
    key = "sk-ant-api03-" + "A" * 93
    result = await OutputGuard().scan(f"Token: {key}")
    assert result.passed is False
    assert result.matched_pattern == "ANTHROPIC_API_KEY"


@pytest.mark.asyncio
async def test_aws_access_key_detected():
    result = await OutputGuard().scan("Key id: AKIAIOSFODNN7EXAMPLE")
    assert result.passed is False
    assert result.matched_pattern == "AWS_ACCESS_KEY_ID"


@pytest.mark.asyncio
async def test_github_pat_detected():
    token = "ghp_" + "a" * 36
    result = await OutputGuard().scan(f"git config: {token}")
    assert result.passed is False
    assert result.matched_pattern == "GITHUB_PAT"


@pytest.mark.asyncio
async def test_gitlab_pat_detected():
    token = "glpat-" + "a" * 20
    result = await OutputGuard().scan(f"Authorization: Bearer {token}")
    assert result.passed is False
    assert result.matched_pattern == "GITLAB_PAT"


@pytest.mark.asyncio
async def test_stripe_live_key_detected():
    key = "sk_live_" + "a" * 24
    result = await OutputGuard().scan(f"Stripe key: {key}")
    assert result.passed is False
    assert result.matched_pattern == "STRIPE_LIVE_KEY"


@pytest.mark.asyncio
async def test_slack_token_detected():
    token = "xoxb-1234567890-1234567890-abcdefghij"
    result = await OutputGuard().scan(f"Slack bot token: {token}")
    assert result.passed is False
    assert result.matched_pattern == "SLACK_TOKEN"


@pytest.mark.asyncio
async def test_sendgrid_key_detected():
    key = "SG." + "a" * 22 + "." + "b" * 43
    result = await OutputGuard().scan(f"Mail key: {key}")
    assert result.passed is False
    assert result.matched_pattern == "SENDGRID_KEY"


@pytest.mark.asyncio
async def test_postgres_connection_string_detected():
    result = await OutputGuard().scan(
        "DATABASE_URL=postgresql://user:s3cret@db.internal:5432/mydb"
    )
    assert result.passed is False
    assert result.matched_pattern == "POSTGRES_URL"


@pytest.mark.asyncio
async def test_mongodb_connection_string_detected():
    result = await OutputGuard().scan(
        "Connect using mongodb+srv://admin:p4ss@cluster0.example.mongodb.net/app"
    )
    assert result.passed is False
    assert result.matched_pattern == "MONGODB_URL"


@pytest.mark.asyncio
async def test_jwt_detected():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signatureValue"
    result = await OutputGuard().scan(f"Bearer {jwt}")
    assert result.passed is False
    assert result.matched_pattern == "JWT"
    assert result.severity == Severity.HIGH
    assert "sensitive claims" in result.detail


@pytest.mark.asyncio
async def test_rsa_private_key_detected():
    body = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAA...\n-----END RSA PRIVATE KEY-----"
    result = await OutputGuard().scan(body)
    assert result.passed is False
    assert result.matched_pattern == "RSA_PRIVATE_KEY"


@pytest.mark.asyncio
async def test_ssh_private_key_detected():
    body = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZX...\n-----END OPENSSH PRIVATE KEY-----"
    result = await OutputGuard().scan(body)
    assert result.passed is False
    assert result.matched_pattern == "SSH_PRIVATE_KEY"


@pytest.mark.asyncio
async def test_npm_token_detected():
    token = "npm_" + "a" * 36
    result = await OutputGuard().scan(f"//registry.npmjs.org/:_authToken={token}")
    assert result.passed is False
    assert result.matched_pattern == "NPM_TOKEN"


@pytest.mark.asyncio
async def test_high_entropy_string_detected():
    # Random-looking 40-char string, no context, no named-pattern match.
    blob = "Xk8mN3qP7vL2wR5jY9tH6bF4cZ1nGsDaEzMqUiPo"
    matches = OutputGuard().find_all_matches(f"opaque token: {blob}")
    names = {m["name"] for m in matches}
    assert "HIGH_ENTROPY_STRING" in names


def test_redaction_replaces_all_matches():
    text = (
        "Card 4242424242424242, email alice@example.com, "
        "key sk-abcdefghijklmnopqrstuvwxyz123456 — please secure."
    )
    redacted, names = OutputGuard().redact(text)
    assert "4242424242424242" not in redacted
    assert "alice@example.com" not in redacted
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "[REDACTED:CREDIT_CARD]" in redacted
    assert "[REDACTED:EMAIL]" in redacted
    assert "[REDACTED:OPENAI_API_KEY]" in redacted
    assert set(names) == {"CREDIT_CARD", "EMAIL", "OPENAI_API_KEY"}


def test_redaction_preserves_clean_text():
    text = "Hello user, your order ORD-001 ships tomorrow at 9am. Thanks!"
    redacted, names = OutputGuard().redact(text)
    assert redacted == text
    assert names == []


# ---------- integration tests ----------


@pytest.mark.asyncio
@respx.mock
async def test_proxy_redacts_credit_card_in_response(
    monkeypatch, session_factory, client, create_key
):
    monkeypatch.setenv("LLMGUARD_OUTPUT_GUARD_ACTION", "redact")
    api_key, _ = await create_key("out-cc")
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(
            200, json=_completion("Your saved card is 4242424242424242, thanks.")
        )
    )
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"X-LLMGuard-Key": api_key, "Authorization": "Bearer sk-customer"},
    )
    assert response.status_code == 200
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    assert "4242424242424242" not in content
    assert "[REDACTED:CREDIT_CARD]" in content
    assert "CREDIT_CARD" in response.headers["X-LLMGuard-Redacted"]


@pytest.mark.asyncio
@respx.mock
async def test_proxy_redacts_api_key_in_response(
    monkeypatch, session_factory, client, create_key
):
    monkeypatch.setenv("LLMGUARD_OUTPUT_GUARD_ACTION", "redact")
    api_key, _ = await create_key("out-key")
    leaked = "sk-abcdefghijklmnopqrstuvwxyz123456"
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=_completion(f"Set OPENAI_API_KEY={leaked}"))
    )
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"X-LLMGuard-Key": api_key, "Authorization": "Bearer sk-customer"},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert leaked not in content
    assert "[REDACTED:OPENAI_API_KEY]" in content
    assert "OPENAI_API_KEY" in response.headers["X-LLMGuard-Redacted"]


@pytest.mark.asyncio
@respx.mock
async def test_proxy_blocks_in_block_mode(
    monkeypatch, session_factory, client, create_key
):
    monkeypatch.setenv("LLMGUARD_OUTPUT_GUARD_ACTION", "block")
    api_key, _ = await create_key("out-block")
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(
            200, json=_completion("Card: 4242424242424242")
        )
    )
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"X-LLMGuard-Key": api_key, "Authorization": "Bearer sk-customer"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "blocked_by_guard"
    assert body["guard"] == "output_guard"
    assert body["reason_code"] == ReasonCode.PII_DETECTED.value


@pytest.mark.asyncio
@respx.mock
async def test_proxy_log_only_passes_through(
    monkeypatch, session_factory, client, create_key
):
    monkeypatch.setenv("LLMGUARD_OUTPUT_GUARD_ACTION", "log_only")
    api_key, _ = await create_key("out-log")
    upstream_body = _completion("Card on file: 4242424242424242")
    respx.post(UPSTREAM_URL).mock(
        return_value=httpx.Response(200, json=copy.deepcopy(upstream_body))
    )
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
        headers={"X-LLMGuard-Key": api_key, "Authorization": "Bearer sk-customer"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == upstream_body["choices"][0]["message"]["content"]
    assert "X-LLMGuard-Redacted" not in response.headers
