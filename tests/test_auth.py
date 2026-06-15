"""Auth flow tests: register, login, refresh, me, RBAC."""
import pytest


async def _register(client, email="alice@example.com", password="supersecret1"):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Alice"},
    )


@pytest.mark.asyncio
async def test_register_returns_tokens_and_masks_password(client):
    r = await _register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "CUSTOMER"
    assert "hashed_password" not in body["user"]
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]


@pytest.mark.asyncio
async def test_duplicate_email_conflicts(client):
    await _register(client)
    r = await _register(client)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_login_success_and_failure(client):
    await _register(client)
    ok = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "supersecret1"},
    )
    assert ok.status_code == 200
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "wrong"},
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_me_with_token(client):
    tokens = (await _register(client)).json()["tokens"]
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_refresh_issues_new_pair(client):
    tokens = (await _register(client)).json()["tokens"]
    r = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


@pytest.mark.asyncio
async def test_access_token_rejected_as_refresh(client):
    tokens = (await _register(client)).json()["tokens"]
    r = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert r.status_code == 401
