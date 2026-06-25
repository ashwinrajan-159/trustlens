"""
Document-forensics framework for TrustLens.

This package adds an image/document-forensics *intelligence layer* that sits
alongside the existing fraud_engine. It produces the same kind of artifact the
rest of the platform speaks in: weighted, explainable signals anchored to a
*document within an application* — never a free-floating "this image is fake".

Design rules (important for a regulated lending product):

1.  Forensics is corroborative, not authoritative. The deterministic
    fraud_engine remains the system of record. A forensic hit nudges the score
    and raises an analyst's attention; it should rarely *solo-decide* a case.

2.  Every technique declares its own CONFIDENCE tier. Weak, high-false-positive
    techniques (ELA, noise) are capped so they cannot, by themselves, push an
    application into HIGH/CRITICAL and trigger a wrongful denial. Only STRONG
    techniques (exact cross-application reuse, impossible metadata timestamps,
    a salary number rendered in a different embedded font than its neighbours)
    are allowed to carry real weight.

3.  Technique applicability depends on the *document kind*. ELA only means
    anything on JPEGs; font-consistency is gold on a digital PDF and nearly
    useless on a phone photo. The pipeline classifies each document first and
    only runs analyzers that are valid for that kind — so we never emit a
    signal a regulator could pick apart as "you ran a JPEG test on a PNG".

Adapt `ForensicSignal` to your existing FraudSignal ORM/dataclass; the field
names here mirror the "code / severity / weight / reasons / evidence" shape
described in the platform docs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class DocumentKind(str, Enum):
    DIGITAL_PDF = "DIGITAL_PDF"     # PDF with a real, extractable text layer
    SCANNED_PDF = "SCANNED_PDF"     # PDF that is essentially full-page images
    RASTER_IMAGE = "RASTER_IMAGE"   # jpg / png / etc.
    UNKNOWN = "UNKNOWN"


class ForensicSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ForensicConfidence(str, Enum):
    """How trustworthy the *technique* is, independent of how strong this hit is.

    This is the lever that protects applicants from weak-signal false positives.
    """
    SUGGESTIVE = "SUGGESTIVE"        # noisy, high false-positive; analyst-eyes-only
    CORROBORATIVE = "CORROBORATIVE"  # meaningful, but use alongside other signals
    STRONG = "STRONG"                # reliable enough to move a decision on its own


# Multiplier applied to a signal's raw weight based on technique confidence.
# Tunable; lives here so governance/audit can point at one number.
CONFIDENCE_MULTIPLIER: dict[ForensicConfidence, float] = {
    ForensicConfidence.SUGGESTIVE: 0.25,
    ForensicConfidence.CORROBORATIVE: 0.60,
    ForensicConfidence.STRONG: 1.00,
}


@dataclass
class ForensicSignal:
    code: str                                   # stable, e.g. FORENSIC_METADATA_EDIT_SOFTWARE
    title: str                                  # short human label
    severity: ForensicSeverity
    confidence: ForensicConfidence
    raw_weight: float                           # 0..1 intrinsic strength of *this* hit
    reasons: list[str]                          # regulator-readable "why"
    evidence: dict[str, Any] = field(default_factory=dict)  # PII-SAFE structured proof
    analyzer: str = ""
    document_id: str | None = None
    page: int | None = None

    @property
    def effective_weight(self) -> float:
        """Weight after applying the confidence cap. Feed THIS to the scorer."""
        return round(self.raw_weight * CONFIDENCE_MULTIPLIER[self.confidence], 4)


@dataclass
class ForensicResult:
    document_id: str
    application_id: str
    kind: DocumentKind
    signals: list[ForensicSignal] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # analyzers not applicable + why
    errors: list[str] = field(default_factory=list)     # graceful-degrade record

    @property
    def forensics_subscore(self) -> float:
        """A 0..100 forensics-only subscore, for feeding the deterministic engine
        as a *single* signal-group rather than letting raw hits flood the scorer.

        Capped so a pile of SUGGESTIVE hits can't fabricate a CRITICAL on its own.
        """
        if not self.signals:
            return 0.0
        weighted = sum(s.effective_weight for s in self.signals)
        # squashing curve: diminishing returns, hard ceiling at 100
        score = 100.0 * (1.0 - 1.0 / (1.0 + weighted))
        return round(min(score, 100.0), 2)


@dataclass
class DocumentBundle:
    """Everything an analyzer might need, prepared once by the pipeline."""
    document_id: str
    application_id: str
    filename: str
    mime: str
    kind: DocumentKind
    raw_bytes: bytes
    fitz_doc: Any | None = None       # fitz.Document, when PDF
    page_images: list[Any] = field(default_factory=list)  # list[np.ndarray] BGR per page
    context: dict[str, Any] = field(default_factory=dict)  # OCR text-dict, extraction, etc.


class ForensicAnalyzer(Protocol):
    name: str

    def applies_to(self, bundle: DocumentBundle) -> bool: ...
    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]: ...


class HashStore(Protocol):
    """Cross-application reuse needs persistence. Implement this on top of your
    repositories layer (a `document_fingerprints` table keyed by app/doc).
    Kept abstract so the forensics package stays storage-agnostic and offline.
    """
    def find_similar(self, phash_hex: str, max_distance: int) -> list[dict]: ...
    def save(self, *, document_id: str, application_id: str, phash_hex: str,
             extra: dict | None = None) -> None: ...
