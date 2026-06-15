"""OCR pipeline: status transitions, persistence, idempotency, de-dup, failure."""
import pytest
from sqlalchemy import select

from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.ocr_result import OcrResult
from app.services import ocr as ocr_service
from app.services.ocr import OcrError, OcrOutput
from app.tasks.ocr import run_ocr_pipeline_async
from tests.conftest import _SessionFactory

_PDF = b"%PDF-1.4\n%digital pdf with a text layer\n%%EOF"


class FakeEngine:
    name = "fake"

    def __init__(self, text="EMP NAME: ALICE\nNET PAY: 50000", confidence=0.97):
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def run(self, data: bytes, content_type: str) -> OcrOutput:
        self.calls += 1
        return OcrOutput(
            text=self.text, confidence=self.confidence, page_count=1,
            engine=self.name, model_version="t1", pages=[{"page": 1}],
        )


class FailingEngine:
    name = "boom"

    def is_available(self) -> bool:
        return True

    def run(self, data: bytes, content_type: str) -> OcrOutput:
        raise OcrError("synthetic failure")


async def _headers(client, email):
    tokens = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret1", "full_name": "U"},
        )
    ).json()["tokens"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _upload(client, headers, body=_PDF, filename="doc.pdf"):
    app_id = (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
            headers=headers,
        )
    ).json()["id"]
    doc = (
        await client.post(
            f"/api/v1/applications/{app_id}/documents",
            data={"document_type": "SALARY_SLIP"},
            files={"file": (filename, body, "application/pdf")},
            headers=headers,
        )
    ).json()
    return doc["id"]


async def _status(doc_id):
    async with _SessionFactory() as s:
        d = (await s.execute(select(Document).where(Document.id == doc_id))).scalar_one()
        return d.status


@pytest.mark.asyncio
async def test_pipeline_processes_and_persists(client):
    engine = FakeEngine()
    ocr_service.set_engine_override(engine)
    h = await _headers(client, "ocr1@example.com")
    doc_id = await _upload(client, h)
    assert await _status(doc_id) == DocumentStatus.QUEUED

    result = await run_ocr_pipeline_async(
        doc_id, session_factory=_SessionFactory, storage=client.fake_storage
    )
    assert result["status"] == "processed"
    assert await _status(doc_id) == DocumentStatus.PROCESSED

    async with _SessionFactory() as s:
        rows = (await s.execute(select(OcrResult).where(OcrResult.document_id == doc_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].confidence_score == 0.97
    assert "ALICE" in rows[0].raw_text


@pytest.mark.asyncio
async def test_pipeline_is_idempotent(client):
    ocr_service.set_engine_override(FakeEngine())
    h = await _headers(client, "ocr2@example.com")
    doc_id = await _upload(client, h)
    first = await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)
    second = await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)
    assert first["status"] == "processed"
    assert second["status"] == "already_processed"
    async with _SessionFactory() as s:
        rows = (await s.execute(select(OcrResult).where(OcrResult.document_id == doc_id, OcrResult.deleted_at.is_(None)))).scalars().all()
    assert len(rows) == 1  # no duplicate result


@pytest.mark.asyncio
async def test_pipeline_dedups_identical_bytes(client):
    engine = FakeEngine()
    ocr_service.set_engine_override(engine)
    h = await _headers(client, "ocr3@example.com")
    doc1 = await _upload(client, h, body=_PDF, filename="a.pdf")
    doc2 = await _upload(client, h, body=_PDF, filename="b.pdf")  # same bytes → same checksum

    await run_ocr_pipeline_async(doc1, session_factory=_SessionFactory, storage=client.fake_storage)
    await run_ocr_pipeline_async(doc2, session_factory=_SessionFactory, storage=client.fake_storage)

    assert engine.calls == 1  # second document reused the first's OCR text
    async with _SessionFactory() as s:
        r2 = (await s.execute(select(OcrResult).where(OcrResult.document_id == doc2))).scalars().first()
    assert r2 is not None and r2.engine.endswith("+dedup")


@pytest.mark.asyncio
async def test_pipeline_marks_failed_on_engine_error(client):
    ocr_service.set_engine_override(FailingEngine())
    h = await _headers(client, "ocr4@example.com")
    doc_id = await _upload(client, h)
    with pytest.raises(OcrError):
        await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)
    assert await _status(doc_id) == DocumentStatus.FAILED


@pytest.mark.asyncio
async def test_document_detail_exposes_ocr_summary_not_raw_text(client):
    ocr_service.set_engine_override(FakeEngine())
    h = await _headers(client, "ocr5@example.com")
    doc_id = await _upload(client, h)
    await run_ocr_pipeline_async(doc_id, session_factory=_SessionFactory, storage=client.fake_storage)

    r = await client.get(f"/api/v1/documents/{doc_id}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PROCESSED"
    assert body["ocr"]["has_text"] is True
    assert body["ocr"]["confidence_score"] == 0.97
    # Raw OCR text must never appear in the API response.
    assert "raw_text" not in body["ocr"]
    assert "ALICE" not in r.text
