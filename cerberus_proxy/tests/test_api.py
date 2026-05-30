import pytest

DASH_TOKEN = "test-dashboard-token"


@pytest.fixture
def auth(monkeypatch):
    """Set the dashboard token in the env and return the matching header."""
    monkeypatch.setenv("CERBERUS_DASHBOARD_TOKEN", DASH_TOKEN)
    return {"X-Dashboard-Token": DASH_TOKEN}


def _endpoint_body(**over):
    body = {
        "name": "Production Chatbot",
        "provider": "openai",
        "upstream_url": "https://api.openai.com",
        "default_model": "gpt-4o-mini",
    }
    body.update(over)
    return body


async def _create_endpoint(client, auth, **over):
    return await client.post("/api/endpoints", json=_endpoint_body(**over), headers=auth)


# -- Endpoints API -------------------------------------------------------------


async def test_get_endpoints_empty(client, session_factory, auth):
    res = await client.get("/api/endpoints", headers=auth)
    assert res.status_code == 200
    assert res.json() == []


async def test_create_endpoint(client, session_factory, auth):
    res = await _create_endpoint(client, auth)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] is not None
    assert data["provider"] == "openai"
    assert data["name"] == "Production Chatbot"
    assert "stats" in data


async def test_create_endpoint_invalid_provider(client, session_factory, auth):
    res = await _create_endpoint(client, auth, provider="unknown")
    assert res.status_code == 422


async def test_get_endpoint_by_id(client, session_factory, auth):
    created = (await _create_endpoint(client, auth)).json()
    res = await client.get(f"/api/endpoints/{created['id']}", headers=auth)
    assert res.status_code == 200
    assert res.json()["name"] == "Production Chatbot"


async def test_patch_endpoint(client, session_factory, auth):
    created = (await _create_endpoint(client, auth)).json()
    res = await client.patch(
        f"/api/endpoints/{created['id']}", json={"name": "Renamed"}, headers=auth
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"


async def test_delete_endpoint(client, session_factory, auth):
    created = (await _create_endpoint(client, auth)).json()
    res = await client.delete(f"/api/endpoints/{created['id']}", headers=auth)
    assert res.status_code == 200
    assert res.json() == {"deleted": True}
    # Soft-deleted endpoints are no longer retrievable by id.
    res = await client.get(f"/api/endpoints/{created['id']}", headers=auth)
    assert res.status_code == 404


# -- Keys API ------------------------------------------------------------------


async def test_create_key_returns_plaintext_once(client, session_factory, auth):
    res = await client.post("/api/keys", json={"name": "mobile-app-prod"}, headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert "key" in data
    assert data["key"].startswith("llmg_")


async def test_get_key_no_plaintext(client, session_factory, auth):
    created = (
        await client.post("/api/keys", json={"name": "svc"}, headers=auth)
    ).json()
    res = await client.get(f"/api/keys/{created['id']}", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert "key" not in data
    assert "key_hash" not in data


async def test_revoke_key(client, session_factory, auth):
    created = (
        await client.post("/api/keys", json={"name": "svc"}, headers=auth)
    ).json()
    res = await client.delete(f"/api/keys/{created['id']}", headers=auth)
    assert res.status_code == 200
    assert res.json() == {"revoked": True}


async def test_key_usage_returns_windows(client, session_factory, auth):
    created = (
        await client.post("/api/keys", json={"name": "svc"}, headers=auth)
    ).json()
    res = await client.get(f"/api/keys/{created['id']}/usage", headers=auth)
    assert res.status_code == 200
    usage = res.json()
    assert {"minute", "hour", "day"} <= set(usage.keys())


# -- Auth API ------------------------------------------------------------------


async def test_auth_verify_valid_token(client, session_factory, auth):
    res = await client.post("/api/auth/verify", json={"token": DASH_TOKEN})
    assert res.status_code == 200
    assert res.json() == {"valid": True}


async def test_auth_verify_invalid_token(client, session_factory, auth):
    res = await client.post("/api/auth/verify", json={"token": "wrong-token"})
    assert res.status_code == 401


# -- Server API ----------------------------------------------------------------


async def test_server_info_returns_version(client, session_factory, auth):
    res = await client.get("/api/server/info", headers=auth)
    assert res.status_code == 200
    assert "version" in res.json()


async def test_health_no_auth(client, session_factory):
    # No token header and no auth fixture: /api/server/health is public.
    res = await client.get("/api/server/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# -- Auth enforcement ----------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/endpoints"),
        ("POST", "/api/endpoints"),
        ("GET", "/api/endpoints/1"),
        ("PATCH", "/api/endpoints/1"),
        ("DELETE", "/api/endpoints/1"),
        ("GET", "/api/keys"),
        ("POST", "/api/keys"),
        ("GET", "/api/keys/1"),
        ("DELETE", "/api/keys/1"),
        ("PATCH", "/api/keys/1/limits"),
        ("GET", "/api/keys/1/usage"),
        ("POST", "/api/auth/rotate"),
        ("GET", "/api/server/info"),
        ("GET", "/api/guards/config"),
        ("PATCH", "/api/guards/config"),
    ],
)
async def test_all_routes_require_token(client, session_factory, auth, method, path):
    # `auth` sets CERBERUS_DASHBOARD_TOKEN so the 401 is due to the MISSING
    # header, not a missing server-side token. No header is sent here.
    res = await client.request(method, path, json={})
    assert res.status_code == 401
