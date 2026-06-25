"""
INTEGRATION REFERENCE (not drop-in as-is) — shows how the forensics package
slots into TrustLens. Adapt names to your actual repositories / models / scorer.

Three things to wire:
  1. A HashStore backed by a new `document_fingerprints` table (for cross-app reuse).
  2. A Celery task `run_document_forensics`, chained after `extract_entities`.
  3. Folding ForensicResult into the deterministic risk assessment as ONE
     signal-group, and pushing reuse hits into the entity graph.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# 1) HashStore backed by your repositories layer
# ─────────────────────────────────────────────────────────────────────────────
class RepoHashStore:
    """Implements forensics.HashStore over a `document_fingerprints` table:

        id | document_id | application_id | phash_hex | extra(jsonb) | created_at

    find_similar uses a bounded scan; for large volumes precompute on an index
    of pHash prefixes or use a BK-tree. Stays fully local/offline either way.
    """
    def __init__(self, repo):
        self.repo = repo

    def find_similar(self, phash_hex: str, max_distance: int) -> list[dict]:
        target = int(phash_hex, 16)
        rows = self.repo.all_fingerprints()          # -> list[dict] with phash_hex
        hits = []
        for r in rows:
            if bin(target ^ int(r["phash_hex"], 16)).count("1") <= max_distance:
                hits.append(r)
        return hits

    def save(self, *, document_id, application_id, phash_hex, extra=None) -> None:
        self.repo.insert_fingerprint(
            document_id=document_id, application_id=application_id,
            phash_hex=phash_hex, extra=extra or {},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2) Celery task — chain it after extract_entities, before run_fraud_engine
#    (or in parallel; forensic signals merge at compute_risk_assessment).
# ─────────────────────────────────────────────────────────────────────────────
"""
# app/tasks/forensics.py
import fitz
from app.worker import celery_app
from app.forensics import run_forensics

@celery_app.task(name="run_document_forensics", bind=True, max_retries=3)
def run_document_forensics(self, document_id: str):
    doc      = document_repo.get(document_id)            # your repo
    raw      = storage_service.get_bytes(doc.storage_key) # MinIO/S3
    fitz_doc = fitz.open(stream=raw, filetype="pdf") if doc.is_pdf else None
    store    = RepoHashStore(fingerprint_repo)

    # optional: pass OCR text-dict / pre-extracted signature crops via context
    result = run_forensics(
        document_id=document_id, application_id=doc.application_id,
        filename=doc.filename, mime=doc.mime, raw_bytes=raw,
        hash_store=store, fitz_doc=fitz_doc,
        context={...},
    )

    for s in result.signals:
        fraud_signal_repo.upsert(                         # idempotent on (doc, code, page)
            application_id=doc.application_id, document_id=document_id,
            code=s.code, title=s.title, severity=s.severity.value,
            weight=s.effective_weight, reasons=s.reasons,
            evidence=s.evidence, source="FORENSICS",
        )
        # cross-application reuse is a graph edge, not just a signal:
        if s.code == "FORENSIC_DOCUMENT_REUSED_ACROSS_APPS":
            for app_id in s.evidence.get("linked_application_ids", []):
                graph_service.add_shared_document_edge(doc.application_id, app_id,
                                                       document_id)
    audit_service.record("FORENSICS_COMPLETED", application_id=doc.application_id,
                         document_id=document_id,
                         correlation_id=self.request.id)
    return {"signals": len(result.signals), "subscore": result.forensics_subscore,
            "skipped": result.skipped, "errors": result.errors}
"""


# ─────────────────────────────────────────────────────────────────────────────
# 3) Feeding the deterministic scorer
# ─────────────────────────────────────────────────────────────────────────────
"""
In compute_risk_assessment, treat forensics as ONE weighted signal-group so a
swarm of weak hits can't dominate. Two safe policies:

  • Cap forensics' contribution to the 0-100 score (e.g. max 25 points), using
    ForensicResult.forensics_subscore (already squashed + confidence-weighted).

  • Allow ONLY these STRONG codes to independently escalate tier to >= HIGH:
        FORENSIC_DOCUMENT_REUSED_ACROSS_APPS
        FORENSIC_METADATA_IMPOSSIBLE_TIMELINE
        FORENSIC_METADATA_EDIT_SOFTWARE
        FORENSIC_FONT_OUTLIER
        FORENSIC_SIGNATURE_COPY_PASTE
    Everything else stays analyst-attention-only. This keeps SUGGESTIVE
    techniques (ELA, noise) from ever causing an automated denial — important
    for DPDP/RBI explainability and for not wrongly rejecting real applicants.

Every signal already carries `reasons` + PII-safe `evidence`, so it drops
straight into your per-signal reasons breakdown and WORM audit trail.
"""
