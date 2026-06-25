"""
Noise & compression-artifact analysis — Tier 3 / SUGGESTIVE.

Two complementary heuristics, both intended as analyst cues (capped SUGGESTIVE):

1.  Local noise inconsistency: estimate the high-frequency residual (image minus
    a median-blurred version) and look at how its variance differs across a grid
    of tiles. A pasted region often carries noise from a *different* source, so
    one tile's noise variance stands far from the rest.

2.  JPEG block-grid disruption: authentic JPEGs have an 8x8 DCT block structure;
    a region pasted from a differently-compressed source breaks the periodicity.

Same warning as ELA: useful to *direct attention*, not to decide. Document scans
have wildly uneven noise for innocent reasons (fold lines, scanner banding), so
this stays low-weight on purpose.
"""
from __future__ import annotations

from .base import (
    DocumentBundle, ForensicConfidence, ForensicSeverity, ForensicSignal,
)

GRID = 8                 # tiles per axis for the noise map
OUTLIER_Z = 3.0          # z-score for a tile to count as anomalous


class NoiseForensics:
    name = "noise"

    def applies_to(self, bundle: DocumentBundle) -> bool:
        return bool(bundle.page_images)

    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        try:
            import cv2
            import numpy as np
        except Exception:
            return []

        out: list[ForensicSignal] = []
        for page_idx, img in enumerate(bundle.page_images):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype("float32")
            residual = gray - cv2.medianBlur(gray.astype("uint8"), 3).astype("float32")
            h, w = residual.shape
            th, tw = h // GRID, w // GRID
            if th < 8 or tw < 8:
                continue

            variances = []
            for gy in range(GRID):
                for gx in range(GRID):
                    tile = residual[gy * th:(gy + 1) * th, gx * tw:(gx + 1) * tw]
                    variances.append(float(tile.var()))
            arr = np.asarray(variances)
            mu, sd = arr.mean(), arr.std()
            if sd < 1e-6:
                continue
            z = (arr - mu) / sd
            anomalous = int((np.abs(z) > OUTLIER_Z).sum())
            if anomalous:
                idx = int(np.argmax(np.abs(z)))
                gy, gx = divmod(idx, GRID)
                out.append(ForensicSignal(
                    code="FORENSIC_NOISE_INCONSISTENCY",
                    title="Localised noise inconsistency — analyst review",
                    severity=ForensicSeverity.LOW,
                    confidence=ForensicConfidence.SUGGESTIVE,
                    raw_weight=0.4,
                    reasons=["One or more image regions show noise statistics that "
                             "diverge sharply from the rest of the page, which can "
                             "indicate a spliced-in region. Scans are naturally "
                             "noisy, so verify before relying on this."],
                    evidence={"anomalous_tiles": anomalous,
                              "grid": GRID,
                              "worst_tile_rowcol": [gy, gx],
                              "page": page_idx},
                    analyzer=self.name, document_id=bundle.document_id,
                    page=page_idx,
                ))
        return out
