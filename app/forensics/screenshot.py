"""
Screenshot detection — Tier 2 / CORROBORATIVE.

A "bank statement" that is actually a phone screenshot of a banking app (or a
screen-grab of a PDF) is a recurring fraud/red-flag pattern: it bypasses the
real document, is trivially croppable/editable, and can hide the source.

We combine cheap heuristics (no single one is conclusive):
  - dimensions exactly match a known device/screen resolution,
  - PNG with no camera metadata (screenshots are almost always PNG, never EXIF),
  - presence of a status-bar-like uniform horizontal band near the top.

Pair this with metadata.FORENSIC_METADATA_NO_CAPTURE_ORIGIN for a stronger case.
"""
from __future__ import annotations

import io

from .base import (
    DocumentBundle, DocumentKind, ForensicConfidence,
    ForensicSeverity, ForensicSignal,
)

# (width, height) — both orientations checked. Extend for your user base.
SCREEN_RES = {
    (1080, 1920), (1170, 2532), (1284, 2778), (1125, 2436), (1440, 3200),
    (828, 1792), (750, 1334), (1080, 2340), (1080, 2400), (1242, 2688),
    (1366, 768), (1920, 1080), (2560, 1440), (1280, 800), (2048, 1536),
}


class ScreenshotForensics:
    name = "screenshot"

    def applies_to(self, bundle: DocumentBundle) -> bool:
        return bundle.kind == DocumentKind.RASTER_IMAGE and bool(bundle.page_images)

    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        try:
            from PIL import Image
            import numpy as np
        except Exception:
            return []

        img = bundle.page_images[0]
        h, w = img.shape[:2]
        # STRONG indicators actually distinguish a screen capture from a scanned/
        # photographed ID. "PNG-with-no-EXIF" is NOT one of them — almost every
        # legitimately-uploaded ID PNG lacks EXIF — so it is recorded only as
        # supporting context and can never, on its own, raise a screenshot signal.
        strong: list[str] = []
        supporting: list[str] = []

        if (w, h) in SCREEN_RES or (h, w) in SCREEN_RES:
            strong.append(f"exact screen resolution {w}x{h}")

        is_png = bundle.mime == "image/png" or bundle.raw_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        try:
            exif = getattr(Image.open(io.BytesIO(bundle.raw_bytes)), "_getexif",
                           lambda: None)() or {}
        except Exception:
            exif = {}
        if is_png and not exif:
            supporting.append("PNG with no camera/EXIF metadata")

        # status-bar tell: a thin, near-uniform horizontal band across the top
        try:
            import cv2
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            band = gray[: max(1, h // 25), :]
            row_var = float(band.var())
            if row_var < 60 and h > 400:
                strong.append("uniform status-bar-like band at top")
        except Exception:
            pass

        signals_for = strong + supporting
        if len(strong) >= 2:
            return [ForensicSignal(
                code="FORENSIC_LIKELY_SCREENSHOT",
                title="Document is likely a screenshot, not an original",
                severity=ForensicSeverity.MEDIUM,
                confidence=ForensicConfidence.CORROBORATIVE,
                raw_weight=0.5,
                reasons=["Multiple screenshot indicators present: "
                         + "; ".join(signals_for) + ". Genuine statements should be "
                         "the original PDF or a scan, not a screen capture."],
                evidence={"indicators": signals_for, "dimensions": [w, h]},
                analyzer=self.name, document_id=bundle.document_id,
            )]
        elif len(strong) == 1:
            return [ForensicSignal(
                code="FORENSIC_POSSIBLE_SCREENSHOT",
                title="Possible screenshot",
                severity=ForensicSeverity.LOW,
                confidence=ForensicConfidence.SUGGESTIVE,
                raw_weight=0.3,
                reasons=["One screenshot indicator present: " + strong[0]
                         + ("; " + supporting[0] if supporting else "") + "."],
                evidence={"indicators": signals_for, "dimensions": [w, h]},
                analyzer=self.name, document_id=bundle.document_id,
            )]
        return []
