"""Financial / business intelligence (Phase 6). Pure logic, no DB.

Reconciles self-employed financials across ITR and GST returns: revenue declared in the
ITR vs GST aggregate turnover, and impossible ratios (net profit exceeding revenue).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.fraud_engine.result import HIGH, RuleResult

REVENUE_TOLERANCE = 0.25  # 25% — ITR income vs GST turnover differ by definition/timing


@dataclass
class FinancialContext:
    itr_revenues: list[float] = field(default_factory=list)
    gst_revenues: list[float] = field(default_factory=list)
    net_profits: list[float] = field(default_factory=list)


@dataclass
class FinancialSummary:
    itr_revenue: float | None
    gst_revenue: float | None
    net_profit: float | None
    revenue_gap_ratio: float | None


def validate(ctx: FinancialContext) -> tuple[list[RuleResult], FinancialSummary]:
    signals: list[RuleResult] = []

    itr = max(ctx.itr_revenues) if ctx.itr_revenues else None
    gst = max(ctx.gst_revenues) if ctx.gst_revenues else None
    net = max(ctx.net_profits) if ctx.net_profits else None

    gap_ratio = None
    if itr and gst and max(itr, gst) > 0:
        gap_ratio = abs(itr - gst) / max(itr, gst)
        if gap_ratio > REVENUE_TOLERANCE:
            signals.append(RuleResult(
                "REVENUE_MISMATCH", HIGH,
                f"ITR income ({itr:.0f}) and GST turnover ({gst:.0f}) differ by {gap_ratio:.0%}",
                "financial_revenue_mismatch", 0.85,
                {"itr_revenue": itr, "gst_revenue": gst, "gap_ratio": round(gap_ratio, 2)},
            ))

    revenue = itr or gst
    if net is not None and revenue is not None and net > revenue:
        signals.append(RuleResult(
            "IMPOSSIBLE_FINANCIAL_RATIO", HIGH,
            f"Net profit ({net:.0f}) exceeds revenue ({revenue:.0f}) — impossible",
            "financial_impossible_ratio", 0.9,
            {"net_profit": net, "revenue": revenue},
        ))

    summary = FinancialSummary(
        itr_revenue=itr, gst_revenue=gst, net_profit=net,
        revenue_gap_ratio=round(gap_ratio, 2) if gap_ratio is not None else None,
    )
    return signals, summary
