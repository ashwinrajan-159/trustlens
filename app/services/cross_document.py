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

# ── Per-loan-type document requirements ────────────────────────────────────────
# A "group" is satisfied when ANY one of its document types is present (e.g. identity
# is satisfied by Aadhaar OR PAN OR …). ``required`` groups gate submission; the rest
# are recommended (advisory only — never block, never solo-deny). One source of truth
# for: the submit gate, the requirements endpoint, and the completeness fraud signal.

@dataclass(frozen=True)
class DocGroup:
    key: str
    label: str
    any_of: tuple[str, ...]
    required: bool = True


_IDENTITY = ("AADHAAR", "PAN", "PASSPORT", "VOTER_ID", "DRIVING_LICENSE")
_INCOME = ("SALARY_SLIP", "ITR")              # salaried slip or tax return
_BIZ_TAX = ("ITR", "GST_RETURN")
_BIZ_REG = ("GST_RETURN", "BUSINESS_PROOF")   # GST / Udyam / Shop & Establishment proof
_PROPERTY = ("SALE_DEED", "TITLE_DEED")

LOAN_REQUIREMENTS: dict[str, list[DocGroup]] = {
    "PERSONAL": [
        DocGroup("identity", "Identity (Aadhaar / PAN / Passport / Voter ID / Driving License)", _IDENTITY),
        DocGroup("income", "Income proof (Salary Slip or ITR)", _INCOME),
        DocGroup("bank", "Bank statement", ("BANK_STATEMENT",)),
    ],
    "HOME": [
        DocGroup("identity", "Identity (Aadhaar / PAN)", _IDENTITY),
        DocGroup("income", "Income proof (Salary Slip or ITR)", _INCOME),
        DocGroup("bank", "Bank statement", ("BANK_STATEMENT",)),
        DocGroup("property", "Property ownership (Sale Deed or Title Deed)", _PROPERTY),
        DocGroup("plan", "Approved building plan (under-construction property)", ("APPROVED_PLAN",), required=False),
    ],
    "BUSINESS": [
        DocGroup("identity", "Identity (Aadhaar / PAN)", _IDENTITY),
        DocGroup("bank", "Bank statement", ("BANK_STATEMENT",)),
        DocGroup("tax", "ITR or GST Return", _BIZ_TAX),
        DocGroup("registration", "Business registration proof (GST / Udyam / Shop License)", _BIZ_REG),
    ],
    "AUTO": [
        DocGroup("identity", "Identity (Aadhaar / PAN)", _IDENTITY),
        DocGroup("income", "Income proof (Salary Slip or ITR)", _INCOME),
        DocGroup("bank", "Bank statement", ("BANK_STATEMENT",)),
        DocGroup("license", "Driving License (preferred)", ("DRIVING_LICENSE",), required=False),
    ],
}


def evaluate_requirements(loan_type: str, present: set[str]) -> dict:
    """Evaluate a loan type's document requirements against the present doc types.

    Returns a structured status (per-group ``ok`` + the labels of any unmet
    required/recommended groups + an overall ``satisfied`` flag).
    """
    groups = LOAN_REQUIREMENTS.get(loan_type, LOAN_REQUIREMENTS["PERSONAL"])
    status = []
    for g in groups:
        present_in_group = sorted(set(g.any_of) & present)
        status.append({
            "key": g.key, "label": g.label, "any_of": list(g.any_of),
            "required": g.required, "present": present_in_group, "ok": bool(present_in_group),
        })
    missing_required = [g["label"] for g in status if g["required"] and not g["ok"]]
    missing_recommended = [g["label"] for g in status if not g["required"] and not g["ok"]]
    return {
        "loan_type": loan_type,
        "groups": status,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "satisfied": not missing_required,
    }


SALARY_TOLERANCE = 0.10  # 10% — net pay vs bank credit may differ by deductions/rounding


@dataclass
class CrossDocContext:
    loan_type: str
    present_doc_types: set[str]
    net_salaries: list[float] = field(default_factory=list)
    salary_credits: list[float] = field(default_factory=list)


def compute_completeness(loan_type: str, present: set[str]) -> tuple[list[str], list[str]]:
    """Return (missing_required_labels, missing_recommended_labels) for a loan type,
    derived from the single ``LOAN_REQUIREMENTS`` spec."""
    r = evaluate_requirements(loan_type, present)
    return r["missing_required"], r["missing_recommended"]


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
