"""Feature engineering for the ML platform (Phase 9). Pure + deterministic.

Turns an application's deterministic-pipeline aggregates (signals, risk, graph, identity,
property, financial) into a fixed-order numeric feature vector. ``FEATURE_NAMES`` is the
canonical schema — training and inference must use the same order, so it is versioned.
No PII enters the feature space (counts, scores, flags only).
"""
from __future__ import annotations

from dataclasses import dataclass, field

FEATURE_VERSION = 1

FEATURE_NAMES: list[str] = [
    "signal_total",
    "signal_critical",
    "signal_high",
    "signal_medium",
    "signal_low",
    "cat_identity",
    "cat_income",
    "cat_document",
    "cat_behavior",
    "deterministic_risk_score",
    "graph_connections",
    "graph_ring_size",
    "graph_in_ring",
    "shared_pan",
    "shared_account",
    "shared_property",
    "identity_synthetic",
    "distinct_pan",
    "property_inflated",
    "valuation_ratio",
    "missing_critical_docs",
    "document_count",
]


@dataclass
class FeatureInputs:
    severity_counts: dict[str, int] = field(default_factory=dict)   # LOW/MEDIUM/HIGH/CRITICAL
    category_counts: dict[str, int] = field(default_factory=dict)   # INCOME/IDENTITY/DOCUMENT/BEHAVIOR
    deterministic_risk_score: float = 0.0
    graph_connections: int = 0
    graph_ring_size: int = 0
    graph_in_ring: bool = False
    shared_pan: int = 0
    shared_account: int = 0
    shared_property: int = 0
    identity_synthetic: bool = False
    distinct_pan: int = 0
    property_inflated: bool = False
    valuation_ratio: float = 0.0
    missing_critical_docs: int = 0
    document_count: int = 0


def build_features(inp: FeatureInputs) -> dict[str, float]:
    sev = inp.severity_counts
    cat = inp.category_counts
    feats = {
        "signal_total": float(sum(sev.values())),
        "signal_critical": float(sev.get("CRITICAL", 0)),
        "signal_high": float(sev.get("HIGH", 0)),
        "signal_medium": float(sev.get("MEDIUM", 0)),
        "signal_low": float(sev.get("LOW", 0)),
        "cat_identity": float(cat.get("IDENTITY", 0)),
        "cat_income": float(cat.get("INCOME", 0)),
        "cat_document": float(cat.get("DOCUMENT", 0)),
        "cat_behavior": float(cat.get("BEHAVIOR", 0)),
        "deterministic_risk_score": float(inp.deterministic_risk_score),
        "graph_connections": float(inp.graph_connections),
        "graph_ring_size": float(inp.graph_ring_size),
        "graph_in_ring": 1.0 if inp.graph_in_ring else 0.0,
        "shared_pan": float(inp.shared_pan),
        "shared_account": float(inp.shared_account),
        "shared_property": float(inp.shared_property),
        "identity_synthetic": 1.0 if inp.identity_synthetic else 0.0,
        "distinct_pan": float(inp.distinct_pan),
        "property_inflated": 1.0 if inp.property_inflated else 0.0,
        "valuation_ratio": float(inp.valuation_ratio or 0.0),
        "missing_critical_docs": float(inp.missing_critical_docs),
        "document_count": float(inp.document_count),
    }
    return {name: feats[name] for name in FEATURE_NAMES}


def to_vector(features: dict[str, float], names: list[str] | None = None) -> list[float]:
    """Order a feature dict into a vector matching ``names`` (defaults to FEATURE_NAMES)."""
    names = names or FEATURE_NAMES
    return [float(features.get(n, 0.0)) for n in names]
