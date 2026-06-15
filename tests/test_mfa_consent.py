"""MFA enrollment + login gate (#25) and DPDP consent withdrawal (#24)."""
import pyotp
import pytest


async def _register(client, email="mfa@example.com"):
    return (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "Mfa"},
        )
    ).json()


@pytest.mark.asyncio
async def test_mfa_enroll_then_login_requires_code(client):
    reg = await _register(client)
    h = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}

    enroll = await client.post("/api/v1/auth/mfa/enroll", headers=h)
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    assert enroll.json()["provisioning_uri"].startswith("otpauth://")

    code = pyotp.TOTP(secret).now()
    verify = await client.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=h)
    assert verify.status_code == 200

    # Login without a code is now rejected.
    no_code = await client.post(
        "/api/v1/auth/login", json={"email": "mfa@example.com", "password": "supersecret1"}
    )
    assert no_code.status_code == 401

    # Login with a valid code succeeds.
    ok = await client.post(
        "/api/v1/auth/login",
        json={"email": "mfa@example.com", "password": "supersecret1", "mfa_code": pyotp.TOTP(secret).now()},
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_consent_withdrawal(client):
    reg = await _register(client, "consent@example.com")
    h = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}
    r = await client.post("/api/v1/auth/consent/withdraw", headers=h)
    assert r.status_code == 200
    assert "withdrawal" in r.json()["message"].lower()
