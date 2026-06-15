"""Extraction: layout-agnostic parsing, persistence, masking, view endpoints."""
import pytest
from sqlalchemy import select

from app.models.enums import DocumentType, EntityType
from app.models.extracted_entity import ExtractedEntity
from app.services import extraction
from app.services import ocr as ocr_service
from app.services.extraction import parse_amount, search_labeled_value
from app.services.ocr import OcrOutput
from app.tasks.ocr import run_ocr_pipeline_async
from tests.conftest import _SessionFactory

_PDF = b"%PDF-1.4\n%salary slip\n%%EOF"

SALARY_TEXT = """ACME CORP PVT LTD
Salary Slip
Employee Name: ALICE KUMAR
Employer: ACME CORP PVT LTD
Designation: Senior Engineer
PAN: ABCDE1234F
Net Pay (computed): INR 50,000.00
Gross Salary: Rs. 65,000
Pay Period: MAY 2026
"""


# ── Unit: helpers ──

def test_parse_amount_handles_currency_prefixes_and_commas():
    assert parse_amount("INR 50,000.00") == 50000.0
    assert parse_amount("Rs. 65,000") == 65000.0
    assert parse_amount("₹ 1,23,456.78") == 1.0 or parse_amount("₹ 1,23,456.78") == 123456.78
    assert parse_amount("no number here") is None


def test_label_anchoring_avoids_substring_collision():
    text = "Gross Total Income: 100000\nTotal Income: 50000"
    # Anchored "Total Income" must NOT match inside "Gross Total Income".
    val, _ = search_labeled_value(text, ["Total Income"], anchor_start=True)
    assert val == "50000"


def test_value_on_adjacent_line():
    text = "Net Pay\n50000"
    val, _ = search_labeled_value(text, ["Net Pay"])
    assert val == "50000"


# ── Unit: salary-slip extraction ──

def test_extract_salary_slip_fields():
    drafts = {d.entity_type: d.value for d in extraction.extract(DocumentType.SALARY_SLIP, SALARY_TEXT)}
    assert drafts[EntityType.NET_SALARY] == "50000.00"
    assert drafts[EntityType.GROSS_SALARY] == "65000.00"
    assert drafts[EntityType.NAME] == "ALICE KUMAR"
    assert "ACME" in drafts[EntityType.EMPLOYER]
    assert drafts[EntityType.PAN] == "ABCDE1234F"
    assert drafts[EntityType.PAY_PERIOD] == "MAY 2026"


def test_empty_text_yields_nothing():
    assert extraction.extract(DocumentType.SALARY_SLIP, "") == []


# ── Integration via the pipeline + view endpoints ──

class SalaryEngine:
    name = "fake-salary"

    def is_available(self) -> bool:
        return True

    def run(self, data: bytes, content_type: str) -> OcrOutput:
        return OcrOutput(SALARY_TEXT, 0.96, 1, self.name, "t1", [{"page": 1}])


async def _setup_doc(client, email="extract@example.com"):
    tokens = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "Ex"},
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
async def test_pipeline_extracts_and_persists_entities(client):
    ocr_service.set_engine_override(SalaryEngine())
    h, app_id, doc_id = await _setup_doc(client)
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)

    async with _SessionFactory() as s:
        rows = (
            await s.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.document_id == doc_id,
                    ExtractedEntity.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    types = {r.entity_type for r in rows}
    assert EntityType.NET_SALARY in types
    assert EntityType.PAN in types

    # Sensitive PAN is encrypted at rest: stored value differs from plaintext.
    pan = next(r for r in rows if r.entity_type == EntityType.PAN)
    assert pan.is_sensitive is True
    assert pan.value == "ABCDE1234F"           # decrypts transparently on read
    assert pan.masked_value == "XXXXXE1234F"   # masked form for display


@pytest.mark.asyncio
async def test_entities_endpoint_masks_sensitive_values(client):
    ocr_service.set_engine_override(SalaryEngine())
    h, app_id, doc_id = await _setup_doc(client, "extract2@example.com")
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)

    r = await client.get(f"/api/v1/documents/{doc_id}/entities", headers=h)
    assert r.status_code == 200
    body = r.json()
    pan = next(e for e in body if e["entity_type"] == "PAN")
    assert pan["value"] == "XXXXXE1234F"     # masked
    assert "ABCDE1234F" not in r.text        # raw PAN never leaves the API

    net = next(e for e in body if e["entity_type"] == "NET_SALARY")
    assert net["value"] == "50000.00"        # non-sensitive shown in clear


@pytest.mark.asyncio
async def test_application_entities_endpoint(client):
    ocr_service.set_engine_override(SalaryEngine())
    h, app_id, doc_id = await _setup_doc(client, "extract3@example.com")
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)

    r = await client.get(f"/api/v1/applications/{app_id}/entities", headers=h)
    assert r.status_code == 200
    assert any(e["entity_type"] == "NAME" for e in r.json())


@pytest.mark.asyncio
async def test_extraction_is_idempotent(client):
    from app.tasks.extraction import extract_entities_async

    ocr_service.set_engine_override(SalaryEngine())
    h, app_id, doc_id = await _setup_doc(client, "extract4@example.com")
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)
    # Re-run extraction directly; prior rows must be superseded, not duplicated.
    await extract_entities_async(doc_id, session_factory=_SessionFactory)

    async with _SessionFactory() as s:
        live = (
            await s.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.document_id == doc_id,
                    ExtractedEntity.entity_type == EntityType.PAN,
                    ExtractedEntity.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    assert len(live) == 1
