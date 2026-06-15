"""Indian-format validators used by identity rules. Pure functions, no dependencies."""
from __future__ import annotations

import re

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]{2}$")

# Verhoeff multiplication (d), permutation (p) and inverse (inv) tables.
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 2, 4, 9, 1, 3, 6, 7],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def is_valid_pan(pan: str | None) -> bool:
    return bool(pan) and bool(_PAN_RE.match(pan.strip().upper()))


def is_valid_ifsc(ifsc: str | None) -> bool:
    return bool(ifsc) and bool(_IFSC_RE.match(ifsc.strip().upper()))


def is_valid_gstin(gstin: str | None) -> bool:
    return bool(gstin) and bool(_GSTIN_RE.match(gstin.strip().upper()))


def is_valid_aadhaar(aadhaar: str | None) -> bool:
    """12 digits with a valid Verhoeff checksum (the last digit)."""
    if not aadhaar:
        return False
    digits = re.sub(r"\s", "", aadhaar)
    if not (len(digits) == 12 and digits.isdigit()):
        return False
    # Aadhaar never starts with 0 or 1.
    if digits[0] in "01":
        return False
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0
