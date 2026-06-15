"""Single-document fraud rules (Phase 3b).

Each rule is a pure ``(RuleContext) -> RuleResult | None``. ``ALL_RULES`` is the ordered
registry the engine runs. Adding a rule = append a function here; no other wiring needed.
"""
from __future__ import annotations

from collections.abc import Callable

from app.fraud_engine.result import CRITICAL, HIGH, LOW, MEDIUM, RuleContext, RuleResult
from app.fraud_engine.validators import (
    is_valid_aadhaar,
    is_valid_gstin,
    is_valid_ifsc,
    is_valid_pan,
)

# Entity-type strings (match app.models.enums.EntityType values).
PAN, AADHAAR, IFSC, GSTIN = "PAN", "AADHAAR", "IFSC", "GSTIN"
NET_SALARY, GROSS_SALARY = "NET_SALARY", "GROSS_SALARY"


# ── Document integrity ──

def low_ocr_confidence(ctx: RuleContext) -> RuleResult | None:
    if ctx.ocr_confidence is None:
        return None
    if ctx.ocr_confidence < 0.4:
        sev, conf = HIGH, 0.9
    elif ctx.ocr_confidence < 0.6:
        sev, conf = MEDIUM, 0.8
    else:
        return None
    return RuleResult(
        signal_type="LOW_OCR_CONFIDENCE", severity=sev,
        description=f"OCR confidence {ctx.ocr_confidence:.2f} is below the reliable-read threshold",
        rule_name="low_ocr_confidence", confidence=conf,
        evidence={"ocr_confidence": ctx.ocr_confidence},
    )


def duplicate_document(ctx: RuleContext) -> RuleResult | None:
    if not ctx.duplicate_of_document_id:
        return None
    return RuleResult(
        signal_type="DUPLICATE_DOCUMENT", severity=MEDIUM,
        description="Document bytes are identical to a previously uploaded document",
        rule_name="duplicate_document", confidence=0.95,
        evidence={"duplicate_of_document_id": ctx.duplicate_of_document_id},
    )


# ── Identity ──

def invalid_pan_format(ctx: RuleContext) -> RuleResult | None:
    bad = [v for v in ctx.values(PAN) if not is_valid_pan(v)]
    if not bad:
        return None
    return RuleResult(
        signal_type="INVALID_PAN_FORMAT", severity=HIGH,
        description="A PAN value does not match the required format [A-Z]{5}[0-9]{4}[A-Z]",
        rule_name="invalid_pan_format", confidence=0.95,
        evidence={"invalid_count": len(bad)},
    )


def invalid_aadhaar_checksum(ctx: RuleContext) -> RuleResult | None:
    bad = [v for v in ctx.values(AADHAAR) if not is_valid_aadhaar(v)]
    if not bad:
        return None
    return RuleResult(
        signal_type="INVALID_AADHAAR_CHECKSUM", severity=HIGH,
        description="An Aadhaar number failed Verhoeff checksum validation",
        rule_name="invalid_aadhaar_checksum", confidence=0.9,
        evidence={"invalid_count": len(bad)},
    )


def invalid_ifsc_format(ctx: RuleContext) -> RuleResult | None:
    bad = [v for v in ctx.values(IFSC) if not is_valid_ifsc(v)]
    if not bad:
        return None
    return RuleResult(
        signal_type="INVALID_IFSC_FORMAT", severity=MEDIUM,
        description="An IFSC value does not match the required format",
        rule_name="invalid_ifsc_format", confidence=0.9, evidence={"invalid_count": len(bad)},
    )


def invalid_gstin_format(ctx: RuleContext) -> RuleResult | None:
    bad = [v for v in ctx.values(GSTIN) if not is_valid_gstin(v)]
    if not bad:
        return None
    return RuleResult(
        signal_type="INVALID_GSTIN_FORMAT", severity=MEDIUM,
        description="A GSTIN value does not match the required 15-character format",
        rule_name="invalid_gstin_format", confidence=0.9, evidence={"invalid_count": len(bad)},
    )


# ── Income ──

def salary_extraction_failure(ctx: RuleContext) -> RuleResult | None:
    if ctx.document_type != "SALARY_SLIP":
        return None
    if ctx.amount(NET_SALARY) is not None or ctx.amount(GROSS_SALARY) is not None:
        return None
    return RuleResult(
        signal_type="SALARY_EXTRACTION_FAILURE", severity=MEDIUM,
        description="No salary amount could be extracted from a salary slip",
        rule_name="salary_extraction_failure", confidence=0.7,
    )


def round_number_salary(ctx: RuleContext) -> RuleResult | None:
    for etype in (NET_SALARY, GROSS_SALARY):
        amt = ctx.amount(etype)
        if amt and amt >= 10000 and amt % 10000 == 0:
            return RuleResult(
                signal_type="ROUND_NUMBER_SALARY", severity=LOW,
                description=f"{etype} is a suspiciously round figure ({amt:.0f})",
                rule_name="round_number_salary", confidence=0.5,
                evidence={"entity_type": etype, "amount": amt},
            )
    return None


def net_exceeds_gross(ctx: RuleContext) -> RuleResult | None:
    net, gross = ctx.amount(NET_SALARY), ctx.amount(GROSS_SALARY)
    if net is None or gross is None or net <= gross:
        return None
    return RuleResult(
        signal_type="NET_EXCEEDS_GROSS", severity=CRITICAL,
        description=f"Net salary ({net:.0f}) exceeds gross salary ({gross:.0f}) — impossible",
        rule_name="net_exceeds_gross", confidence=0.95,
        evidence={"net": net, "gross": gross},
    )


ALL_RULES: list[Callable[[RuleContext], RuleResult | None]] = [
    low_ocr_confidence,
    duplicate_document,
    invalid_pan_format,
    invalid_aadhaar_checksum,
    invalid_ifsc_format,
    invalid_gstin_format,
    salary_extraction_failure,
    round_number_salary,
    net_exceeds_gross,
]
