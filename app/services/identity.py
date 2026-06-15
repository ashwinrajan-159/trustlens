"""Cross-document identity resolution + synthetic-identity heuristics (Phase 4).

Pure logic: given the identity values extracted across an application's documents,
consolidate a single resolved identity and emit IDENTITY-scope signals when attributes
conflict. Reuses the fraud-engine ``RuleResult`` shape so the task layer converts to
``FraudSignal`` uniformly. No DB, no PII side effects here.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.fraud_engine.result import HIGH, MEDIUM, RuleResult

_TITLES = {"MR", "MRS", "MS", "DR", "SHRI", "SMT", "KUMARI", "M/S"}


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"[^A-Za-z ]", " ", name).upper()
    tokens = [t for t in cleaned.split() if t and t not in _TITLES]
    return " ".join(tokens)


def _most_common(values: list[str]) -> str | None:
    vals = [v for v in values if v]
    if not vals:
        return None
    return Counter(vals).most_common(1)[0][0]


def mask_name(name: str | None) -> str | None:
    if not name:
        return None
    toks = name.split()
    if not toks:
        return None
    return " ".join([toks[0]] + ["*" * len(t) for t in toks[1:]])


@dataclass
class ResolvedIdentity:
    name: str | None = None
    pan: str | None = None
    aadhaar_last4: str | None = None
    dob: str | None = None
    distinct_name_count: int = 0
    distinct_pan_count: int = 0
    distinct_dob_count: int = 0
    synthetic_score: float = 0.0
    is_synthetic_suspected: bool = False
    indicators: list[str] = field(default_factory=list)


def resolve(
    names: list[str], pans: list[str], aadhaars: list[str], dobs: list[str]
) -> tuple[ResolvedIdentity, list[RuleResult]]:
    signals: list[RuleResult] = []
    indicators: list[str] = []

    norm_names = [normalize_name(n) for n in names]
    distinct_names = {n for n in norm_names if n}
    distinct_pans = {p.strip().upper() for p in pans if p}
    distinct_dobs = {d.strip() for d in dobs if d}

    if len(distinct_names) > 1:
        indicators.append("name_mismatch")
        signals.append(RuleResult(
            "NAME_MISMATCH_ACROSS_DOCS", MEDIUM,
            f"{len(distinct_names)} distinct applicant names across documents",
            "identity_name_mismatch", 0.8, {"distinct_names": len(distinct_names)},
        ))
    if len(distinct_pans) > 1:
        indicators.append("pan_mismatch")
        signals.append(RuleResult(
            "PAN_MISMATCH_ACROSS_DOCS", HIGH,
            f"{len(distinct_pans)} distinct PANs across documents",
            "identity_pan_mismatch", 0.9, {"distinct_pans": len(distinct_pans)},
        ))
    if len(distinct_dobs) > 1:
        indicators.append("dob_mismatch")
        signals.append(RuleResult(
            "DOB_MISMATCH_ACROSS_DOCS", HIGH,
            f"{len(distinct_dobs)} distinct dates of birth across documents",
            "identity_dob_mismatch", 0.85, {"distinct_dobs": len(distinct_dobs)},
        ))

    # Synthetic / stitched identity: multiple PANs, or a name conflict combined with
    # another conflicting core attribute (PAN or DOB).
    synthetic = (len(distinct_pans) > 1) or (
        len(distinct_names) > 1 and (len(distinct_dobs) > 1 or len(distinct_pans) > 1)
    )
    if synthetic:
        signals.append(RuleResult(
            "POSSIBLE_SYNTHETIC_IDENTITY", HIGH,
            "Conflicting identity attributes suggest a synthetic or stitched identity",
            "identity_synthetic", 0.7, {"indicators": indicators},
        ))

    aadhaar = _most_common(aadhaars)
    last4 = re.sub(r"\D", "", aadhaar)[-4:] if aadhaar else None

    resolved = ResolvedIdentity(
        name=_most_common([n.strip() for n in names if n and n.strip()]),
        pan=_most_common([p.strip().upper() for p in pans if p]),
        aadhaar_last4=last4,
        dob=_most_common([d.strip() for d in dobs if d]),
        distinct_name_count=len(distinct_names),
        distinct_pan_count=len(distinct_pans),
        distinct_dob_count=len(distinct_dobs),
        synthetic_score=float(len(indicators)),
        is_synthetic_suspected=synthetic,
        indicators=indicators,
    )
    return resolved, signals
