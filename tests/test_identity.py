"""Identity intelligence: resolution logic, synthetic detection, pipeline, endpoint."""
import pytest
from sqlalchemy import select

from app.models.enums import SignalScope
from app.models.fraud_signal import FraudSignal
from app.models.identity_profile import IdentityProfile
from app.services import ocr as ocr_service
from app.services.identity import normalize_name, resolve
from app.services.ocr import OcrOutput
from app.tasks.identity import run_identity_resolution_async
from app.tasks.ocr import run_ocr_pipeline_async
from tests.conftest import _SessionFactory

_PDF = b"%PDF-1.4\n%id\n%%EOF"


# ── Pure resolution logic ──

def test_normalize_name_strips_titles_and_case():
    assert normalize_name("Mr. Bob Kumar") == "BOB KUMAR"
    assert normalize_name("BOB   KUMAR") == "BOB KUMAR"


def test_consistent_identity_no_signals():
    resolved, signals = resolve(
        names=["Bob Kumar", "BOB KUMAR"], pans=["ABCDE1234F"], aadhaars=[], dobs=["01/01/1990"]
    )
    assert signals == []
    assert resolved.is_synthetic_suspected is False
    assert resolved.pan == "ABCDE1234F"
    assert resolved.distinct_name_count == 1


def test_pan_mismatch_flags_synthetic():
    resolved, signals = resolve(
        names=["Bob Kumar"], pans=["ABCDE1234F", "ZZZZZ9999Z"], aadhaars=[], dobs=[]
    )
    types = {s.signal_type for s in signals}
    assert "PAN_MISMATCH_ACROSS_DOCS" in types
    assert "POSSIBLE_SYNTHETIC_IDENTITY" in types
    assert resolved.is_synthetic_suspected is True


def test_name_plus_dob_mismatch_is_synthetic():
    resolved, signals = resolve(
        names=["Bob Kumar", "Alice Singh"], pans=[], aadhaars=[], dobs=["01/01/1990", "02/02/1991"]
    )
    types = {s.signal_type for s in signals}
    assert "NAME_MISMATCH_ACROSS_DOCS" in types
    assert "DOB_MISMATCH_ACROSS_DOCS" in types
    assert resolved.is_synthetic_suspected is True


def test_name_only_mismatch_not_synthetic():
    # A lone name discrepancy is suspicious but not enough to call synthetic.
    resolved, signals = resolve(names=["Bob Kumar", "Bobby Kumar"], pans=["ABCDE1234F"], aadhaars=[], dobs=[])
    assert resolved.is_synthetic_suspected is False
    assert any(s.signal_type == "NAME_MISMATCH_ACROSS_DOCS" for s in signals)


# ── Pipeline + endpoint integration ──

class _Engine:
    name = "fake-id"

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


async def _new_app(client, headers):
    return (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
            headers=headers,
        )
    ).json()["id"]


async def _upload(client, headers, app_id, dtype, filename):
    # Distinct bytes per file so OCR de-dup (by checksum) doesn't reuse another doc's text.
    body = _PDF + f"\n%{filename}".encode()
    return (
        await client.post(
            f"/api/v1/applications/{app_id}/documents",
            data={"document_type": dtype},
            files={"file": (filename, body, "application/pdf")},
            headers=headers,
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_pipeline_resolves_identity_and_flags_pan_mismatch(client):
    h = await _register(client, "id1@example.com")
    app_id = await _new_app(client, h)

    # Two documents on the same application with DIFFERENT PANs → synthetic identity.
    doc1 = await _upload(client, h, app_id, "PAN", "pan1.pdf")
    ocr_service.set_engine_override(_Engine("Name: BOB KUMAR\nPAN: ABCDE1234F\n"))
    await run_ocr_pipeline_async(doc1, session_factory=_SessionFactory, storage=client.fake_storage)

    doc2 = await _upload(client, h, app_id, "SALARY_SLIP", "slip.pdf")
    ocr_service.set_engine_override(_Engine("Employee Name: BOB KUMAR\nPAN: ZZZZZ9999Z\nNet Pay: 40000\n"))
    await run_ocr_pipeline_async(doc2, session_factory=_SessionFactory, storage=client.fake_storage)

    async with _SessionFactory() as s:
        ident_signals = (
            await s.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == app_id,
                    FraudSignal.signal_scope == SignalScope.IDENTITY,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        profile = (
            await s.execute(select(IdentityProfile).where(IdentityProfile.application_id == app_id, IdentityProfile.deleted_at.is_(None)))
        ).scalars().first()

    types = {sig.signal_type.value for sig in ident_signals}
    assert "PAN_MISMATCH_ACROSS_DOCS" in types
    assert "POSSIBLE_SYNTHETIC_IDENTITY" in types
    assert profile is not None and profile.is_synthetic_suspected is True
    assert profile.distinct_pan_count == 2


@pytest.mark.asyncio
async def test_identity_endpoint_masks_pii(client):
    h = await _register(client, "id2@example.com")
    app_id = await _new_app(client, h)
    doc = await _upload(client, h, app_id, "PAN", "pan.pdf")
    ocr_service.set_engine_override(_Engine("Name: BOB KUMAR\nPAN: ABCDE1234F\n"))
    await run_ocr_pipeline_async(doc, session_factory=_SessionFactory, storage=client.fake_storage)

    r = await client.get(f"/api/v1/applications/{app_id}/identity", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["pan_masked"] == "XXXXXE1234F"
    assert "ABCDE1234F" not in r.text  # full PAN never exposed
    assert body["is_synthetic_suspected"] is False


@pytest.mark.asyncio
async def test_identity_resolution_idempotent(client):
    h = await _register(client, "id3@example.com")
    app_id = await _new_app(client, h)
    doc = await _upload(client, h, app_id, "PAN", "pan.pdf")
    ocr_service.set_engine_override(_Engine("Name: BOB KUMAR\nPAN: ABCDE1234F\n"))
    await run_ocr_pipeline_async(doc, session_factory=_SessionFactory, storage=client.fake_storage)
    await run_identity_resolution_async(app_id, session_factory=_SessionFactory)  # re-run

    async with _SessionFactory() as s:
        profiles = (
            await s.execute(select(IdentityProfile).where(IdentityProfile.application_id == app_id, IdentityProfile.deleted_at.is_(None)))
        ).scalars().all()
    assert len(profiles) == 1  # single live profile after re-run
