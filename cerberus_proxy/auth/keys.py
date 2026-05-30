import hashlib
import hmac
import secrets

_KEY_PREFIX = "llmg_"


def generate_api_key() -> str:
    """Generate a cryptographically secure API key: "llmg_" + 32 url-safe random bytes."""
    return _KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(plaintext: str) -> str:
    """SHA-256 hex digest of the plaintext key — this is what gets stored, never the plaintext."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def verify_key(plaintext: str, hashed: str) -> bool:
    """Constant-time comparison of hash_key(plaintext) against a stored hash."""
    return hmac.compare_digest(hash_key(plaintext), hashed)
