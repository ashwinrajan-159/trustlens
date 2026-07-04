"""OCR service with a pluggable engine.

Engine selection is layered so the heavy native deps are optional and tests are
hermetic:

1. A test/override engine (``set_engine_override``) wins if set.
2. ``PaddleOCREngine`` — primary in production (imported lazily; only used if installed).
3. ``PyMuPDFEngine`` — fast path + fallback for digital PDFs with an embedded text layer
   (no real OCR needed; fixed 0.85 confidence per spec §6).

Engines never raise into the caller for *content* problems — they return a low/zero
confidence result; only genuinely unreadable input raises ``OcrError`` so the pipeline
can mark the document FAILED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.core.exceptions import TrustLensError
from app.core.logging import get_logger

log = get_logger(__name__)

PYMUPDF_TEXT_CONFIDENCE = 0.85


class OcrError(TrustLensError):
    """OCR could not process the document at all."""

    status_code = 422
    code = "ocr_failed"


@dataclass
class OcrOutput:
    text: str
    confidence: float
    page_count: int
    engine: str
    model_version: str
    pages: list[dict] = field(default_factory=list)


class OcrEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def run(self, data: bytes, content_type: str) -> OcrOutput: ...


class PyMuPDFEngine:
    """Digital-PDF text extraction via PyMuPDF (``fitz``). No OCR — pulls the embedded
    text layer, which is exact when present (scanned PDFs yield little/no text → low
    confidence so a real OCR engine is preferred upstream)."""

    name = "pymupdf"

    def is_available(self) -> bool:
        try:
            import fitz  # noqa: F401
        except ImportError:
            return False
        return True

    def run(self, data: bytes, content_type: str) -> OcrOutput:
        import fitz

        if "pdf" not in content_type:
            # PyMuPDF can open images too, but it won't OCR them — defer to Paddle.
            return OcrOutput("", 0.0, 0, self.name, getattr(fitz, "__version__", "pymupdf"), [])
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            raise OcrError("Could not open PDF") from exc

        pages: list[dict] = []
        chunks: list[str] = []
        for i, page in enumerate(doc):
            text = page.get_text() or ""
            chunks.append(text)
            pages.append({"page": i + 1, "chars": len(text)})
        full = "\n".join(chunks).strip()
        confidence = PYMUPDF_TEXT_CONFIDENCE if full else 0.0
        return OcrOutput(
            text=full,
            confidence=confidence,
            page_count=doc.page_count,
            engine=self.name,
            model_version=getattr(fitz, "__version__", "unknown"),
            pages=pages,
        )


class PaddleOCREngine:
    """Production OCR for scanned docs/images. Lazy singleton; only used if installed."""

    name = "paddleocr"
    _reader = None

    def is_available(self) -> bool:
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_reader(self):
        if PaddleOCREngine._reader is None:
            from paddleocr import PaddleOCR

            # Constructor kwargs shifted across PaddleOCR releases (show_log removed
            # in 2.8+, use_angle_cls renamed later) — degrade to what this version takes.
            for kwargs in (
                {"use_angle_cls": True, "lang": "en", "show_log": False},
                {"use_angle_cls": True, "lang": "en"},
                {"lang": "en"},
            ):
                try:
                    PaddleOCREngine._reader = PaddleOCR(**kwargs)
                    break
                except (TypeError, ValueError):
                    continue
            if PaddleOCREngine._reader is None:
                raise OcrError("PaddleOCR constructor rejected all known signatures")
        return PaddleOCREngine._reader

    def run(self, data: bytes, content_type: str) -> OcrOutput:  # pragma: no cover - needs native dep
        import io

        import numpy as np
        from PIL import Image

        reader = self._get_reader()
        images: list = []
        if "pdf" in content_type:
            import fitz

            doc = fitz.open(stream=data, filetype="pdf")
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                images.append(np.array(img))
        else:
            images.append(np.array(Image.open(io.BytesIO(data)).convert("RGB")))

        pages, chunks, confs = [], [], []
        for idx, img in enumerate(images):
            try:
                result = reader.ocr(img, cls=True) or []
            except TypeError:  # cls kwarg removed in newer releases
                result = reader.ocr(img) or []
            lines = result[0] if result else []
            page_text = []
            for line in lines:
                txt, conf = line[1][0], float(line[1][1])
                page_text.append(txt)
                confs.append(conf)
            chunks.append("\n".join(page_text))
            pages.append({"page": idx + 1, "lines": len(lines)})
        full = "\n".join(chunks).strip()
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return OcrOutput(full, avg_conf, len(images), self.name, "paddleocr", pages)


_override: OcrEngine | None = None


def set_engine_override(engine: OcrEngine | None) -> None:
    """Test/DI hook to force a specific engine (e.g. a fake)."""
    global _override
    _override = engine


def get_engine() -> OcrEngine:
    """Pick the best available engine: Paddle (scanned/images) → PyMuPDF (digital PDF)."""
    if _override is not None:
        return _override
    for engine in (PaddleOCREngine(), PyMuPDFEngine()):
        if engine.is_available():
            return engine
    raise OcrError("No OCR engine available")


def run_ocr(data: bytes, content_type: str) -> OcrOutput:
    engine = get_engine()
    log.info("ocr.run", engine=engine.name, content_type=content_type, bytes=len(data))
    return engine.run(data, content_type)
