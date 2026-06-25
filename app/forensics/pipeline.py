"""
Forensics pipeline orchestrator.

Responsibilities:
  1. Classify the document (digital PDF vs scanned PDF vs raster image) so each
     analyzer only runs where it is valid.
  2. Rasterise pages ONCE (shared by all pixel-based analyzers) — expensive work
     done a single time, matching the platform's idempotent-step philosophy.
  3. Run each analyzer with per-analyzer try/except so one failure degrades
     gracefully (recorded in result.errors) instead of failing the whole stage.
  4. Return a ForensicResult: signals + skipped + errors + a capped subscore.

This mirrors the existing analysis-pipeline contract: deterministic, re-runnable,
persists before chaining. The deterministic fraud_engine stays the system of
record — these signals are an additional, clearly-labelled input.
"""
from __future__ import annotations

from .base import (
    DocumentBundle, DocumentKind, ForensicResult, HashStore,
)
from .copy_move import CopyMoveForensics
from .ela import ELAForensics
from .font_consistency import FontConsistencyForensics
from .metadata import MetadataForensics
from .noise import NoiseForensics
from .screenshot import ScreenshotForensics
from .seals import SealForensics
from .signatures import SignatureForensics
from .similarity import SimilarityForensics

RASTER_DPI = 150           # enough for forensics without exploding memory
MAX_PAGES = 10             # cap heavy pixel analysis on huge PDFs


def classify(raw: bytes, mime: str, fitz_doc=None) -> DocumentKind:
    if fitz_doc is not None or raw[:5] == b"%PDF-":
        try:
            text_chars = sum(len(p.get_text("text")) for p in fitz_doc)  # type: ignore
            return DocumentKind.DIGITAL_PDF if text_chars > 200 else DocumentKind.SCANNED_PDF
        except Exception:
            return DocumentKind.SCANNED_PDF
    if mime.startswith("image/") or raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n":
        return DocumentKind.RASTER_IMAGE
    return DocumentKind.UNKNOWN


def _rasterise(bundle: DocumentBundle) -> None:
    """Populate bundle.page_images (list of BGR np.ndarray)."""
    import numpy as np
    if bundle.fitz_doc is not None:
        import cv2
        for i, page in enumerate(bundle.fitz_doc):
            if i >= MAX_PAGES:
                break
            pix = page.get_pixmap(dpi=RASTER_DPI)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            else:
                arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            bundle.page_images.append(arr)
    else:
        import cv2
        arr = cv2.imdecode(np.frombuffer(bundle.raw_bytes, np.uint8), cv2.IMREAD_COLOR)
        if arr is not None:
            bundle.page_images.append(arr)


def run_forensics(*, document_id: str, application_id: str, filename: str,
                  mime: str, raw_bytes: bytes, hash_store: HashStore,
                  fitz_doc=None, context: dict | None = None) -> ForensicResult:
    kind = classify(raw_bytes, mime, fitz_doc)
    bundle = DocumentBundle(
        document_id=document_id, application_id=application_id, filename=filename,
        mime=mime, kind=kind, raw_bytes=raw_bytes, fitz_doc=fitz_doc,
        context=context or {},
    )

    result = ForensicResult(document_id=document_id, application_id=application_id, kind=kind)

    analyzers = [
        MetadataForensics(),
        FontConsistencyForensics(),
        SimilarityForensics(hash_store),
        CopyMoveForensics(),
        ScreenshotForensics(),
        SignatureForensics(),
        SealForensics(),
        ELAForensics(),
        NoiseForensics(),
    ]

    needs_pixels = any(getattr(a, "name", "") in
                       {"similarity", "copy_move", "screenshot", "seals", "noise"}
                       for a in analyzers)
    if needs_pixels:
        try:
            _rasterise(bundle)
        except Exception as e:
            result.errors.append(f"rasterise: {type(e).__name__}: {e}")

    for analyzer in analyzers:
        try:
            if not analyzer.applies_to(bundle):
                result.skipped.append(analyzer.name)
                continue
            result.signals.extend(analyzer.analyze(bundle))
        except Exception as e:  # graceful degradation per analyzer
            result.errors.append(f"{analyzer.name}: {type(e).__name__}: {e}")

    return result
