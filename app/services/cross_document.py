"""Cross-document validation: completeness checklist + income reconciliation (Phase 5).

Pure logic operating on a pre-fetched summary of an application's PROCESSED documents.
Produces CROSS_DOCUMENT-scope signals (fraud-engine ``RuleResult`` shape). No DB here.

- **Completeness** (home-loan checklist per spec §7): missing core docs are CRITICAL,
  missing supporting docs are MEDIUM. A reduced required set applies to other loan types.
- **Income reconciliation**: salary-slip net pay vs salary credits seen in the bank
  statement — mismatch beyond tolerance, or employer deposit not found, or net pay that
  is inconsistent across multiple slips.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.fraud_engine.result import HIGH, MEDIUM, RuleResult

# "income proof" is satisfied by any one of these document types.
_INCOME_PROOF = {"SALARY_SLIP", "BANK_STATEMENT", "ITR", "FORM_16"}

# Required (CRITICAL if missing) and recommended (MEDIUM if missing) by loan type.
_CRITICAL_REQUIRED = {
    "HOME": {"PAN", "AADHAAR", "BANK_STATEMENT", "SALE_DEED", "VALUATION_REPORT"},
    "PERSONAL": {"PAN", "AADHAAR", "BANK_STATEMENT"},
    "AUTO": {"PAN", "AADHAAR", "BANK_STATEMENT"},
    "BUSINESS": {"PAN", "AADHAAR", "BANK_STATEMENT", "GST_RETURN"},
}
_RECOMMENDED = {
    "HOME": {"FORM_16", "PROPERTY_TAX", "ENCUMBRANCE_CERTIFICATE", "APPROVED_PLAN"},
    "PERSONAL": {"FORM_16"},
    "AUTO": {"FORM_16"},
    "BUSINESS": {"BALANCE_SHEET", "PROFIT_LOSS"},
}

SALARY_TOLERANCE = 0.10  # 10% — net pay vs bank credit may differ by deductions/rounding


@dataclass
class CrossDocContext:
    loan_type: str
    present_doc_types: set[str]
    net_salaries: list[float] = field(default_factory=list)
    salary_credits: list[float] = field(default_factory=list)


def compute_completeness(loan_type: str, present: set[str]) -> tuple[list[str], list[str]]:
    """Return (missing_critical, missing_recommended) for a loan type."""
    required = set(_CRITICAL_REQUIRED.get(loan_type, _CRITICAL_REQUIRED["PERSONAL"]))
    recommended = set(_RECOMMENDED.get(loan_type, set()))

    missing_critical = sorted(required - present)
    # Income proof is required but satisfiable by any income doc.
    if not (present & _INCOME_PROOF):
        missing_critical.append("INCOME_PROOF")
    missing_recommended = sorted(recommended - present)
    return missing_critical, missing_recommended


def validate(ctx: CrossDocContext) -> list[RuleResult]:
    signals: list[RuleResult] = []

    missing_critical, missing_recommended = compute_completeness(ctx.loan_type, ctx.present_doc_types)
    if missing_critical:
        signals.append(RuleResult(
            "MISSING_CRITICAL_DOCUMENT", "CRITICAL",
            f"Required documents missing for a {ctx.loan_type} loan: {', '.join(missing_critical)}",
            "completeness_critical", 0.95, {"missing": missing_critical},
        ))
    if missing_recommended:
        signals.append(RuleResult(
            "MISSING_RECOMMENDED_DOCUMENT", MEDIUM,
            f"Recommended documents missing: {', '.join(missing_recommended)}",
            "completeness_recommended", 0.7, {"missing": missing_recommended},
        ))

    # ── Income reconciliation (only when prerequisites exist; else naturally deferred) ──
    if ctx.net_salaries:
        # Net pay inconsistent across slips (beyond tolerance).
        lo, hi = min(ctx.net_salaries), max(ctx.net_salaries)
        if hi > 0 and (hi - lo) / hi > SALARY_TOLERANCE:
            signals.append(RuleResult(
                "SALARY_INCONSISTENT_ACROSS_SLIPS", HIGH,
                f"Net salary varies across slips ({lo:.0f}–{hi:.0f})",
                "salary_inconsistent", 0.8, {"min": lo, "max": hi},
            ))

        if "BANK_STATEMENT" in ctx.present_doc_types:
            if not ctx.salary_credits:
                signals.append(RuleResult(
                    "EMPLOYER_DEPOSIT_NOT_FOUND", MEDIUM,
                    "Salary slip present but no matching salary credit found in the bank statement",
                    "employer_deposit_not_found", 0.7, {},
                ))
            else:
                # Compare the representative net pay to the closest bank salary credit.
                net = max(ctx.net_salaries)
                closest = min(ctx.salary_credits, key=lambda c: abs(c - net))
                if net > 0 and abs(net - closest) / net > SALARY_TOLERANCE:
                    signals.append(RuleResult(
                        "SALARY_BANK_MISMATCH", HIGH,
                        f"Payslip net ({net:.0f}) does not match bank salary credit ({closest:.0f})",
                        "salary_bank_mismatch", 0.85,
                        {"payslip_net": net, "bank_credit": closest},
                    ))
    return signals
