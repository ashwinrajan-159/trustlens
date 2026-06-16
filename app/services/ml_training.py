"""Model training (Phase 9) — local sklearn, no internet.

Pure of the DB: takes a feature matrix + labels and returns a fitted model + governance
metrics, or refuses with a reason if the data gates aren't met (too few samples / too low
fraud prevalence — training on thin data is how you ship a biased model). Default model is
a RandomForest (always available); XGBoost is used if installed and requested.

Metrics (spec §9): PR-AUC, ROC-AUC, F1, precision, recall, FPR, and FDR@k — the fraud
detection rate when an analyst reviews the top-k% highest-scored cases.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split


@dataclass
class TrainConfig:
    algorithm: str = "random_forest"
    min_samples: int = 20
    min_fraud_rate: float = 0.10
    test_size: float = 0.25
    random_state: int = 42


@dataclass
class TrainResult:
    ok: bool
    reason: str | None = None
    model: Any = None
    algorithm: str = ""
    metrics: dict = field(default_factory=dict)
    n_samples: int = 0


def _build_estimator(algorithm: str, random_state: int):
    if algorithm == "xgboost":
        try:
            from xgboost import XGBClassifier

            return XGBClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.1,
                eval_metric="logloss", random_state=random_state,
            ), "xgboost"
        except ImportError:
            pass  # fall back to RandomForest if xgboost isn't installed
    return RandomForestClassifier(
        n_estimators=200, max_depth=8, class_weight="balanced", random_state=random_state,
    ), "random_forest"


def _fdr_at_k(y_true: np.ndarray, scores: np.ndarray, k_pct: float) -> float:
    """Fraud detection rate when reviewing the top k% highest-scored cases."""
    total_fraud = int(y_true.sum())
    if total_fraud == 0:
        return 0.0
    n = max(1, int(round(len(scores) * k_pct)))
    top_idx = np.argsort(scores)[::-1][:n]
    return round(float(y_true[top_idx].sum()) / total_fraud, 4)


def train(
    X: list[list[float]], y: list[int], *, config: TrainConfig | None = None
) -> TrainResult:
    config = config or TrainConfig()
    Xa, ya = np.asarray(X, dtype=float), np.asarray(y, dtype=int)
    n = len(ya)

    # ── Data gates ──
    if n < config.min_samples:
        return TrainResult(False, f"insufficient_samples: {n} < {config.min_samples}", n_samples=n)
    fraud_rate = float(ya.mean()) if n else 0.0
    if ya.sum() == 0 or ya.sum() == n:
        return TrainResult(False, "single_class: need both fraud and legitimate labels", n_samples=n)
    if fraud_rate < config.min_fraud_rate:
        return TrainResult(False, f"low_fraud_rate: {fraud_rate:.2f} < {config.min_fraud_rate}", n_samples=n)

    X_tr, X_te, y_tr, y_te = train_test_split(
        Xa, ya, test_size=config.test_size, stratify=ya, random_state=config.random_state
    )
    estimator, algo = _build_estimator(config.algorithm, config.random_state)
    estimator.fit(X_tr, y_tr)

    proba = estimator.predict_proba(X_te)[:, 1]
    pred = (proba >= 0.5).astype(int)

    tn = int(((pred == 0) & (y_te == 0)).sum())
    fp = int(((pred == 1) & (y_te == 0)).sum())
    fpr = round(fp / (fp + tn), 4) if (fp + tn) else 0.0

    def _safe_auc(fn):
        try:
            return round(float(fn(y_te, proba)), 4)
        except ValueError:  # single-class test fold
            return None

    metrics = {
        "pr_auc": _safe_auc(average_precision_score),
        "roc_auc": _safe_auc(roc_auc_score),
        "f1": round(float(f1_score(y_te, pred, zero_division=0)), 4),
        "precision": round(float(precision_score(y_te, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_te, pred, zero_division=0)), 4),
        "fpr": fpr,
        "fdr_at_5": _fdr_at_k(y_te, proba, 0.05),
        "fdr_at_10": _fdr_at_k(y_te, proba, 0.10),
        "fdr_at_20": _fdr_at_k(y_te, proba, 0.20),
        "fraud_rate": round(fraud_rate, 4),
        "test_samples": int(len(y_te)),
    }
    return TrainResult(True, None, model=estimator, algorithm=algo, metrics=metrics, n_samples=n)
