"""Engine entrypoint: run every rule against a context, collect non-null results."""
from __future__ import annotations

from app.fraud_engine.result import RuleContext, RuleResult
from app.fraud_engine.rules import ALL_RULES


def run_rules(ctx: RuleContext) -> list[RuleResult]:
    """Evaluate all rules. A rule raising is isolated so one bad rule can't sink the run."""
    results: list[RuleResult] = []
    for rule in ALL_RULES:
        try:
            res = rule(ctx)
        except Exception:  # noqa: BLE001 - never let a rule crash the pipeline
            continue
        if res is not None:
            results.append(res)
    return results
