"""Property / collateral intelligence (Phase 6). Pure logic, no DB.

Consolidates property attributes across an application's documents (sale deed, valuation
report) and flags collateral fraud: survey-number conflicts, area mismatches, inflated
valuation vs sale consideration, owner≠applicant, and duplicate collateral (the same
survey number pledged on another application — detected by the task layer and passed in).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.fraud_engine.result import CRITICAL, HIGH, MEDIUM, RuleResult
from app.services.identity import normalize_name

AREA_TOLERANCE = 0.05          # 5% — measurement/rounding noise across documents
INFLATION_THRESHOLD = 1.20     # valuation > 1.2× sale consideration looks inflated


@dataclass
class PropertyContext:
    survey_numbers: list[str] = field(default_factory=list)
    areas: list[float] = field(default_factory=list)
    sale_considerations: list[float] = field(default_factory=list)
    valuations: list[float] = field(default_factory=list)
    owner_names: list[str] = field(default_factory=list)
    applicant_name: str | None = None
    duplicate_collateral_app_ids: list[str] = field(default_factory=list)


@dataclass
class PropertySummary:
    survey_numbers: list[str]
    area: float | None
    sale_consideration: float | None
    valuation: float | None
    valuation_ratio: float | None
    is_inflated: bool
    duplicate_collateral_app_ids: list[str]


def validate(ctx: PropertyContext) -> tuple[list[RuleResult], PropertySummary]:
    signals: list[RuleResult] = []

    distinct_surveys = sorted({s.strip().upper() for s in ctx.survey_numbers if s and s.strip()})
    if len(distinct_surveys) > 1:
        signals.append(RuleResult(
            "SURVEY_NUMBER_CONFLICT", MEDIUM,
            f"{len(distinct_surveys)} distinct survey numbers across property documents",
            "property_survey_conflict", 0.8, {"survey_numbers": distinct_surveys},
        ))

    if len(ctx.areas) > 1:
        lo, hi = min(ctx.areas), max(ctx.areas)
        if hi > 0 and (hi - lo) / hi > AREA_TOLERANCE:
            signals.append(RuleResult(
                "PROPERTY_AREA_MISMATCH", MEDIUM,
                f"Property area differs across documents ({lo:.0f}–{hi:.0f})",
                "property_area_mismatch", 0.75, {"min": lo, "max": hi},
            ))

    sale = max(ctx.sale_considerations) if ctx.sale_considerations else None
    valuation = max(ctx.valuations) if ctx.valuations else None
    ratio = (valuation / sale) if (sale and valuation and sale > 0) else None
    is_inflated = bool(ratio and ratio > INFLATION_THRESHOLD)
    if is_inflated:
        signals.append(RuleResult(
            "INFLATED_VALUATION", HIGH,
            f"Valuation ({valuation:.0f}) is {ratio:.2f}× the sale consideration ({sale:.0f})",
            "property_inflated_valuation", 0.85,
            {"valuation": valuation, "sale_consideration": sale, "ratio": round(ratio, 2)},
        ))

    if ctx.applicant_name and ctx.owner_names:
        applicant = normalize_name(ctx.applicant_name)
        owners = {normalize_name(o) for o in ctx.owner_names if normalize_name(o)}
        if applicant and owners and applicant not in owners:
            signals.append(RuleResult(
                "PROPERTY_OWNER_MISMATCH", HIGH,
                "Property owner/purchaser name does not match the resolved applicant identity",
                "property_owner_mismatch", 0.8, {"owner_count": len(owners)},
            ))

    if ctx.duplicate_collateral_app_ids:
        signals.append(RuleResult(
            "DUPLICATE_COLLATERAL", CRITICAL,
            "The same property (survey number) is pledged on another application",
            "property_duplicate_collateral", 0.9,
            {"other_application_ids": ctx.duplicate_collateral_app_ids},
        ))

    summary = PropertySummary(
        survey_numbers=distinct_surveys,
        area=max(ctx.areas) if ctx.areas else None,
        sale_consideration=sale,
        valuation=valuation,
        valuation_ratio=round(ratio, 2) if ratio else None,
        is_inflated=is_inflated,
        duplicate_collateral_app_ids=ctx.duplicate_collateral_app_ids,
    )
    return signals, summary
