"""Health probe tests."""
import pytest


@pytest.mark.asyncio
async def test_liveness(client):
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_db_ok(client):
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["database"] == "ok"


@pytest.mark.asyncio
async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert r.json()["version"] == "1.0.0"
