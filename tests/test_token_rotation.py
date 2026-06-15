"""Refresh-token rotation, reuse detection, and logout (#3)."""
import pytest


async def _register(client, email="rot@example.com"):
    return (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "Rot"},
        )
    ).json()["tokens"]


@pytest.mark.asyncio
async def test_refresh_rotates_token(client):
    tokens = await _register(client)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_refresh = r.json()["refresh_token"]
    assert new_refresh != tokens["refresh_token"]


@pytest.mark.asyncio
async def test_old_refresh_token_reuse_revokes_family(client):
    tokens = await _register(client)
    old = tokens["refresh_token"]
    # First refresh rotates; old token is now stale.
    await client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    # Replaying the old (stolen) token is reuse → rejected + family revoked.
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert reuse.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_session(client):
    tokens = await _register(client)
    out = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert out.status_code == 200
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert after.status_code == 401
