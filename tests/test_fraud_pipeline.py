"""Integration: OCR → extraction → fraud engine → risk assessment, end to end."""
import pytest
from sqlalchemy import select

from app.models.application import Application
from app.models.fraud_signal import FraudSignal
from app.models.risk_assessment import RiskAssessment
from app.services import ocr as ocr_service
from app.services.ocr import OcrOutput
from app.tasks.ocr import run_ocr_pipeline_async
from tests.conftest import _SessionFactory

_PDF = b"%PDF-1.4\n%slip\n%%EOF"

# Net pay exceeds gross → CRITICAL signal; 80,000 is also a round number → LOW.
FRAUDY_SALARY = """Employee Name: BOB KUMAR
Net Pay: INR 80,000
Gross Salary: Rs. 65,000
"""


class FraudySalaryEngine:
    name = "fake-fraud-salary"

    def is_available(self) -> bool:
        return True

    def run(self, data: bytes, content_type: str) -> OcrOutput:
        return OcrOutput(FRAUDY_SALARY, 0.96, 1, self.name, "t1", [{"page": 1}])


async def _setup(client, email="fraud@example.com"):
    tokens = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "F"},
        )
    ).json()["tokens"]
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
            headers=h,
        )
    ).json()["id"]
    doc_id = (
        await client.post(
            f"/api/v1/applications/{app_id}/documents",
            data={"document_type": "SALARY_SLIP"},
            files={"file": ("slip.pdf", _PDF, "application/pdf")},
            headers=h,
        )
    ).json()["id"]
    return h, app_id, doc_id


@pytest.mark.asyncio
async def test_pipeline_generates_signals_and_risk(client):
    ocr_service.set_engine_override(FraudySalaryEngine())
    h, app_id, doc_id = await _setup(client)
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)

    async with _SessionFactory() as s:
        signals = (
            await s.execute(select(FraudSignal).where(FraudSignal.application_id == app_id))
        ).scalars().all()
        risk = (
            await s.execute(select(RiskAssessment).where(RiskAssessment.application_id == app_id))
        ).scalars().first()
        app = (await s.execute(select(Application).where(Application.id == app_id))).scalar_one()

    types = {sig.signal_type.value for sig in signals}
    assert "NET_EXCEEDS_GROSS" in types
    assert risk is not None and risk.total_score >= 50
    assert app.current_risk_score == risk.total_score
    assert app.risk_tier is not None


@pytest.mark.asyncio
async def test_signals_and_risk_endpoints(client):
    ocr_service.set_engine_override(FraudySalaryEngine())
    h, app_id, doc_id = await _setup(client, "fraud2@example.com")
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)

    sig = await client.get(f"/api/v1/applications/{app_id}/signals", headers=h)
    assert sig.status_code == 200
    body = sig.json()
    assert any(x["signal_type"] == "NET_EXCEEDS_GROSS" for x in body)
    # Highest severity sorts first.
    assert body[0]["severity"] == "CRITICAL"

    risk = await client.get(f"/api/v1/applications/{app_id}/risk", headers=h)
    assert risk.status_code == 200
    rb = risk.json()
    assert rb["total_score"] >= 50
    assert rb["risk_tier"] in {"MEDIUM", "HIGH", "CRITICAL"}
    assert rb["reasons"]  # explainable breakdown


@pytest.mark.asyncio
async def test_fraud_signals_are_idempotent_on_rerun(client):
    from app.tasks.fraud import run_fraud_engine_async

    ocr_service.set_engine_override(FraudySalaryEngine())
    h, app_id, doc_id = await _setup(client, "fraud3@example.com")
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)
    await run_fraud_engine_async(doc_id, session_factory=_SessionFactory)  # re-run

    async with _SessionFactory() as s:
        live = (
            await s.execute(
                select(FraudSignal).where(
                    FraudSignal.document_id == doc_id, FraudSignal.deleted_at.is_(None)
                )
            )
        ).scalars().all()
        risk = (
            await s.execute(
                select(RiskAssessment).where(
                    RiskAssessment.application_id == app_id, RiskAssessment.deleted_at.is_(None)
                )
            )
        ).scalars().all()
    # No duplicate NET_EXCEEDS_GROSS, single live risk assessment.
    net = [x for x in live if x.signal_type.value == "NET_EXCEEDS_GROSS"]
    assert len(net) == 1
    assert len(risk) == 1
