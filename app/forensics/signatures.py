"""
Signature verification — split honestly into what's achievable offline vs not.

TRUE signature verification ("is this really the applicant's signature?") needs
*enrolled reference signatures* for that person. You don't have those at intake,
so we do NOT pretend to verify authenticity. What we CAN do well, with no
reference data, are two intra-application consistency checks that catch common
forgeries:

  A. Pixel-identical reuse: the *same* signature image pasted onto multiple
     documents in one application. A real person re-signing produces natural
     variation; an exact match means copy-paste. This is STRONG.

  B. Inconsistency: signatures on documents that should share a signer differ
     beyond plausible natural variation. CORROBORATIVE (handwriting varies).

IMPLEMENTATION NOTE — signature *localisation*: robustly finding the signature
region on arbitrary documents is itself a model-grade problem. Below we expose a
`signature_crops` hook in bundle.context that your extraction layer should
populate (e.g. from template coordinates per document type, or a small detector).
If it's absent, this analyzer cleanly reports "skipped" rather than guessing.
"""
from __future__ import annotations

from itertools import combinations

from .base import (
    DocumentBundle, ForensicConfidence, ForensicSeverity, ForensicSignal,
)

IDENTICAL_SSIM = 0.97     # >= this between two crops == copy-paste
DIVERGENT_SSIM = 0.45     # <= this between two "same-signer" crops == inconsistent


class SignatureForensics:
    name = "signatures"

    def applies_to(self, bundle: DocumentBundle) -> bool:
        # Needs pre-extracted signature crops for this application.
        return bool(bundle.context.get("signature_crops"))

    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        crops = bundle.context.get("signature_crops") or []
        if len(crops) < 2:
            return []
        try:
            import cv2
            import numpy as np
            from skimage.metrics import structural_similarity as ssim
        except Exception:
            return []

        out: list[ForensicSignal] = []
        norm = []
        for c in crops:
            g = cv2.cvtColor(c["image"], cv2.COLOR_BGR2GRAY) if c["image"].ndim == 3 else c["image"]
            norm.append((c.get("document_id"), cv2.resize(g, (200, 80))))

        for (id_a, a), (id_b, b) in combinations(norm, 2):
            score = float(ssim(a, b))
            if score >= IDENTICAL_SSIM:
                out.append(ForensicSignal(
                    code="FORENSIC_SIGNATURE_COPY_PASTE",
                    title="Identical signature reused across documents",
                    severity=ForensicSeverity.HIGH,
                    confidence=ForensicConfidence.STRONG,
                    raw_weight=0.75,
                    reasons=["Two documents in this application carry a pixel-near-"
                             "identical signature. Genuine re-signing always varies; "
                             "an exact match indicates a copied/pasted signature."],
                    evidence={"document_ids": [id_a, id_b], "ssim": round(score, 3)},
                    analyzer=self.name, document_id=bundle.document_id,
                ))
            elif score <= DIVERGENT_SSIM:
                out.append(ForensicSignal(
                    code="FORENSIC_SIGNATURE_INCONSISTENT",
                    title="Signatures differ across the application",
                    severity=ForensicSeverity.MEDIUM,
                    confidence=ForensicConfidence.CORROBORATIVE,
                    raw_weight=0.45,
                    reasons=["Signatures on different documents diverge more than "
                             "typical natural variation. May indicate documents "
                             "signed by different people. Handwriting varies — "
                             "confirm before acting."],
                    evidence={"document_ids": [id_a, id_b], "ssim": round(score, 3)},
                    analyzer=self.name, document_id=bundle.document_id,
                ))
        return out
