"""Inference + drift (Phase 9) — local, explainable.

``predict`` runs the champion's ``predict_proba`` on an ordered feature vector and returns
the fraud probability, an ML risk tier, and the top contributing features (SHAP if
installed, else the model's feature importances weighted by the feature value). ML output
is advisory — a *second opinion* surfaced alongside the deterministic score, never the
system of record.

``ks_drift`` runs a scipy KS-test per feature between a reference (training) sample and a
recent sample, flagging features whose distribution has shifted.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


def proba_to_tier(p: float) -> str:
    if p >= 0.80:
        return "CRITICAL"
    if p >= 0.60:
        return "HIGH"
    if p >= 0.30:
        return "MEDIUM"
    return "LOW"


@dataclass
class PredictionResult:
    fraud_probability: float
    risk_tier: str
    shap_top: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0


def _top_contributions(model: Any, vector: list[float], names: list[str], k: int = 5) -> list[dict]:
    """Top feature contributions. SHAP if available; else importance×value heuristic."""
    try:  # pragma: no cover - SHAP is an optional dependency
        import shap

        explainer = shap.TreeExplainer(model)
        vals = explainer.shap_values([vector])
        contrib = vals[1][0] if isinstance(vals, list) else vals[0]
        pairs = sorted(zip(names, contrib, strict=False), key=lambda x: abs(x[1]), reverse=True)
        return [{"feature": n, "contribution": round(float(c), 4)} for n, c in pairs[:k]]
    except Exception:  # noqa: BLE001 - fall back to feature importances
        importances = getattr(model, "feature_importances_", None)
        if importances is None:
            return []
        pairs = sorted(
            ((n, float(imp) * float(v)) for n, imp, v in zip(names, importances, vector, strict=False)),
            key=lambda x: abs(x[1]), reverse=True,
        )
        return [{"feature": n, "contribution": round(c, 4)} for n, c in pairs[:k]]


def predict(model: Any, vector: list[float], names: list[str]) -> PredictionResult:
    start = time.perf_counter()
    proba = float(model.predict_proba([vector])[0][1])
    latency = (time.perf_counter() - start) * 1000.0
    return PredictionResult(
        fraud_probability=round(proba, 4),
        risk_tier=proba_to_tier(proba),
        shap_top=_top_contributions(model, vector, names),
        latency_ms=round(latency, 2),
    )


def ks_drift(reference: list[list[float]], recent: list[list[float]], names: list[str], *, threshold: float = 0.2) -> dict:
    """Per-feature KS-test drift between a reference and a recent feature sample."""
    import numpy as np
    from scipy.stats import ks_2samp

    ref, rec = np.asarray(reference, dtype=float), np.asarray(recent, dtype=float)
    drifted = []
    per_feature = {}
    for i, name in enumerate(names):
        if ref.shape[0] == 0 or rec.shape[0] == 0:
            continue
        stat, _ = ks_2samp(ref[:, i], rec[:, i])
        per_feature[name] = round(float(stat), 4)
        if stat > threshold:
            drifted.append(name)
    return {
        "drifted_features": drifted,
        "per_feature_ks": per_feature,
        "drift_detected": bool(drifted),
        "recommendation": "retrain" if drifted else "ok",
    }
