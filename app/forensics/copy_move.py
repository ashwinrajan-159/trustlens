"""
Copy-move forgery detection — Tier 2 / CORROBORATIVE.

Finds regions of an image that were duplicated *within the same image* — the
fingerprint of cloning a signature, stamp, a "PAID" mark, or copying a digit
block to overwrite an amount.

Method: ORB keypoints + brute-force self-matching, then keep only matched pairs
that (a) are far apart spatially and (b) share a *consistent translation
offset* with other pairs. A real cloned region produces a cluster of matches
all shifted by roughly the same vector; random texture matches do not. This
filtering is what keeps the false-positive rate sane on documents.

Caveat (documented honestly): genuine documents legitimately repeat content —
table gridlines, a bank logo, repeated letterhead. We raise severity only when
a *dense* consistent-offset cluster appears, and keep this CORROBORATIVE so it
supports rather than drives a decision.
"""
from __future__ import annotations

from collections import defaultdict

from .base import (
    DocumentBundle, ForensicConfidence, ForensicSeverity, ForensicSignal,
)

# Raised from 12 → 30: real ID cards repeat content (logo, letterforms, guilloché
# background) that legitimately produces same-offset feature clusters. A genuine
# copy-paste of a signature/stamp/digit-block yields a much denser cluster, so the
# higher floor cuts false positives on authentic documents without missing real clones.
MIN_CLUSTER = 30          # matched pairs sharing an offset before we call it cloning
MIN_SPATIAL_DIST = 40     # px; ignore near-self matches
OFFSET_BUCKET = 8         # px quantisation for grouping translation vectors
MAX_DESC_DIST = 24        # ORB descriptor distance gate (tightened from 32) — near-identical only


class CopyMoveForensics:
    name = "copy_move"

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
            orb = cv2.ORB_create(nfeatures=4000)
            kps, desc = orb.detectAndCompute(gray, None)
            if desc is None or len(kps) < 2 * MIN_CLUSTER:
                continue

            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            # k=10: a cloned point matches its twin, not itself
            knn = bf.knnMatch(desc, desc, k=10)

            offsets: dict[tuple[int, int], list] = defaultdict(list)
            for matches in knn:
                for m in matches:
                    if m.queryIdx == m.trainIdx:
                        continue
                    if m.distance > MAX_DESC_DIST:   # ORB descriptor distance gate
                        continue
                    p1 = kps[m.queryIdx].pt
                    p2 = kps[m.trainIdx].pt
                    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                    if (dx * dx + dy * dy) ** 0.5 < MIN_SPATIAL_DIST:
                        continue
                    key = (int(dx // OFFSET_BUCKET), int(dy // OFFSET_BUCKET))
                    # normalise direction so A->B and B->A share a bucket
                    key = tuple(sorted((key, (-key[0], -key[1])))[0])
                    offsets[key].append((p1, p2))

            if not offsets:
                continue
            best_key, best_pairs = max(offsets.items(), key=lambda kv: len(kv[1]))
            if len(best_pairs) >= MIN_CLUSTER:
                xs = [p for pair in best_pairs for p in (pair[0][0], pair[1][0])]
                ys = [p for pair in best_pairs for p in (pair[0][1], pair[1][1])]
                out.append(ForensicSignal(
                    code="FORENSIC_COPY_MOVE",
                    title="Duplicated region detected within document",
                    severity=ForensicSeverity.HIGH,
                    confidence=ForensicConfidence.CORROBORATIVE,
                    raw_weight=0.6,
                    reasons=[
                        f"Page {page_idx}: {len(best_pairs)} feature pairs share a "
                        "consistent spatial offset, indicating one region was "
                        "copied and pasted elsewhere on the page (e.g. a cloned "
                        "signature, stamp or digit block). Verify the highlighted "
                        "area is not a legitimate repeated element (logo/gridline).",
                    ],
                    evidence={"cluster_size": len(best_pairs),
                              "region_bbox": [int(min(xs)), int(min(ys)),
                                              int(max(xs)), int(max(ys))],
                              "page": page_idx},
                    analyzer=self.name, document_id=bundle.document_id,
                    page=page_idx,
                ))
        return out
