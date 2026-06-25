"""Document-forensics intelligence layer for TrustLens."""
from .base import (
    DocumentBundle, DocumentKind, ForensicConfidence, ForensicResult,
    ForensicSeverity, ForensicSignal, HashStore, CONFIDENCE_MULTIPLIER,
)
from .pipeline import run_forensics, classify

__all__ = [
    "run_forensics", "classify",
    "DocumentBundle", "DocumentKind", "ForensicResult", "ForensicSignal",
    "ForensicSeverity", "ForensicConfidence", "HashStore", "CONFIDENCE_MULTIPLIER",
]
