"""Deterministic, explainable risk scoring (spec §7).

Weighted sum of signal severities → 0–100 → tier. Every contribution is recorded in
``reasons`` so a regulator/analyst can audit exactly how the score was reached. Standalone:
weights + tier thresholds live here (single source of truth), no app imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.fraud_engine.result import RuleResult

SEVERITY_WEIGHTS: dict[str, float] = {
    "LOW": 5.0,
    "MEDIUM": 15.0,
    "HIGH": 30.0,
    "CRITICAL": 50.0,
}

# Tier thresholds (spec §7): LOW <30, MEDIUM 30–60, HIGH 60–80, CRITICAL >80.
def score_to_tier(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


# Signal-type → risk category (mirrors app.models.enums.SIGNAL_CATEGORY_MAP values).
SIGNAL_CATEGORY: dict[str, str] = {
    "LOW_OCR_CONFIDENCE": "DOCUMENT",
    "EXTRACTION_FAILURE": "DOCUMENT",
    "DUPLICATE_DOCUMENT": "DOCUMENT",
    "INVALID_PAN_FORMAT": "IDENTITY",
    "INVALID_AADHAAR_CHECKSUM": "IDENTITY",
    "INVALID_IFSC_FORMAT": "IDENTITY",
    "INVALID_GSTIN_FORMAT": "IDENTITY",
    "SALARY_EXTRACTION_FAILURE": "INCOME",
    "ROUND_NUMBER_SALARY": "INCOME",
    "NET_EXCEEDS_GROSS": "INCOME",
    "NAME_MISMATCH_ACROSS_DOCS": "IDENTITY",
    "PAN_MISMATCH_ACROSS_DOCS": "IDENTITY",
    "DOB_MISMATCH_ACROSS_DOCS": "IDENTITY",
    "POSSIBLE_SYNTHETIC_IDENTITY": "IDENTITY",
    "MISSING_CRITICAL_DOCUMENT": "DOCUMENT",
    "MISSING_RECOMMENDED_DOCUMENT": "DOCUMENT",
    "SALARY_BANK_MISMATCH": "INCOME",
    "EMPLOYER_DEPOSIT_NOT_FOUND": "INCOME",
    "SALARY_INCONSISTENT_ACROSS_SLIPS": "INCOME",
}


@dataclass
class ScoreResult:
    total_score: float
    risk_tier: str
    reasons: list[dict] = field(default_factory=list)
    by_category: dict[str, float] = field(default_factory=dict)


def score(results: list[RuleResult]) -> ScoreResult:
    total = 0.0
    reasons: list[dict] = []
    by_category: dict[str, float] = {}
    for r in results:
        weight = SEVERITY_WEIGHTS.get(r.severity, 0.0)
        category = SIGNAL_CATEGORY.get(r.signal_type, "DOCUMENT")
        total += weight
        by_category[category] = by_category.get(category, 0.0) + weight
        reasons.append(
            {
                "rule_name": r.rule_name,
                "signal_type": r.signal_type,
                "severity": r.severity,
                "category": category,
                "weight": weight,
                "confidence": r.confidence,
                "description": r.description,
            }
        )
    total = min(100.0, round(total, 2))
    return ScoreResult(total_score=total, risk_tier=score_to_tier(total), reasons=reasons, by_category=by_category)
