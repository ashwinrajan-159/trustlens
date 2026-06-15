"""Graph intelligence: pure build/analyze, ring detection, pipeline, endpoints."""
import pytest
from sqlalchemy import select

from app.models.enums import SignalScope
from app.models.fraud_signal import FraudSignal
from app.services import graph_intel as gi
from app.services import ocr as ocr_service
from app.services.ocr import OcrOutput
from app.tasks.ocr import run_ocr_pipeline_async
from tests.conftest import _SessionFactory

# ── Pure graph logic ──

def test_shared_pan_links_applications():
    g = gi.build_graph([
        gi.AppRecord(application_id="A", pans=["ABCDE1234F"]),
        gi.AppRecord(application_id="B", pans=["ABCDE1234F"]),
    ])
    summary, signals = gi.analyze(g, "A")
    types = {s.signal_type for s in signals}
    assert "SHARED_PAN_MULTIPLE_APPLICATIONS" in types
    assert summary.shared_pan_count == 1
    assert "B" in summary.connected_application_ids


def test_mule_account_and_property_network():
    g = gi.build_graph([
        gi.AppRecord(application_id="A", accounts=["111222333"], surveys=["12/4A"]),
        gi.AppRecord(application_id="B", accounts=["111222333"]),
        gi.AppRecord(application_id="C", surveys=["12/4A"]),
    ])
    _, signals = gi.analyze(g, "A")
    types = {s.signal_type for s in signals}
    assert "MULE_ACCOUNT_REUSE" in types
    assert "DUPLICATE_COLLATERAL_NETWORK" in types


def test_fraud_ring_detected():
    # Three applications transitively linked through shared strong attributes.
    g = gi.build_graph([
        gi.AppRecord(application_id="A", pans=["AAAAA1111A"], accounts=["acct1"]),
        gi.AppRecord(application_id="B", accounts=["acct1"], aadhaars=["234123412346"]),
        gi.AppRecord(application_id="C", aadhaars=["234123412346"]),
    ])
    summary, signals = gi.analyze(g, "A")
    assert summary.in_fraud_ring is True
    assert summary.ring_size == 3
    assert any(s.signal_type == "FRAUD_RING_DETECTED" for s in signals)


def test_isolated_application_no_signals():
    g = gi.build_graph([
        gi.AppRecord(application_id="A", pans=["ABCDE1234F"], names=["bob kumar"]),
    ])
    summary, signals = gi.analyze(g, "A")
    assert signals == []
    assert summary.fraud_connections_count == 0
    assert summary.in_fraud_ring is False


def test_ego_network_masks_pii():
    g = gi.build_graph([
        gi.AppRecord(application_id="A", pans=["ABCDE1234F"], accounts=["000111222333"]),
    ])
    net = gi.ego_network(g, "A")
    labels = " ".join(n["label"] for n in net["nodes"])
    assert "ABCDE1234F" not in labels      # PAN masked
    assert "XXXXXE1234F" in labels
    assert "000111222333" not in labels    # account masked


# ── Pipeline + endpoint integration ──

_PDF = b"%PDF-1.4\n%g\n%%EOF"


class _Engine:
    name = "fake-g"

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


async def _new_app(client, h):
    return (
        await client.post(
            "/api/v1/applications",
            json={"loan_type": "HOME", "loan_amount_requested": "5000000"},
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
async def test_pipeline_flags_shared_pan_network(client):
    h = await _register(client, "graph1@example.com")
    # Two applications by the same customer carrying the SAME PAN.
    app1 = await _new_app(client, h)
    await _upload_run(client, h, app1, "PAN", "p1.pdf", "PAN: ABCDE1234F\n")
    app2 = await _new_app(client, h)
    await _upload_run(client, h, app2, "PAN", "p2.pdf", "PAN: ABCDE1234F\n")

    g = await client.get(f"/api/v1/applications/{app2}/graph", headers=h)
    assert g.status_code == 200
    body = g.json()
    assert body["shared_pan_count"] >= 1
    assert app1 in body["connected_application_ids"]

    sig = await client.get(f"/api/v1/applications/{app2}/signals", headers=h)
    types = {s["signal_type"] for s in sig.json()}
    assert "SHARED_PAN_MULTIPLE_APPLICATIONS" in types
    assert any(s["signal_scope"] == "GRAPH" for s in sig.json())


@pytest.mark.asyncio
async def test_network_endpoint_returns_masked_graph(client):
    h = await _register(client, "graph2@example.com")
    app_id = await _new_app(client, h)
    await _upload_run(client, h, app_id, "PAN", "p.pdf", "PAN: ABCDE1234F\n")

    r = await client.get(f"/api/v1/applications/{app_id}/network", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert any(n["kind"] == "APP" for n in body["nodes"])
    assert any(n["kind"] == "PAN" for n in body["nodes"])
    assert "ABCDE1234F" not in r.text  # raw PAN never in the network view


@pytest.mark.asyncio
async def test_graph_analysis_idempotent(client):
    from app.tasks.graph import run_graph_analysis_async

    h = await _register(client, "graph3@example.com")
    app_id = await _new_app(client, h)
    await _upload_run(client, h, app_id, "PAN", "p.pdf", "PAN: ABCDE1234F\n")
    await run_graph_analysis_async(app_id, session_factory=_SessionFactory)  # re-run

    async with _SessionFactory() as s:
        from app.models.graph_analysis import GraphAnalysis

        analyses = (
            await s.execute(
                select(GraphAnalysis).where(
                    GraphAnalysis.application_id == app_id,
                    GraphAnalysis.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        graph_sigs = (
            await s.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == app_id,
                    FraudSignal.signal_scope == SignalScope.GRAPH,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    assert len(analyses) == 1            # single live analysis after re-run
    assert len(graph_sigs) == 0          # isolated app → no graph signals
