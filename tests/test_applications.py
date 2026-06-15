"""Application lifecycle + RBAC + state-machine tests."""
import pytest


async def _auth_headers(client, email="bob@example.com"):
    tokens = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "Bob"},
        )
    ).json()["tokens"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.asyncio
async def test_create_application_draft(client):
    h = await _auth_headers(client)
    r = await client.post(
        "/api/v1/applications",
        json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
        headers=h,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "DRAFT"
    assert body["application_number"].startswith("TL-")


@pytest.mark.asyncio
async def test_submit_transitions_to_submitted(client):
    h = await _auth_headers(client)
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "PERSONAL", "loan_amount_requested": "100000"},
            headers=h,
        )
    ).json()["id"]
    r = await client.post(f"/api/v1/applications/{app_id}/submit", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_double_submit_is_invalid_transition(client):
    h = await _auth_headers(client)
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "AUTO", "loan_amount_requested": "800000"},
            headers=h,
        )
    ).json()["id"]
    await client.post(f"/api/v1/applications/{app_id}/submit", headers=h)
    r = await client.post(f"/api/v1/applications/{app_id}/submit", headers=h)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_customer_cannot_access_others_application(client):
    h1 = await _auth_headers(client, "carol@example.com")
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "9000000"},
            headers=h1,
        )
    ).json()["id"]
    h2 = await _auth_headers(client, "dave@example.com")
    r = await client.get(f"/api/v1/applications/{app_id}", headers=h2)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_customer_cannot_decide(client):
    h = await _auth_headers(client, "erin@example.com")
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "9000000"},
            headers=h,
        )
    ).json()["id"]
    await client.post(f"/api/v1/applications/{app_id}/submit", headers=h)
    r = await client.post(
        f"/api/v1/applications/{app_id}/decision",
        json={"approve": True, "reason": "looks good"},
        headers=h,
    )
    assert r.status_code == 403  # CUSTOMER lacks analyst role
