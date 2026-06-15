"""File content validation by magic bytes (#4).

The client-supplied Content-Type is advisory only; we verify the actual leading bytes
and reject any mismatch before the file is stored or handed to OCR workers.
"""
from __future__ import annotations

# (declared_content_type) -> list of acceptable leading-byte signatures.
_SIGNATURES: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF-"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/jpg": [b"\xff\xd8\xff"],
    "image/tiff": [b"II*\x00", b"MM\x00*"],
}

ALLOWED_CONTENT_TYPES = set(_SIGNATURES.keys())


def detect_content_type(head: bytes) -> str | None:
    """Return the content type implied by the leading bytes, or None if unrecognised."""
    for ctype, sigs in _SIGNATURES.items():
        if any(head.startswith(sig) for sig in sigs):
            return ctype
    return None


def content_matches(declared: str, head: bytes) -> bool:
    """True if the real magic bytes are consistent with the declared content type."""
    sigs = _SIGNATURES.get(declared)
    if not sigs:
        return False
    return any(head.startswith(sig) for sig in sigs)
