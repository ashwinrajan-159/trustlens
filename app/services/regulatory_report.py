"""Regulatory Explainability Report — per-application auditable PDF.

This service produces the artifact that makes TrustLens's core promise concrete:
*"explains every decision in a form a regulator and analyst can audit."* It performs
**no new analysis** — it reassembles data already produced by the pipeline (the
deterministic scorer's `reasons` breakdown, fraud signals, masked extracted fields,
RBI classification, and the WORM audit hash-chain) into a single, reproducible PDF.

Design constraints honoured:
  * **Offline / air-gapped** — rendered locally with reportlab (pure Python). No cloud,
    no external AI, no network.
  * **PII-safe** — sensitive identifiers are shown only in masked form; full values stay
    in the encrypted store. The audit attestation references the source rows.
  * **Reproducible** — the report stamps `engine_version` + `weight_config_version` so the
    score can be recomputed with the exact weights in force at assessment time.
  * **Tamper-evident** — embeds this application's audit entries and the live audit
    chain-head hash as an integrity anchor.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.enums import UserRole
from app.models.extracted_entity import ExtractedEntity
from app.models.user import User
from app.services.application import ApplicationService
from app.services import rbi


_SEV_COLORS = {
    "CRITICAL": "#b91c1c",
    "HIGH": "#c2410c",
    "MEDIUM": "#a16207",
    "LOW": "#1d4ed8",
}


class RegulatoryReportService:
    """Assembles and renders the per-application regulatory explainability PDF."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.apps = ApplicationService(session)

    # ── public API ────────────────────────────────────────────────────────────

    async def build_pdf(self, app_id: str, *, user_id: str, role: UserRole) -> tuple[bytes, str]:
        """Return ``(pdf_bytes, filename)``. Authorization is enforced via
        ``ApplicationService.get_for_user`` inside ``_assemble``."""
        data = await self._assemble(app_id, user_id=user_id, role=role)
        pdf = _render_pdf(data)
        filename = f"{data['application']['number']}-regulatory-report.pdf"
        return pdf, filename

    # ── data assembly (reuses existing authorized getters) ──────────────────────

    async def _assemble(self, app_id: str, *, user_id: str, role: UserRole) -> dict:
        app: Application = await self.apps.get_for_user(app_id, user_id=user_id, role=role)
        risk = await self.apps.get_risk(app_id, user_id=user_id, role=role)
        signals = await self.apps.list_signals(app_id, user_id=user_id, role=role)

        applicant = (
            await self.session.execute(select(User).where(User.id == app.applicant_id))
        ).scalars().first()

        documents = (
            await self.session.execute(
                select(Document).where(
                    Document.application_id == app_id,
                    Document.deleted_at.is_(None),
                    Document.is_current_version.is_(True),
                ).order_by(Document.created_at.asc())
            )
        ).scalars().all()

        entities = (
            await self.session.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.application_id == app_id,
                    ExtractedEntity.deleted_at.is_(None),
                ).order_by(ExtractedEntity.entity_type.asc())
            )
        ).scalars().all()

        # RBI / FMR classification by loan exposure.
        amount = float(app.loan_amount_requested or 0)
        rbi_cls = rbi.classify(amount)

        # Audit attestation: this application's recorded actions + the live chain head.
        audit_entries = (
            await self.session.execute(
                select(AuditLog).where(AuditLog.entity_id == app_id)
                .order_by(AuditLog.created_at.asc())
            )
        ).scalars().all()
        chain_head = (
            await self.session.execute(
                select(AuditLog.entry_hash)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(1)
            )
        ).scalars().first()

        return {
            "generated_at": datetime.now(timezone.utc),
            "application": {
                "number": app.application_number,
                "applicant_name": getattr(applicant, "full_name", None) or "—",
                "loan_type": _val(app.loan_type),
                "loan_amount": amount,
                "status": _val(app.status),
                "decision_at": app.decision_at,
                "decision_by": app.decision_by,
                "decision_reason": app.decision_reason,
            },
            "risk": {
                "score": getattr(risk, "total_score", None),
                "tier": _val(getattr(risk, "risk_tier", None)),
                "by_category": getattr(risk, "by_category", None) or {},
                "reasons": getattr(risk, "reasons", None) or [],
                "engine_version": getattr(risk, "engine_version", None),
                "weight_config_version": getattr(risk, "weight_config_version", None),
                "assessed_at": getattr(risk, "created_at", None),
            },
            "signals": [
                {
                    "type": _val(s.signal_type),
                    "severity": _val(s.severity),
                    "scope": _val(s.signal_scope),
                    "rule_name": s.rule_name,
                    "description": s.description,
                    "confidence": s.confidence,
                    "evidence": s.evidence or {},
                    "source_documents": s.source_document_ids or [],
                    "is_confirmed": s.is_confirmed,
                }
                for s in signals
            ],
            "documents": [
                {
                    "type": _val(d.document_type),
                    "filename": d.original_filename,
                    "status": _val(d.status),
                    "uploaded_at": d.created_at,
                }
                for d in documents
            ],
            "entities": [
                {
                    "type": _val(e.entity_type),
                    # PII-safe: sensitive values shown only masked.
                    "value": (e.masked_value if e.is_sensitive else e.value) or "—",
                    "sensitive": bool(e.is_sensitive),
                    "confidence": e.confidence,
                }
                for e in entities
            ],
            "rbi": {
                "required": rbi_cls.required,
                "report_type": _val(rbi_cls.report_type),
                "deadline_hours": rbi_cls.deadline_hours,
            },
            "audit": {
                "entries": [
                    {
                        "action": _val(a.action),
                        "actor_id": a.actor_id,
                        "at": a.created_at,
                        "entry_hash": a.entry_hash,
                        "prev_hash": a.prev_hash,
                    }
                    for a in audit_entries
                ],
                "chain_head": chain_head,
            },
        }


def _val(x):
    """Enum-or-scalar → display string."""
    if x is None:
        return None
    return getattr(x, "value", x)


# ── PDF rendering (pure, synchronous) ───────────────────────────────────────────

def _render_pdf(d: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
        title=f"Regulatory Explainability Report — {d['application']['number']}",
        author="TrustLens AI",
    )
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#0f172a"))
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("small", parent=ss["BodyText"], fontSize=7, leading=9,
                           textColor=colors.HexColor("#475569"))
    cell = ParagraphStyle("cell", parent=ss["BodyText"], fontSize=7.5, leading=9.5)

    flow = []

    def section(title):
        flow.append(Paragraph(title, h2))
        flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"),
                               spaceAfter=4))

    def kv_table(rows):
        t = Table([[Paragraph(f"<b>{k}</b>", cell), Paragraph(str(v), cell)] for k, v in rows],
                  colWidths=[45 * mm, 130 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return t

    app = d["application"]
    risk = d["risk"]

    # ── Title ────────────────────────────────────────────────────────────────
    flow.append(Paragraph("Regulatory Explainability Report", h1))
    flow.append(Paragraph(
        "TrustLens AI — deterministic, auditable fraud-risk decision record. "
        "Generated locally; no external AI was used.", small))
    flow.append(Spacer(1, 8))

    # ── Application & decision ─────────────────────────────────────────────────
    section("Application &amp; Decision")
    flow.append(kv_table([
        ("Application No.", app["number"]),
        ("Applicant", app["applicant_name"]),
        ("Loan", f"{app['loan_type']} · ₹{app['loan_amount']:,.0f}"),
        ("Status", app["status"]),
        ("Decision", f"{app.get('decision_reason') or '—'}"
                     + (f" (by {app['decision_by']}, {_fmt(app['decision_at'])})" if app.get("decision_by") else "")),
        ("Report generated", _fmt(d["generated_at"])),
        ("Engine version", risk["engine_version"] or "—"),
        ("Weight config version", risk["weight_config_version"] if risk["weight_config_version"] is not None else "built-in defaults"),
    ]))
    flow.append(Spacer(1, 6))

    # ── Risk summary ───────────────────────────────────────────────────────────
    section("Risk Assessment")
    if risk["score"] is None:
        flow.append(Paragraph("No risk assessment has been computed for this application yet.", body))
    else:
        tier = risk["tier"] or "—"
        tcol = _SEV_COLORS.get(tier, "#1d4ed8")
        flow.append(Paragraph(
            f"<b>Total risk score:</b> {risk['score']:.0f}/100 &nbsp;&nbsp; "
            f"<b>Tier:</b> <font color='{tcol}'>{tier}</font> &nbsp;&nbsp; "
            f"<b>Assessed:</b> {_fmt(risk['assessed_at'])}", body))
        cats = risk["by_category"]
        if cats:
            crows = [[Paragraph("<b>Category</b>", cell), Paragraph("<b>Weight contribution</b>", cell)]]
            for k, v in sorted(cats.items(), key=lambda kv: -float(kv[1] or 0)):
                crows.append([Paragraph(str(k), cell), Paragraph(f"{float(v):.1f}", cell)])
            ct = Table(crows, colWidths=[60 * mm, 60 * mm])
            ct.setStyle(_grid())
            flow.append(Spacer(1, 4)); flow.append(ct)

    # ── Decision reasons (the spine) ───────────────────────────────────────────
    section("Decision Reasons — Per-Signal Score Breakdown")
    reasons = risk["reasons"]
    if not reasons:
        flow.append(Paragraph("No scored signals.", body))
    else:
        header = ["Signal", "Severity", "Category", "Weight", "Source", "Conf.", "Why"]
        rows = [[Paragraph(f"<b>{h}</b>", cell) for h in header]]
        for r in reasons:
            sev = r.get("severity", "")
            rows.append([
                Paragraph(str(r.get("signal_type", "")), cell),
                Paragraph(f"<font color='{_SEV_COLORS.get(sev, '#334155')}'>{sev}</font>", cell),
                Paragraph(str(r.get("category", "")), cell),
                Paragraph(f"{float(r.get('weight', 0)):.1f}", cell),
                Paragraph(str(r.get("weight_source", "")).replace("_", " "), cell),
                Paragraph(f"{float(r.get('confidence', 0)):.2f}", cell),
                Paragraph(str(r.get("description", "")), cell),
            ])
        t = Table(rows, colWidths=[28*mm, 16*mm, 18*mm, 12*mm, 20*mm, 11*mm, 73*mm], repeatRows=1)
        t.setStyle(_grid())
        flow.append(t)
        flow.append(Paragraph(
            "Weight source 'governed' = an approved SignalWeightConfig override; "
            "'severity default' = the standard severity weight. The total above is reproducible "
            "from the engine + weight-config versions recorded in this report.", small))

    # ── Fraud signals detail ───────────────────────────────────────────────────
    section("Fraud Signals — Evidence")
    if not d["signals"]:
        flow.append(Paragraph("No fraud signals were raised.", body))
    else:
        for s in d["signals"]:
            ev = ", ".join(f"{k}={v}" for k, v in s["evidence"].items()) if s["evidence"] else "—"
            conf = "  ·  <b>confirmed by analyst</b>" if s["is_confirmed"] else ""
            flow.append(Paragraph(
                f"<b>{s['type']}</b> "
                f"<font color='{_SEV_COLORS.get(s['severity'], '#334155')}'>[{s['severity']}]</font> "
                f"<font color='#64748b'>({s['scope']}, conf {float(s['confidence']):.2f})</font>{conf}", body))
            flow.append(Paragraph(s["description"] or "", small))
            flow.append(Paragraph(f"<i>Evidence:</i> {ev}", small))
            flow.append(Spacer(1, 3))

    # ── Documents & extracted fields ───────────────────────────────────────────
    section("Documents &amp; Extracted Fields (masked)")
    if d["documents"]:
        drows = [[Paragraph(f"<b>{h}</b>", cell) for h in ("Type", "File", "Status", "Uploaded")]]
        for x in d["documents"]:
            drows.append([Paragraph(str(x["type"]), cell), Paragraph(str(x["filename"]), cell),
                          Paragraph(str(x["status"]), cell), Paragraph(_fmt(x["uploaded_at"]), cell)])
        dt = Table(drows, colWidths=[34*mm, 70*mm, 26*mm, 48*mm], repeatRows=1)
        dt.setStyle(_grid()); flow.append(dt); flow.append(Spacer(1, 4))
    if d["entities"]:
        erows = [[Paragraph(f"<b>{h}</b>", cell) for h in ("Field", "Value", "Sensitive", "Conf.")]]
        for e in d["entities"]:
            erows.append([Paragraph(str(e["type"]), cell), Paragraph(str(e["value"]), cell),
                          Paragraph("yes" if e["sensitive"] else "no", cell),
                          Paragraph(f"{float(e['confidence'] or 0):.2f}", cell)])
        et = Table(erows, colWidths=[40*mm, 90*mm, 24*mm, 24*mm], repeatRows=1)
        et.setStyle(_grid()); flow.append(et)

    # ── RBI classification ─────────────────────────────────────────────────────
    section("RBI / FMR Classification")
    rb = d["rbi"]
    if rb["required"]:
        dl = f"{rb['deadline_hours']}h" if rb["deadline_hours"] else "quarterly batch return"
        flow.append(Paragraph(
            f"This exposure requires an RBI report: <b>{rb['report_type']}</b> "
            f"(reporting window: {dl}).", body))
    else:
        flow.append(Paragraph("Exposure below RBI fraud-reporting thresholds; no FMR filing triggered.", body))

    # ── Audit attestation ──────────────────────────────────────────────────────
    section("Audit Attestation (tamper-evident)")
    au = d["audit"]
    flow.append(Paragraph(
        "Every state change on this application is recorded in an append-only (WORM) audit log "
        "secured by a SHA-256 hash chain. The current chain-head hash anchors the entire log; "
        "any retroactive edit would break the chain.", small))
    flow.append(Paragraph(f"<b>Audit chain head:</b> <font face='Courier'>{(au['chain_head'] or '—')[:32]}…</font>", small))
    if au["entries"]:
        arows = [[Paragraph(f"<b>{h}</b>", cell) for h in ("When", "Action", "Actor", "Entry hash")]]
        for a in au["entries"]:
            arows.append([Paragraph(_fmt(a["at"]), cell), Paragraph(str(a["action"]), cell),
                          Paragraph(str(a["actor_id"] or "system"), cell),
                          Paragraph(f"<font face='Courier'>{(a['entry_hash'] or '')[:16]}…</font>", cell)])
        at = Table(arows, colWidths=[44*mm, 34*mm, 50*mm, 50*mm], repeatRows=1)
        at.setStyle(_grid()); flow.append(Spacer(1, 4)); flow.append(at)

    # ── Methodology footer ─────────────────────────────────────────────────────
    flow.append(Spacer(1, 8))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
    flow.append(Paragraph(
        "<b>Methodology.</b> Risk is computed by a deterministic, rule-based engine (the system of "
        "record); machine-learning and document-forensics layers are advisory only and never solely "
        "decide a case. Each signal contributes a weight by severity (LOW 5 · MEDIUM 15 · HIGH 30 · "
        "CRITICAL 50) unless overridden by an approved, version-controlled weight configuration. "
        "Sensitive identifiers are masked in this report; full values remain encrypted at rest. "
        "This document was generated offline with no external AI or network calls.", small))

    doc.build(flow)
    return buf.getvalue()


def _grid():
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ])


def _fmt(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(dt)
