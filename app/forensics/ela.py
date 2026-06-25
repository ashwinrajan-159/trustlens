"""
Error Level Analysis (ELA) — Tier 3 / SUGGESTIVE.  *** READ THIS ***

ELA is the most over-hyped tool in this whole list. It only has any meaning on
JPEGs (re-saving introduces compression error that differs between original and
pasted regions). On PNGs, lossless exports and most PDFs it is meaningless, and
even on JPEGs it produces a high rate of false positives — bright edges, text
and high-contrast areas always "light up" regardless of tampering.

Because of that, this analyzer:
  - runs ONLY on JPEG-sourced images,
  - is hard-capped at SUGGESTIVE confidence (0.25x multiplier in base.py), so it
    can never, by itself, move an application into a denial,
  - is intended as an *analyst heat-map cue*, not an automated verdict.

Do not raise its confidence. If you find yourself wanting to, you actually want
metadata/font/copy-move evidence instead.
"""
from __future__ import annotations

import io

from .base import (
    DocumentBundle, ForensicConfidence, ForensicSeverity, ForensicSignal,
)

RESAVE_QUALITY = 90
SUSPECT_RATIO = 0.04   # fraction of pixels with anomalously high residual


class ELAForensics:
    name = "ela"

    def applies_to(self, bundle: DocumentBundle) -> bool:
        # JPEG only. Cheap sniff on the magic bytes / mime.
        return bundle.mime in ("image/jpeg", "image/jpg") or \
            bundle.raw_bytes[:3] == b"\xff\xd8\xff"

    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        try:
            from PIL import Image, ImageChops
            import numpy as np
        except Exception:
            return []
        try:
            orig = Image.open(io.BytesIO(bundle.raw_bytes)).convert("RGB")
            buf = io.BytesIO()
            orig.save(buf, "JPEG", quality=RESAVE_QUALITY)
            buf.seek(0)
            resaved = Image.open(buf).convert("RGB")
            ela = np.asarray(ImageChops.difference(orig, resaved), dtype="float32")
        except Exception:
            return []

        mag = ela.max(axis=2)
        if mag.size == 0:
            return []
        thresh = mag.mean() + 3.0 * mag.std()
        suspect = float((mag > thresh).mean())
        if suspect <= SUSPECT_RATIO:
            return []

        ys, xs = (mag > thresh).nonzero()
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if xs.size else []
        return [ForensicSignal(
            code="FORENSIC_ELA_ANOMALY",
            title="Uneven compression error (ELA) — analyst review",
            severity=ForensicSeverity.MEDIUM,
            confidence=ForensicConfidence.SUGGESTIVE,
            raw_weight=0.5,
            reasons=[
                "Error-level analysis found a localised region whose compression "
                "error differs from its surroundings, which *can* indicate a "
                "pasted/edited area. ELA is noisy (text and edges trigger it too); "
                "treat as a visual cue for an analyst, not proof.",
            ],
            evidence={"suspect_pixel_ratio": round(suspect, 4),
                      "region_bbox": bbox},
            analyzer=self.name, document_id=bundle.document_id,
        )]
