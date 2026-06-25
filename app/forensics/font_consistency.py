"""
Font consistency analysis.

Two very different reliability regimes, handled explicitly:

DIGITAL_PDF  -> Tier 1 / STRONG.
    PyMuPDF exposes the *actual* font, size, colour and flags for every text
    span. If a salary figure, an account balance or a date is rendered in a
    font/size that nothing else on the page uses, that text was almost
    certainly inserted by hand into an otherwise genuine PDF. This is one of
    the most defensible forgery signals available — we are reading the
    document's own typesetting, not guessing from pixels.

SCANNED_PDF / RASTER_IMAGE -> NOT IMPLEMENTED here (deliberately).
    On a scan there is no font object; detecting font substitution would mean
    OCR-level glyph/stroke classification — a research-grade problem with poor
    precision. Emitting a weak "fonts look different" signal on a noisy scan is
    exactly the kind of false positive that wrongly denies real applicants, so
    we skip it and say so, rather than fake a result.
"""
from __future__ import annotations

from collections import Counter

from .base import (
    DocumentBundle, DocumentKind, ForensicConfidence,
    ForensicSeverity, ForensicSignal,
)


class FontConsistencyForensics:
    name = "font_consistency"

    def applies_to(self, bundle: DocumentBundle) -> bool:
        # Only meaningful where a real font layer exists.
        return bundle.kind == DocumentKind.DIGITAL_PDF and bundle.fitz_doc is not None

    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        out: list[ForensicSignal] = []
        doc = bundle.fitz_doc
        for page_idx in range(doc.page_count):
            page = doc.load_page(page_idx)
            spans = self._collect_spans(page)
            if len(spans) < 8:           # too little text to reason about
                continue

            fonts = Counter(s["font"] for s in spans)
            sizes = Counter(round(s["size"], 1) for s in spans)
            dominant_font, dom_count = fonts.most_common(1)[0]
            total = sum(fonts.values())

            # rare fonts: used by <5% of spans and at most twice — likely inserts
            rare = [f for f, c in fonts.items()
                    if f != dominant_font and c <= max(1, int(0.05 * total))]
            if rare:
                sample = [s for s in spans if s["font"] in rare][:5]
                out.append(ForensicSignal(
                    code="FORENSIC_FONT_OUTLIER",
                    title="Text rendered in an outlier font",
                    severity=ForensicSeverity.HIGH,
                    confidence=ForensicConfidence.STRONG,
                    raw_weight=0.7,
                    reasons=[
                        f"Page {page_idx} is set predominantly in "
                        f"'{dominant_font}' ({dom_count}/{total} spans) but a few "
                        f"spans use {len(rare)} different font(s). Localised font "
                        "changes are a classic sign of values edited into a "
                        "genuine PDF.",
                    ],
                    evidence={"dominant_font": dominant_font,
                              "outlier_fonts": rare,
                              # bbox only — NEVER the text content (PII)
                              "outlier_span_boxes": [s["bbox"] for s in sample],
                              "page": page_idx},
                    analyzer=self.name, document_id=bundle.document_id,
                    page=page_idx,
                ))

            # an isolated font *size* among otherwise uniform body text
            if len(sizes) >= 4 and sizes.most_common(1)[0][1] / total > 0.6:
                odd_sizes = [sz for sz, c in sizes.items() if c == 1]
                if odd_sizes:
                    out.append(ForensicSignal(
                        code="FORENSIC_FONT_SIZE_OUTLIER",
                        title="Isolated font-size outlier in body text",
                        severity=ForensicSeverity.MEDIUM,
                        confidence=ForensicConfidence.CORROBORATIVE,
                        raw_weight=0.4,
                        reasons=[f"Page {page_idx} has uniform body text with "
                                 f"one-off size(s) {odd_sizes}, consistent with a "
                                 "manually overwritten field."],
                        evidence={"outlier_sizes": odd_sizes, "page": page_idx},
                        analyzer=self.name, document_id=bundle.document_id,
                        page=page_idx,
                    ))
        return out

    @staticmethod
    def _collect_spans(page) -> list[dict]:
        spans = []
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    spans.append({
                        "font": span.get("font", "?"),
                        "size": float(span.get("size", 0.0)),
                        "bbox": [round(c, 1) for c in span.get("bbox", [])],
                    })
        return spans
