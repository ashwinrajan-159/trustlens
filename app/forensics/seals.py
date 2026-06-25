"""
Seal / stamp verification — honest two-phase design.

True "is this a genuine ICICI / Sub-Registrar seal?" verification requires a
REFERENCE LIBRARY of authentic seals per institution. That is a data-collection
project, not an algorithm — and without it, any "authenticity" claim is fiction.
So this analyzer ships in two layers:

PHASE 1 (implemented, no reference data) — digital-insertion heuristics.
    Detect circular/elliptical stamp candidates (Hough) and flag the tells of a
    *digitally pasted* stamp rather than an inked impression:
      - implausibly clean / hard edges (no ink bleed or paper texture),
      - perfectly uniform fill colour (real ink varies),
      - a sharp rectangular alpha/JPEG halo around the stamp.
    CORROBORATIVE: points an analyst at a suspicious stamp.

PHASE 2 (interface only) — template matching against a genuine-seal library.
    When you have `bundle.context['seal_templates']` (per issuer), match detected
    stamps and emit STRONG signals on mismatch/absence. Wire this once the
    library exists; until then it is correctly reported as unavailable.
"""
from __future__ import annotations

from .base import (
    DocumentBundle, ForensicConfidence, ForensicSeverity, ForensicSignal,
)


class SealForensics:
    name = "seals"

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
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blurred = cv2.medianBlur(gray, 5)
            h, w = gray.shape
            circles = cv2.HoughCircles(
                blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=max(40, w // 12),
                param1=120, param2=60,
                minRadius=max(15, w // 40), maxRadius=max(60, w // 6),
            )
            if circles is None:
                continue
            # Cast to plain Python ints BEFORE arithmetic — numpy uint16 scalars
            # underflow on (cx - r) when r > cx, raising a RuntimeWarning and
            # producing a garbage bbox.
            for c in np.around(circles[0]).astype(int):
                cx, cy, r = int(c[0]), int(c[1]), int(c[2])
                x0, y0 = max(0, cx - r), max(0, cy - r)
                x1, y1 = min(w, cx + r), min(h, cy + r)
                patch = img[y0:y1, x0:x1]
                if patch.size == 0:
                    continue
                tells = self._insertion_tells(patch)
                # Require ALL THREE insertion tells (was >=2). Every genuine
                # Indian ID card carries a *printed* government emblem/hologram
                # that trivially trips 2 of these heuristics; only a truly pasted
                # graphic (crisp edges AND uniform fill AND a paste halo) hits 3.
                if len(tells) >= 3:
                    out.append(ForensicSignal(
                        code="FORENSIC_SEAL_DIGITALLY_INSERTED",
                        title="Stamp/seal appears digitally inserted",
                        # Downgraded HIGH→MEDIUM and CORROBORATIVE→SUGGESTIVE:
                        # without a genuine-seal reference library this is an
                        # analyst cue, not weight that should move a denial.
                        severity=ForensicSeverity.MEDIUM,
                        confidence=ForensicConfidence.SUGGESTIVE,
                        raw_weight=0.55,
                        reasons=["A circular stamp region shows hallmarks of digital "
                                 "insertion rather than a physical ink impression: "
                                 + "; ".join(tells) + "."],
                        evidence={"region_bbox": [x0, y0, x1, y1],
                                  "tells": tells, "page": page_idx},
                        analyzer=self.name, document_id=bundle.document_id,
                        page=page_idx,
                    ))

        # Phase 2 availability note (so audit shows we didn't silently skip auth check)
        if not bundle.context.get("seal_templates"):
            out.append(ForensicSignal(
                code="FORENSIC_SEAL_AUTH_UNAVAILABLE",
                title="Seal authenticity not verified (no reference library)",
                severity=ForensicSeverity.INFO,
                confidence=ForensicConfidence.SUGGESTIVE,
                raw_weight=0.0,
                reasons=["Authenticity matching against genuine issuer seals was "
                         "not performed because no reference-seal library is "
                         "configured. Only digital-insertion heuristics ran."],
                evidence={},
                analyzer=self.name, document_id=bundle.document_id,
            ))
        return out

    @staticmethod
    def _insertion_tells(patch) -> list[str]:
        import cv2
        import numpy as np
        tells: list[str] = []
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)

        # 1. edge sharpness: pasted graphics have crisp, high-gradient borders.
        #    Threshold raised (1500→2500) — printed emblems are also fairly crisp.
        lap = cv2.Laplacian(gray, cv2.CV_64F).var()
        if lap > 2500:
            tells.append("unusually crisp edges (no ink bleed)")

        # 2. colour-fill uniformity: real ink varies in saturation.
        #    Tightened (std<12→<8) — printed emblems have some natural variation.
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        ink = hsv[(hsv[..., 1] > 60)]
        if ink.size and float(ink[:, 1].std()) < 8:
            tells.append("uniform fill colour (real ink varies)")

        # 3. rectangular compression halo around a round stamp.
        #    Tightened (30→45) — only a genuine paste boundary is this strong.
        edges = cv2.Canny(gray, 80, 200)
        border = np.concatenate([edges[0], edges[-1], edges[:, 0], edges[:, -1]])
        if border.mean() > 45:
            tells.append("rectangular halo / paste boundary")
        return tells
