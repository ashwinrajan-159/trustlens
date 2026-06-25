"""
Metadata forensics — Tier 1 / STRONG.

Cheap, deterministic, hard to argue with in front of a regulator: we are
reading what the producing software *wrote about itself*. No pixels, no ML.

PDF: PyMuPDF .metadata + raw XMP. We flag
  - known editing software in the Producer/Creator (Photoshop, GIMP, etc.)
  - modification date earlier than creation date (physically impossible)
  - a large gap between creation and last modification on a doc that claims to
    be a freshly generated statement
  - missing producer on a document type that is always machine-generated

Image: EXIF via Pillow. We flag editing-software tags, and the *absence* of any
camera metadata on something presented as a photographed/scanned original
(a strong screenshot/export tell — see also screenshot.py).

Everything emitted is PII-safe: we never put document *content* in evidence,
only metadata fields.
"""
from __future__ import annotations

import re
from datetime import datetime

from .base import (
    DocumentBundle, DocumentKind, ForensicConfidence,
    ForensicSeverity, ForensicSignal,
)

# Substrings (lower-cased) that indicate a raster/vector editor touched the file.
# Tune to your environment; bank back-office tools should be allow-listed.
EDITING_SOFTWARE = (
    "photoshop", "gimp", "inkscape", "illustrator", "coreldraw", "paint.net",
    "pixlr", "snapseed", "picsart", "canva", "figma", "affinity",
    "ms paint", "photoscape", "facetune",
)
# PDF producers that legitimately *edit* (vs. generate) — softer flag.
PDF_EDIT_PRODUCERS = ("acrobat", "foxit", "nitro", "pdfescape", "ilovepdf", "smallpdf")


def _parse_pdf_date(value: str | None) -> datetime | None:
    if not value:
        return None
    # PyMuPDF gives e.g. "D:20230115120000+05'30'"
    m = re.match(r"D?:?(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", value)
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(g) if g else 0 for g in m.groups())
    try:
        return datetime(y, mo, d, hh or 0, mm or 0, ss or 0)
    except ValueError:
        return None


class MetadataForensics:
    name = "metadata"

    def applies_to(self, bundle: DocumentBundle) -> bool:
        return bundle.kind != DocumentKind.UNKNOWN

    def analyze(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        if bundle.fitz_doc is not None:
            return self._pdf(bundle)
        return self._image(bundle)

    # ------------------------------------------------------------------ PDF
    def _pdf(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        out: list[ForensicSignal] = []
        meta = dict(bundle.fitz_doc.metadata or {})
        producer = (meta.get("producer") or "").strip()
        creator = (meta.get("creator") or "").strip()
        blob = f"{producer} {creator}".lower()

        hit = next((s for s in EDITING_SOFTWARE if s in blob), None)
        if hit:
            out.append(ForensicSignal(
                code="FORENSIC_METADATA_EDIT_SOFTWARE",
                title="Document produced/edited by image-editing software",
                severity=ForensicSeverity.HIGH,
                confidence=ForensicConfidence.STRONG,
                raw_weight=0.8,
                reasons=[
                    f"PDF metadata names an image editor ('{hit}'). Genuine bank, "
                    "salary and government PDFs are emitted by reporting/print "
                    "stacks, not by raster editors.",
                ],
                evidence={"producer": producer, "creator": creator, "matched": hit},
                analyzer=self.name, document_id=bundle.document_id,
            ))
        elif any(s in blob for s in PDF_EDIT_PRODUCERS):
            out.append(ForensicSignal(
                code="FORENSIC_METADATA_PDF_REEDITED",
                title="Document re-saved by a PDF editor",
                severity=ForensicSeverity.LOW,
                confidence=ForensicConfidence.CORROBORATIVE,
                raw_weight=0.35,
                reasons=["A PDF-editing tool last wrote this file. Benign on its "
                         "own; meaningful if combined with content anomalies."],
                evidence={"producer": producer, "creator": creator},
                analyzer=self.name, document_id=bundle.document_id,
            ))

        created = _parse_pdf_date(meta.get("creationDate"))
        modified = _parse_pdf_date(meta.get("modDate"))
        if created and modified:
            if modified < created:
                out.append(ForensicSignal(
                    code="FORENSIC_METADATA_IMPOSSIBLE_TIMELINE",
                    title="Modification date precedes creation date",
                    severity=ForensicSeverity.HIGH,
                    confidence=ForensicConfidence.STRONG,
                    raw_weight=0.75,
                    reasons=["The file's last-modified timestamp is earlier than "
                             "its creation timestamp — physically impossible for "
                             "an untouched original."],
                    evidence={"creationDate": meta.get("creationDate"),
                              "modDate": meta.get("modDate")},
                    analyzer=self.name, document_id=bundle.document_id,
                ))
            elif (modified - created).days >= 1:
                out.append(ForensicSignal(
                    code="FORENSIC_METADATA_LATE_MODIFICATION",
                    title="Document modified well after creation",
                    severity=ForensicSeverity.LOW,
                    confidence=ForensicConfidence.CORROBORATIVE,
                    raw_weight=0.3,
                    reasons=[f"File was modified {(modified - created).days} day(s) "
                             "after creation. Statements are usually generated and "
                             "submitted unchanged."],
                    evidence={"creationDate": meta.get("creationDate"),
                              "modDate": meta.get("modDate")},
                    analyzer=self.name, document_id=bundle.document_id,
                ))

        if not producer and not creator:
            out.append(ForensicSignal(
                code="FORENSIC_METADATA_STRIPPED",
                title="Producer/creator metadata stripped",
                severity=ForensicSeverity.LOW,
                confidence=ForensicConfidence.CORROBORATIVE,
                raw_weight=0.3,
                reasons=["No producer/creator metadata. Often the result of "
                         "exporting/flattening a doc to hide its editing history."],
                evidence={},
                analyzer=self.name, document_id=bundle.document_id,
            ))
        return out

    # ---------------------------------------------------------------- image
    def _image(self, bundle: DocumentBundle) -> list[ForensicSignal]:
        out: list[ForensicSignal] = []
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS
            import io
            img = Image.open(io.BytesIO(bundle.raw_bytes))
            exif_raw = getattr(img, "_getexif", lambda: None)() or {}
            exif = {TAGS.get(k, k): v for k, v in exif_raw.items()}
        except Exception as e:  # graceful degrade — never crash the pipeline
            return [ForensicSignal(
                code="FORENSIC_METADATA_UNREADABLE",
                title="Image metadata could not be read",
                severity=ForensicSeverity.INFO,
                confidence=ForensicConfidence.SUGGESTIVE,
                raw_weight=0.1,
                reasons=[f"EXIF parse failed ({type(e).__name__}); other "
                         "analyzers still ran."],
                analyzer=self.name, document_id=bundle.document_id,
            )]

        software = str(exif.get("Software", "")).lower()
        hit = next((s for s in EDITING_SOFTWARE if s in software), None)
        if hit:
            out.append(ForensicSignal(
                code="FORENSIC_METADATA_EDIT_SOFTWARE",
                title="Image last saved by editing software",
                severity=ForensicSeverity.HIGH,
                confidence=ForensicConfidence.STRONG,
                raw_weight=0.8,
                reasons=[f"EXIF 'Software' tag names an editor ('{hit}')."],
                evidence={"software": exif.get("Software"), "matched": hit},
                analyzer=self.name, document_id=bundle.document_id,
            ))

        # No camera origin on an image presented as a scan/photo of an original.
        has_camera = any(k in exif for k in ("Make", "Model", "LensModel"))
        has_capture_time = "DateTimeOriginal" in exif
        if not has_camera and not has_capture_time:
            out.append(ForensicSignal(
                code="FORENSIC_METADATA_NO_CAPTURE_ORIGIN",
                title="No camera/capture metadata",
                severity=ForensicSeverity.LOW,
                # SUGGESTIVE, not CORROBORATIVE: the overwhelming majority of
                # legitimately-uploaded ID images (scans, app exports, re-saved
                # PNGs) carry no EXIF. On its own this is normal, not suspicious —
                # it only matters as corroboration for the screenshot analyzer.
                confidence=ForensicConfidence.SUGGESTIVE,
                raw_weight=0.35,
                reasons=["Image carries no camera make/model or capture time. "
                         "Consistent with a screenshot, screen-export or a "
                         "synthetically generated image rather than a photographed "
                         "original. See screenshot analyzer for corroboration."],
                evidence={"exif_keys": sorted(map(str, exif.keys()))[:20]},
                analyzer=self.name, document_id=bundle.document_id,
            ))
        return out
