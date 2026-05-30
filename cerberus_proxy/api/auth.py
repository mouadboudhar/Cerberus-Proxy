"""Dashboard authentication API (Stage 12, Component 3).

POST /api/auth/verify is the login endpoint: it takes the token in the body
(not the header) so it is intentionally NOT guarded by verify_dashboard_token.
POST /api/auth/rotate requires the current token in X-Dashboard-Token and
issues a new one, invalidating the previous token immediately.
"""

import hmac
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cerberus_proxy.audit.api import verify_dashboard_token

router = APIRouter(prefix="/api/auth")

_TOKEN_ENV = "CERBERUS_DASHBOARD_TOKEN"


class TokenVerify(BaseModel):
    token: str


def _env_file_path() -> str:
    # Overridable for tests/deploys; defaults to .env in the working directory.
    return os.getenv("CERBERUS_ENV_FILE", ".env")


def _update_env_file(path: str, key: str, value: str) -> bool:
    """Rewrite KEY=value in an existing .env. Returns False if no file exists."""
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    new_line = f"{key}={value}\n"
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True


@router.post("/verify")
async def verify_token(body: TokenVerify) -> dict:
    expected = os.getenv(_TOKEN_ENV)
    if not expected or not hmac.compare_digest(body.token, expected):
        raise HTTPException(status_code=401, detail="invalid_dashboard_token")
    return {"valid": True}


@router.post("/rotate", dependencies=[Depends(verify_dashboard_token)])
async def rotate_token() -> dict:
    new_token = secrets.token_urlsafe(32)
    # Update the live process env first so the old token is rejected immediately,
    # then best-effort persist to .env (in-memory only if no .env exists).
    os.environ[_TOKEN_ENV] = new_token
    _update_env_file(_env_file_path(), _TOKEN_ENV, new_token)
    return {"token": new_token}
