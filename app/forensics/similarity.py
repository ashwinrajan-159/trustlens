"""
Document similarity & reuse detection — Tier 1 / STRONG (for near-exact reuse).

This is the single highest-value forensic check for *organised* fraud, and it
plugs straight into your existing NetworkX fraud-ring graph: when the same
document (or a lightly re-rendered copy) shows up across different applications,
that's a coordinated-fraud edge, not a per-document curiosity.

Method: a perceptual hash (pHash) per page. pHash is robust to re-compression,
mild resizing and format changes but changes sharply when content changes — so
near-identical Hamming distance == "same document reused". We persist hashes via
a HashStore (your repositories layer) so comparison is cross-application and
fully offline.

We deliberately keep two thresholds:
  - EXACT_MAX_DIST  -> STRONG signal (reuse), can stand on its own
  - NEAR_MAX_DIST   -> CORROBORATIVE (template reuse / same source)
"""
from __future__ import annotations

from .base import (
    DocumentBundle, ForensicConfidence, ForensicSeverity, ForensicSignal, HashStore,
)

EXACT_MAX_DIST = 4      # near-identical render
NEAR_MAX_DIST = 12      # same template / same underlying scan, re-exported


def _phash_hex(image_bgr) -> str | None:
    try:
        import imagehash
        from PIL import Image
        import cv2
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        return str(imagehash.phash(Image.fromarray(rgb), hash_size=16))
    except Exception:
        return None


def _hamming(a_hex: str, b_hex: str) -> int:
    a, b = int(a_hex, 16), int(b_hex, 16)
    return bin(a ^ b).count("1")


class SimilarityForensics:
    name = "similarity"

    def __init__(self, store: HashStore):
        self.store = store

    def applies_to(self, bundle: DocumentBundle) -> bool:
        return bool(bundle.page_images)

    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        out: list[ForensicSignal] = []
        for page_idx, img in enumerate(bundle.page_images):
            phash = _phash_hex(img)
            if phash is None:
                continue

            matches = self.store.find_similar(phash, max_distance=NEAR_MAX_DIST) or []
            # exclude this application's own documents
            matches = [m for m in matches if m.get("application_id") != bundle.application_id]

            if matches:
                best = min(matches, key=lambda m: _hamming(phash, m["phash_hex"]))
                dist = _hamming(phash, best["phash_hex"])
                cross_apps = sorted({m["application_id"] for m in matches})

                if dist <= EXACT_MAX_DIST:
                    out.append(ForensicSignal(
                        code="FORENSIC_DOCUMENT_REUSED_ACROSS_APPS",
                        title="Same document submitted in other application(s)",
                        severity=ForensicSeverity.CRITICAL,
                        confidence=ForensicConfidence.STRONG,
                        raw_weight=0.9,
                        reasons=[
                            "A near-identical copy of this page was submitted in "
                            f"{len(cross_apps)} other application(s). Strong "
                            "indicator of a coordinated fraud ring or recycled "
                            "supporting documents.",
                        ],
                        evidence={"hamming_distance": dist,
                                  "linked_application_ids": cross_apps[:25],
                                  "page": page_idx},
                        analyzer=self.name, document_id=bundle.document_id,
                        page=page_idx,
                    ))
                else:
                    out.append(ForensicSignal(
                        code="FORENSIC_DOCUMENT_TEMPLATE_REUSE",
                        title="Document closely matches one in another application",
                        severity=ForensicSeverity.MEDIUM,
                        confidence=ForensicConfidence.CORROBORATIVE,
                        raw_weight=0.5,
                        reasons=["This page is highly similar to a document in "
                                 f"{len(cross_apps)} other application(s) — same "
                                 "template or source. Review for shared fabrication."],
                        evidence={"hamming_distance": dist,
                                  "linked_application_ids": cross_apps[:25],
                                  "page": page_idx},
                        analyzer=self.name, document_id=bundle.document_id,
                        page=page_idx,
                    ))

            # persist AFTER comparing so we don't match ourselves
            self.store.save(document_id=bundle.document_id,
                            application_id=bundle.application_id,
                            phash_hex=phash, extra={"page": page_idx})
        return out
