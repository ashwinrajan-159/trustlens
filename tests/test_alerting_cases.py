"""Phase 10: RBI thresholds, alert dedup/SLA/escalation, case lifecycle, operations."""
import pytest
from sqlalchemy import select

from app.models.enums import (
    AlertType,
    CaseStatus,
    CaseType,
    RBIReportType,
    SignalSeverity,
    UserRole,
)
from app.models.fraud_alert import FraudAlert
from app.models.user import User
from app.services import rbi
from app.services.alerting import AlertingService
from app.services.cases import CaseService
from tests.conftest import _SessionFactory

# ── RBI threshold engine (pure) ──

def test_rbi_classification_tiers():
    assert rbi.classify(30 * rbi.CR).report_type == RBIReportType.FLASH
    assert rbi.classify(30 * rbi.CR).deadline_hours == 24
    assert rbi.classify(2 * rbi.CR).report_type == RBIReportType.FMR_1
    assert rbi.classify(5 * rbi.LAKH).report_type == RBIReportType.QUARTERLY
    assert rbi.classify(50_000).required is False


def test_fmr_report_shape():
    report = rbi.build_fmr_report(
        alert_number="AL-1", application_number="TL-1", amount=30 * rbi.CR,
        classification=rbi.classify(30 * rbi.CR), risk_tier="CRITICAL", generated_at="2026-01-01T00:00:00Z",
    )
    assert report["report_type"] == "FLASH"
    assert report["amount_involved_cr"] == 30.0
    assert report["regulator"] == "RBI"


# ── Helpers ──

async def _customer(client, email="cw@example.com"):
    reg = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "C"},
        )
    ).json()
    return {"Authorization": f"Bearer {reg['tokens']['access_token']}"}


async def _make_analyst(client, email, role=UserRole.ANALYST):
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1", "full_name": "A"},
    )
    async with _SessionFactory() as s:
        u = (await s.execute(select(User).where(User.email == email))).scalar_one()
        u.role = role
        await s.commit()
    login = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


async def _app(client, headers, amount="20000000"):  # 2 Cr → FMR-1
    return (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": amount},
            headers=headers,
        )
    ).json()["id"]


# ── Alerting service ──

@pytest.mark.asyncio
async def test_alert_creation_sets_rbi_and_sla(client):
    h = await _customer(client, "alert1@example.com")
    app_id = await _app(client, h, amount="300000000")  # 30 Cr → FLASH
    async with _SessionFactory() as s:
        alert = await AlertingService(s).create_for_application(
            app_id, alert_type=AlertType.HIGH_RISK_APPLICATION,
            severity=SignalSeverity.CRITICAL, description="test",
        )
    assert alert.rbi_reporting_required is True
    assert alert.rbi_report_type == RBIReportType.FLASH
    assert alert.sla_deadline is not None
    assert alert.alert_number.startswith("AL-")


@pytest.mark.asyncio
async def test_alert_is_idempotent_per_application_type(client):
    h = await _customer(client, "alert2@example.com")
    app_id = await _app(client, h)
    async with _SessionFactory() as s:
        a1 = await AlertingService(s).create_for_application(
            app_id, alert_type=AlertType.HIGH_RISK_APPLICATION, severity=SignalSeverity.HIGH, description="x")
    async with _SessionFactory() as s:
        a2 = await AlertingService(s).create_for_application(
            app_id, alert_type=AlertType.HIGH_RISK_APPLICATION, severity=SignalSeverity.HIGH, description="x")
    assert a1.id == a2.id  # reused, not duplicated


@pytest.mark.asyncio
async def test_realtime_escalation_creates_alert_on_critical_risk(client):
    """A CRITICAL RISK_CALCULATED event flowing through the bus auto-creates an alert."""
    from app.core.security import new_id
    from app.events import schemas as ev
    from app.events.publisher import get_publisher

    h = await _customer(client, "alert3@example.com")
    app_id = await _app(client, h)
    # Publish a CRITICAL risk event → in-process engine → escalation hook → alert.
    await get_publisher().publish(ev.risk_calculated(
        new_id(), app_id, score=95, tier="CRITICAL", signal_count=4))

    async with _SessionFactory() as s:
        alerts = (await s.execute(select(FraudAlert).where(FraudAlert.application_id == app_id))).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.HIGH_RISK_APPLICATION


# ── Case lifecycle ──

@pytest.mark.asyncio
async def test_case_lifecycle_and_senior_close(client):
    analyst = await _make_analyst(client, "caseanalyst@example.com", UserRole.ANALYST)
    created = await client.post(
        "/api/v1/cases",
        json={"case_type": "INVESTIGATION", "summary": "Review ring", "priority": "HIGH"},
        headers=analyst,
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    # Plain analyst cannot close (senior-only).
    closed = await client.post(
        f"/api/v1/cases/{case_id}/close", json={"outcome": "FRAUD_CONFIRMED"}, headers=analyst
    )
    assert closed.status_code == 403

    senior = await _make_analyst(client, "casesenior@example.com", UserRole.SENIOR_ANALYST)
    ok = await client.post(
        f"/api/v1/cases/{case_id}/close", json={"outcome": "FRAUD_CONFIRMED"}, headers=senior
    )
    assert ok.status_code == 200 and ok.json()["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_case_service_create(client):
    async with _SessionFactory() as s:
        case = await CaseService(s).create(case_type=CaseType.FRAUD_RING, summary="ring of 3")
    assert case.status == CaseStatus.OPEN
    assert case.case_number.startswith("CS-")


# ── Operations ──

@pytest.mark.asyncio
async def test_operations_overview_and_rbac(client):
    customer = await _customer(client, "opscust@example.com")
    assert (await client.get("/api/v1/operations/overview", headers=customer)).status_code == 403

    analyst = await _make_analyst(client, "opsanalyst@example.com")
    r = await client.get("/api/v1/operations/overview", headers=analyst)
    assert r.status_code == 200
    body = r.json()
    assert "applications_total" in body and "alerts_open" in body


@pytest.mark.asyncio
async def test_fmr_report_endpoint_senior_only(client):
    h = await _customer(client, "fmr@example.com")
    app_id = await _app(client, h, amount="300000000")
    async with _SessionFactory() as s:
        alert = await AlertingService(s).create_for_application(
            app_id, alert_type=AlertType.HIGH_RISK_APPLICATION, severity=SignalSeverity.CRITICAL, description="x")

    analyst = await _make_analyst(client, "fmranalyst@example.com", UserRole.ANALYST)
    assert (await client.get(f"/api/v1/alerts/{alert.id}/fmr-report", headers=analyst)).status_code == 403

    senior = await _make_analyst(client, "fmrsenior@example.com", UserRole.SENIOR_ANALYST)
    r = await client.get(f"/api/v1/alerts/{alert.id}/fmr-report", headers=senior)
    assert r.status_code == 200
    assert r.json()["report"]["report_type"] == "FLASH"
