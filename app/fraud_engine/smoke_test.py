"""Standalone smoke test — run directly: ``python -m app.fraud_engine.smoke_test``.

Proves the engine works without the web app, DB, or any I/O.
"""
from __future__ import annotations

from app.fraud_engine import RuleContext, run_rules, score


def main() -> None:
    # A salary slip with an impossible net>gross and a bad PAN.
    ctx = RuleContext(
        document_id="doc-1",
        document_type="SALARY_SLIP",
        ocr_confidence=0.95,
        entities={
            "PAN": ["ABCDE1234F", "BADPAN"],          # one valid, one invalid
            "NET_SALARY": ["80000"],
            "GROSS_SALARY": ["65000"],                # net > gross → CRITICAL
        },
    )
    results = run_rules(ctx)
    s = score(results)
    print(f"signals={len(results)} score={s.total_score} tier={s.risk_tier}")
    for r in s.reasons:
        print(f"  [{r['severity']:<8}] {r['signal_type']:<24} {r['description']}")
    assert any(r.signal_type == "NET_EXCEEDS_GROSS" for r in results)
    assert any(r.signal_type == "INVALID_PAN_FORMAT" for r in results)
    assert s.risk_tier in {"HIGH", "CRITICAL"}
    print("smoke test OK")


if __name__ == "__main__":
    main()
