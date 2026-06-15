"""Property + financial intelligence: pure services, duplicate collateral, pipeline."""
import pytest
from sqlalchemy import select

from app.models.enums import SignalScope
from app.models.fraud_signal import FraudSignal
from app.services import financial as fin
from app.services import ocr as ocr_service
from app.services import property_intel as prop
from app.services.ocr import OcrOutput
from app.tasks.ocr import run_ocr_pipeline_async
from tests.conftest import _SessionFactory

# ── Pure property logic ──

def test_inflated_valuation():
    signals, summary = prop.validate(prop.PropertyContext(
        sale_considerations=[5_000_000], valuations=[8_000_000],
    ))
    assert any(s.signal_type == "INFLATED_VALUATION" for s in signals)
    assert summary.is_inflated is True


def test_survey_conflict_and_owner_mismatch():
    signals, _ = prop.validate(prop.PropertyContext(
        survey_numbers=["12/4A", "99/1B"],
        owner_names=["RAVI KUMAR"],
        applicant_name="BOB SINGH",
    ))
    types = {s.signal_type for s in signals}
    assert "SURVEY_NUMBER_CONFLICT" in types
    assert "PROPERTY_OWNER_MISMATCH" in types


def test_duplicate_collateral_is_critical():
    signals, _ = prop.validate(prop.PropertyContext(
        survey_numbers=["12/4A"], duplicate_collateral_app_ids=["other-app"],
    ))
    dup = next(s for s in signals if s.signal_type == "DUPLICATE_COLLATERAL")
    assert dup.severity == "CRITICAL"


def test_clean_property_no_signals():
    signals, summary = prop.validate(prop.PropertyContext(
        survey_numbers=["12/4A"], sale_considerations=[5_000_000], valuations=[5_100_000],
        owner_names=["BOB KUMAR"], applicant_name="Bob Kumar",
    ))
    assert signals == []
    assert summary.is_inflated is False


# ── Pure financial logic ──

def test_revenue_mismatch_and_impossible_ratio():
    signals, _ = fin.validate(fin.FinancialContext(
        itr_revenues=[1_000_000], gst_revenues=[2_000_000], net_profits=[3_000_000],
    ))
    types = {s.signal_type for s in signals}
    assert "REVENUE_MISMATCH" in types
    assert "IMPOSSIBLE_FINANCIAL_RATIO" in types


def test_consistent_financials_no_signal():
    signals, _ = fin.validate(fin.FinancialContext(
        itr_revenues=[1_000_000], gst_revenues=[1_050_000], net_profits=[200_000],
    ))
    assert signals == []


# ── Pipeline integration ──

_PDF = b"%PDF-1.4\n%p\n%%EOF"


class _Engine:
    name = "fake-p"

    def __init__(self, text):
        self.text = text

    def is_available(self):
        return True

    def run(self, data, content_type):
        return OcrOutput(self.text, 0.96, 1, self.name, "t1", [{"page": 1}])


async def _register(client, email):
    tokens = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "X"},
        )
    ).json()["tokens"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _new_app(client, h, loan_type="HOME"):
    return (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": loan_type, "loan_amount_requested": "5000000"},
            headers=h,
        )
    ).json()["id"]


async def _upload_run(client, h, app_id, dtype, filename, text):
    body = _PDF + f"\n%{filename}".encode()
    doc_id = (
        await client.post(
            f"/api/v1/applications/{app_id}/documents",
            data={"document_type": dtype},
            files={"file": (filename, body, "application/pdf")},
            headers=h,
        )
    ).json()["id"]
    ocr_service.set_engine_override(_Engine(text))
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)
    return doc_id


@pytest.mark.asyncio
async def test_pipeline_flags_inflated_valuation(client):
    h = await _register(client, "prop1@example.com")
    app_id = await _new_app(client, h)
    await _upload_run(client, h, app_id, "SALE_DEED", "deed.pdf",
                      "Purchaser: BOB KUMAR\nSurvey No: 12/4A\nSale Consideration: Rs. 5000000\n")
    await _upload_run(client, h, app_id, "VALUATION_REPORT", "val.pdf",
                      "Survey No: 12/4A\nFair Market Value: Rs. 9000000\n")

    r = await client.get(f"/api/v1/applications/{app_id}/property", headers=h)
    assert r.status_code == 200
    assert r.json()["is_inflated"] is True

    sig = await client.get(f"/api/v1/applications/{app_id}/signals", headers=h)
    types = {s["signal_type"] for s in sig.json()}
    assert "INFLATED_VALUATION" in types
    assert any(s["signal_scope"] == "PROPERTY" for s in sig.json())


@pytest.mark.asyncio
async def test_pipeline_detects_duplicate_collateral_across_applications(client):
    h = await _register(client, "prop2@example.com")
    # First application pledges survey 77/2C.
    app1 = await _new_app(client, h)
    await _upload_run(client, h, app1, "SALE_DEED", "d1.pdf", "Survey No: 77/2C\nSale Consideration: 4000000\n")
    # Second application pledges the SAME survey number → duplicate collateral.
    app2 = await _new_app(client, h)
    await _upload_run(client, h, app2, "SALE_DEED", "d2.pdf", "Survey No: 77/2C\nSale Consideration: 4000000\n")

    sig = await client.get(f"/api/v1/applications/{app2}/signals", headers=h)
    types = {s["signal_type"] for s in sig.json()}
    assert "DUPLICATE_COLLATERAL" in types


@pytest.mark.asyncio
async def test_pipeline_financial_revenue_mismatch(client):
    h = await _register(client, "prop3@example.com")
    app_id = await _new_app(client, h, loan_type="BUSINESS")
    await _upload_run(client, h, app_id, "ITR", "itr.pdf", "Gross Total Income: 1000000\n")
    await _upload_run(client, h, app_id, "GST_RETURN", "gst.pdf", "Total Turnover: 2500000\n")

    fin_r = await client.get(f"/api/v1/applications/{app_id}/financial", headers=h)
    assert fin_r.status_code == 200
    assert fin_r.json()["itr_revenue"] == 1000000
    assert fin_r.json()["gst_revenue"] == 2500000

    sig = await client.get(f"/api/v1/applications/{app_id}/signals", headers=h)
    types = {s["signal_type"] for s in sig.json()}
    assert "REVENUE_MISMATCH" in types


@pytest.mark.asyncio
async def test_property_validation_idempotent(client):
    from app.tasks.property import run_property_validation_async

    h = await _register(client, "prop4@example.com")
    app_id = await _new_app(client, h)
    await _upload_run(client, h, app_id, "SALE_DEED", "deed.pdf",
                      "Survey No: 12/4A\nSale Consideration: 5000000\n")
    await _upload_run(client, h, app_id, "VALUATION_REPORT", "val.pdf",
                      "Survey No: 12/4A\nFair Market Value: 9000000\n")
    await run_property_validation_async(app_id, session_factory=_SessionFactory)  # re-run

    async with _SessionFactory() as s:
        live = (
            await s.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == app_id,
                    FraudSignal.signal_scope == SignalScope.PROPERTY,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    inflated = [x for x in live if x.signal_type.value == "INFLATED_VALUATION"]
    assert len(inflated) == 1  # no duplicates after re-run
