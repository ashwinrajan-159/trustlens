"""Audit trail: entries are written and form a verifiable hash chain (#7, #11, #13)."""

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.enums import AuditAction


async def _session(client):
    # Reuse the same session factory the app override uses.
    from tests.conftest import _SessionFactory

    return _SessionFactory()


@pytest.mark.asyncio
async def test_register_and_login_write_audit_entries(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "aud@example.com", "password": "supersecret1", "full_name": "Aud"},
    )
    await client.post(
        "/api/v1/auth/login", json={"email": "aud@example.com", "password": "supersecret1"}
    )
    async with await _session(client) as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
    actions = {r.action for r in rows}
    assert AuditAction.CREATE in actions
    assert AuditAction.LOGIN in actions


@pytest.mark.asyncio
async def test_audit_hash_chain_is_consistent(client):
    # Generate several audited actions.
    reg = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "chain@example.com", "password": "supersecret1", "full_name": "C"},
        )
    ).json()
    h = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}
    await client.post(
        "/api/v1/applications",
        json={"loan_type": "HOME", "loan_amount_requested": "1000000"},
        headers=h,
    )

    async with await _session(client) as s:
        rows = list(
            (
                await s.execute(select(AuditLog).order_by(AuditLog.created_at.asc(), AuditLog.id.asc()))
            ).scalars().all()
        )
    assert len(rows) >= 2
    # Each entry's prev_hash matches the previous entry's entry_hash (genesis for first).
    prev = "0" * 64
    for row in rows:
        assert row.prev_hash == prev
        assert row.entry_hash and len(row.entry_hash) == 64
        prev = row.entry_hash


@pytest.mark.asyncio
async def test_analyst_read_is_audited(client):
    # Customer creates an application.
    cust = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "cust2@example.com", "password": "supersecret1", "full_name": "Cust"},
        )
    ).json()
    ch = {"Authorization": f"Bearer {cust['tokens']['access_token']}"}
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "AUTO", "loan_amount_requested": "500000"},
            headers=ch,
        )
    ).json()["id"]

    # Promote a second user to ANALYST directly in the DB, then view the application.
    from app.models.enums import UserRole
    from app.models.user import User
    from tests.conftest import _SessionFactory

    analyst = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "analyst@example.com", "password": "supersecret1", "full_name": "An"},
        )
    ).json()
    async with _SessionFactory() as s:
        u = (await s.execute(select(User).where(User.email == "analyst@example.com"))).scalar_one()
        u.role = UserRole.ANALYST
        await s.commit()

    ah = {"Authorization": f"Bearer {analyst['tokens']['access_token']}"}
    # NOTE: token still encodes CUSTOMER role; re-login to get an ANALYST token.
    relog = (
        await client.post(
            "/api/v1/auth/login", json={"email": "analyst@example.com", "password": "supersecret1"}
        )
    ).json()
    ah = {"Authorization": f"Bearer {relog['access_token']}"}
    r = await client.get(f"/api/v1/applications/{app_id}", headers=ah)
    assert r.status_code == 200

    async with _SessionFactory() as s:
        reads = (
            await s.execute(select(AuditLog).where(AuditLog.action == AuditAction.READ_PII))
        ).scalars().all()
    assert any(x.entity_id == app_id for x in reads)
