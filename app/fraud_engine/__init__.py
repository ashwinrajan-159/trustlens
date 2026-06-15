"""Standalone, explainable fraud-detection engine.

Pure Python — imports nothing from ``app.*`` outside this package — so it can be tested
and reused independently of the web app. Public surface:

    from app.fraud_engine import RuleContext, run_rules, score
"""
from app.fraud_engine.engine import run_rules
from app.fraud_engine.result import RuleContext, RuleResult
from app.fraud_engine.scorer import ScoreResult, score, score_to_tier

__all__ = ["RuleContext", "RuleResult", "run_rules", "score", "ScoreResult", "score_to_tier"]
