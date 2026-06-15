"""Cross-document validation: completeness checklist + income reconciliation."""
import pytest
from sqlalchemy import select

from app.models.enums import FraudSignalType, SignalScope
from app.models.fraud_signal import FraudSignal
from app.services import ocr as ocr_service
from app.services.cross_document import CrossDocContext, compute_completeness, validate
from app.services.ocr import OcrOutput
from app.tasks.ocr import run_ocr_pipeline_async
from tests.conftest import _SessionFactory

# ── Pure completeness logic ──

def test_home_loan_missing_core_docs():
    missing_critical, missing_recommended = compute_completeness("HOME", {"PAN"})
    assert "AADHAAR" in missing_critical
    assert "SALE_DEED" in missing_critical
    assert "INCOME_PROOF" in missing_critical  # no income doc present
    assert "FORM_16" in missing_recommended


def test_home_loan_complete_when_all_present():
    present = {"PAN", "AADHAAR", "BANK_STATEMENT", "SALE_DEED", "VALUATION_REPORT", "SALARY_SLIP"}
    missing_critical, _ = compute_completeness("HOME", present)
    assert missing_critical == []


# ── Pure reconciliation logic ──

def test_salary_bank_mismatch():
    ctx = CrossDocContext(
        loan_type="HOME",
        present_doc_types={"SALARY_SLIP", "BANK_STATEMENT", "PAN", "AADHAAR", "SALE_DEED", "VALUATION_REPORT"},
        net_salaries=[50000.0],
        salary_credits=[30000.0],  # >10% below payslip
    )
    types = {s.signal_type for s in validate(ctx)}
    assert "SALARY_BANK_MISMATCH" in types


def test_employer_deposit_not_found():
    ctx = CrossDocContext(
        loan_type="PERSONAL",
        present_doc_types={"SALARY_SLIP", "BANK_STATEMENT", "PAN", "AADHAAR"},
        net_salaries=[50000.0],
        salary_credits=[],  # bank present but no salary credit detected
    )
    types = {s.signal_type for s in validate(ctx)}
    assert "EMPLOYER_DEPOSIT_NOT_FOUND" in types


def test_matching_salary_no_income_signal():
    ctx = CrossDocContext(
        loan_type="PERSONAL",
        present_doc_types={"SALARY_SLIP", "BANK_STATEMENT", "PAN", "AADHAAR"},
        net_salaries=[50000.0],
        salary_credits=[49500.0],  # within 10% tolerance
    )
    types = {s.signal_type for s in validate(ctx)}
    assert "SALARY_BANK_MISMATCH" not in types
    assert "EMPLOYER_DEPOSIT_NOT_FOUND" not in types


# ── Pipeline + endpoint integration ──

_PDF = b"%PDF-1.4\n%x\n%%EOF"


class _Engine:
    name = "fake-x"

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


async def _upload_and_run(client, h, app_id, dtype, filename, text):
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
async def test_completeness_endpoint_reflects_uploads(client):
    h = await _register(client, "xdoc1@example.com")
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
            headers=h,
        )
    ).json()["id"]

    # Nothing processed yet → many missing.
    r0 = await client.get(f"/api/v1/applications/{app_id}/completeness", headers=h)
    assert r0.status_code == 200
    assert r0.json()["is_complete"] is False
    assert "PAN" in r0.json()["missing_critical"]

    await _upload_and_run(client, h, app_id, "PAN", "pan.pdf", "PAN: ABCDE1234F\n")
    r1 = await client.get(f"/api/v1/applications/{app_id}/completeness", headers=h)
    assert "PAN" in r1.json()["present"]
    assert "PAN" not in r1.json()["missing_critical"]


@pytest.mark.asyncio
async def test_pipeline_flags_salary_bank_mismatch(client):
    h = await _register(client, "xdoc2@example.com")
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "PERSONAL", "loan_amount_requested": "200000"},
            headers=h,
        )
    ).json()["id"]

    await _upload_and_run(client, h, app_id, "SALARY_SLIP", "slip.pdf",
                          "Employee Name: BOB\nNet Pay: 50000\nGross Salary: 60000\n")
    # Bank statement shows a much smaller salary credit → mismatch.
    await _upload_and_run(client, h, app_id, "BANK_STATEMENT", "bank.pdf",
                          "Account Number: 123456789012\n01/05 NEFT SALARY CREDIT 30000\n")

    sig = await client.get(f"/api/v1/applications/{app_id}/signals", headers=h)
    types = {s["signal_type"] for s in sig.json()}
    assert "SALARY_BANK_MISMATCH" in types
    # Cross-document scope is recorded.
    assert any(s["signal_scope"] == "CROSS_DOCUMENT" for s in sig.json())


@pytest.mark.asyncio
async def test_cross_doc_signals_idempotent(client):
    from app.tasks.cross_document import run_cross_document_validation_async

    h = await _register(client, "xdoc3@example.com")
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
            headers=h,
        )
    ).json()["id"]
    await _upload_and_run(client, h, app_id, "PAN", "pan.pdf", "PAN: ABCDE1234F\n")
    await run_cross_document_validation_async(app_id, session_factory=_SessionFactory)  # re-run

    async with _SessionFactory() as s:
        live = (
            await s.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == app_id,
                    FraudSignal.signal_scope == SignalScope.CROSS_DOCUMENT,
                    FraudSignal.signal_type == FraudSignalType.MISSING_CRITICAL_DOCUMENT,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    assert len(live) == 1  # single live completeness signal after re-run
