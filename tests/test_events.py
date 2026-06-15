"""Events: outbox dual-write, relay, reconciliation, real-time engine, ops endpoint."""
import pytest
from sqlalchemy import select

from app.events.publisher import InMemoryPublisher, get_publisher
from app.events.service import make_event, publish_pending, stage
from app.models.enums import EventStatus, EventType
from app.models.event_log import EventLog
from tests.conftest import _SessionFactory


async def _headers(client, email, *, analyst=False):
    reg = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "X"},
        )
    ).json()
    if analyst:
        from app.models.enums import UserRole
        from app.models.user import User

        async with _SessionFactory() as s:
            u = (await s.execute(select(User).where(User.email == email))).scalar_one()
            u.role = UserRole.ANALYST
            await s.commit()
        reg = (
            await client.post(
                "/api/v1/auth/login", json={"email": email, "password": "supersecret1"}
            )
        ).json()
        return {"Authorization": f"Bearer {reg['access_token']}"}
    return {"Authorization": f"Bearer {reg['tokens']['access_token']}"}


@pytest.mark.asyncio
async def test_application_create_stages_and_relays_event(client):
    h = await _headers(client, "ev1@example.com")
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
            headers=h,
        )
    ).json()["id"]

    async with _SessionFactory() as s:
        rows = (
            await s.execute(select(EventLog).where(EventLog.aggregate_id == app_id))
        ).scalars().all()
    created = [r for r in rows if r.event_type == EventType.APPLICATION_CREATED]
    assert len(created) == 1
    # Best-effort relay ran inline → already SENT via the in-memory bus.
    assert created[0].status == EventStatus.SENT
    # PII-free payload (ids + scalars only).
    assert set(created[0].payload).issubset({"applicant_id", "loan_type"})


@pytest.mark.asyncio
async def test_published_to_in_memory_bus(client):
    h = await _headers(client, "ev2@example.com")
    await client.post(
        "/api/v1/applications",
        json={"loan_type": "AUTO", "loan_amount_requested": "300000"},
        headers=h,
    )
    pub = get_publisher()
    assert isinstance(pub, InMemoryPublisher)
    assert any(e.event_type == EventType.APPLICATION_CREATED for e in pub.published)


@pytest.mark.asyncio
async def test_outbox_durability_and_reconciliation():
    """A staged event survives even if the relay didn't run; replay re-publishes it."""
    async with _SessionFactory() as s:
        stage(s, make_event(EventType.RISK_CALCULATED, "application", "app-x",
                            {"score": 90, "tier": "CRITICAL", "signal_count": 3}))
        await s.commit()  # committed PENDING, not yet published

    async with _SessionFactory() as s:
        pending = (
            await s.execute(select(EventLog).where(EventLog.status == EventStatus.PENDING))
        ).scalars().all()
        assert len(pending) == 1

    # Reconciliation/replay publishes it and marks SENT.
    async with _SessionFactory() as s:
        result = await publish_pending(s)
        assert result["sent"] == 1

    async with _SessionFactory() as s:
        still_pending = (
            await s.execute(select(EventLog).where(EventLog.status == EventStatus.PENDING))
        ).scalars().all()
        assert still_pending == []


@pytest.mark.asyncio
async def test_realtime_engine_escalates_critical_risk_idempotently():
    from app.events.consumer import get_realtime_engine

    engine = get_realtime_engine()
    crit = make_event(EventType.RISK_CALCULATED, "application", "app-1",
                      {"score": 95, "tier": "CRITICAL", "signal_count": 5})
    low = make_event(EventType.RISK_CALCULATED, "application", "app-2",
                     {"score": 10, "tier": "LOW", "signal_count": 0})
    await engine.handle(crit)
    await engine.handle(crit)   # redelivery → must not double-escalate
    await engine.handle(low)    # LOW tier → no escalation
    assert len(engine.escalations) == 1
    assert engine.escalations[0].aggregate_id == "app-1"


@pytest.mark.asyncio
async def test_operations_events_endpoint_requires_analyst(client):
    customer = await _headers(client, "ev3@example.com")
    assert (await client.get("/api/v1/operations/events", headers=customer)).status_code == 403

    analyst = await _headers(client, "ev4analyst@example.com", analyst=True)
    r = await client.get("/api/v1/operations/events", headers=analyst)
    assert r.status_code == 200
    assert "items" in r.json()
