"""RBI Fraud Management reporting thresholds (Phase 10). Pure logic.

Classifies a loan exposure into the RBI reporting tier and its deadline:
- ≥ ₹25 Cr  → FLASH report within 24 hours
- ≥ ₹1 Cr   → FMR-1 within 7 days
- ≥ ₹1 Lakh → quarterly return
- otherwise → no RBI report required

Also builds an FMR-shaped report dict (IDs + amounts only — no PII).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import RBIReportType

CR = 10_000_000        # 1 crore
LAKH = 100_000         # 1 lakh
FLASH_THRESHOLD = 25 * CR
FMR1_THRESHOLD = 1 * CR
QUARTERLY_THRESHOLD = 1 * LAKH


@dataclass
class RBIClassification:
    required: bool
    report_type: RBIReportType
    deadline_hours: int | None  # None for quarterly (batch return)


def classify(amount: float) -> RBIClassification:
    if amount >= FLASH_THRESHOLD:
        return RBIClassification(True, RBIReportType.FLASH, 24)
    if amount >= FMR1_THRESHOLD:
        return RBIClassification(True, RBIReportType.FMR_1, 24 * 7)
    if amount >= QUARTERLY_THRESHOLD:
        return RBIClassification(True, RBIReportType.QUARTERLY, 24 * 90)
    return RBIClassification(False, RBIReportType.NONE, None)


def build_fmr_report(*, alert_number: str, application_number: str, amount: float,
                     classification: RBIClassification, risk_tier: str | None,
                     generated_at: str) -> dict:
    """FMR-shaped report payload (no PII — references + amounts only)."""
    return {
        "report_type": classification.report_type.value,
        "alert_number": alert_number,
        "application_number": application_number,
        "amount_involved_inr": round(float(amount), 2),
        "amount_involved_cr": round(float(amount) / CR, 4),
        "risk_tier": risk_tier,
        "reporting_required": classification.required,
        "deadline_hours": classification.deadline_hours,
        "generated_at": generated_at,
        "regulator": "RBI",
        "framework": "Fraud Management & FMR",
    }
