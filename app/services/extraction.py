"""Layout-agnostic entity extraction from OCR text (spec §6).

Design goals:
- **Format-agnostic.** Handle label/value on the same line, on adjacent lines, with
  parenthetical suffixes (``Net Pay (computed):``) and any currency prefix
  (``INR``/``₹``/``Rs.``). Ambiguous labels are anchored to line-start so
  ``Total Income`` does not match inside ``Gross Total Income``.
- **Deterministic-first.** Labeled regex is preferred; spaCy NER is an optional, lazily
  imported fallback for names only.
- **Routed by document type**, with a global identity sweep (PAN/Aadhaar/IFSC/GSTIN can
  appear on many document types) that always runs.

Returns ``EntityDraft`` objects (pure data, no DB/PII handling) — the task layer decides
encryption + masking.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.enums import DocumentType, EntityType, ExtractionMethod

# ── Validators / sweep patterns (Indian formats) ──
PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]{2}\b")
DATE_RE = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
_AMOUNT_RE = re.compile(r"(?:inr|rs\.?|₹)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)


@dataclass
class EntityDraft:
    entity_type: EntityType
    value: str
    confidence: float = 0.8
    method: ExtractionMethod = ExtractionMethod.REGEX
    source_page: int | None = None


# ── Text helpers ──

def parse_amount(s: str) -> float | None:
    m = _AMOUNT_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def search_labeled_value(
    text: str, labels: list[str], *, anchor_start: bool = False
) -> tuple[str | None, int | None]:
    """Find the value following any of ``labels`` (same line, else next non-empty line).

    Strips a leading parenthetical suffix and ``: - =`` separators. With
    ``anchor_start`` the label must begin the line (after optional whitespace) so short
    labels don't match as substrings of longer ones.
    """
    lines = text.splitlines()
    lowered = [ln.lower() for ln in lines]
    for i, low in enumerate(lowered):
        for label in labels:
            ll = label.lower()
            idx = low.find(ll)
            if idx == -1:
                continue
            if anchor_start and lines[i][:idx].strip() != "":
                continue
            after = lines[i][idx + len(label):]
            after = re.sub(r"^\s*\([^)]*\)", "", after)  # drop "(computed)" etc.
            after = after.lstrip(" :\t-=").strip()
            if after:
                return after, i + 1
            # Value on a following line.
            for j in range(i + 1, min(i + 3, len(lines))):
                nxt = lines[j].strip()
                if nxt:
                    return nxt, j + 1
    return None, None


def _labeled_amount(text: str, labels: list[str], etype: EntityType) -> EntityDraft | None:
    raw, page = search_labeled_value(text, labels, anchor_start=True)
    if raw is None:
        return None
    amount = parse_amount(raw)
    if amount is None:
        return None
    return EntityDraft(etype, f"{amount:.2f}", confidence=0.85, source_page=page)


def _labeled_text(text: str, labels: list[str], etype: EntityType, *, conf: float = 0.8) -> EntityDraft | None:
    raw, page = search_labeled_value(text, labels)
    if not raw:
        return None
    # Keep it to a single line value, trimmed.
    return EntityDraft(etype, raw.split("  ")[0].strip(", ."), confidence=conf, source_page=page)


# ── Global identity sweep (runs for every document type) ──

def _identity_sweep(text: str) -> list[EntityDraft]:
    drafts: list[EntityDraft] = []
    for m in dict.fromkeys(PAN_RE.findall(text)):
        drafts.append(EntityDraft(EntityType.PAN, m, confidence=0.95))
    for m in dict.fromkeys(IFSC_RE.findall(text)):
        drafts.append(EntityDraft(EntityType.IFSC, m, confidence=0.9))
    for m in dict.fromkeys(GSTIN_RE.findall(text)):
        drafts.append(EntityDraft(EntityType.GSTIN, m, confidence=0.9))
    for m in dict.fromkeys(AADHAAR_RE.findall(text)):
        digits = re.sub(r"\s", "", m)
        # Exclude 12-digit strings that are actually account numbers etc. is hard here;
        # Verhoeff validation lands in Phase 4. Keep as a candidate.
        drafts.append(EntityDraft(EntityType.AADHAAR, digits, confidence=0.7))
    return drafts


def _name_via_labels(text: str) -> EntityDraft | None:
    return _labeled_text(
        text,
        ["Employee Name", "Name of Employee", "Name of Applicant", "Candidate Name", "Name"],
        EntityType.NAME,
        conf=0.8,
    )


def _name_via_ner(text: str) -> EntityDraft | None:  # pragma: no cover - optional dep
    try:
        import spacy
    except ImportError:
        return None
    try:
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        return None
    doc = nlp(text[:2000])
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return EntityDraft(EntityType.NAME, ent.text.strip(), confidence=0.6, method=ExtractionMethod.NER)
    return None


def _dob(text: str) -> EntityDraft | None:
    raw, page = search_labeled_value(text, ["Date of Birth", "DOB", "D.O.B"])
    if raw:
        m = DATE_RE.search(raw)
        if m:
            return EntityDraft(EntityType.DOB, m.group(0), confidence=0.85, source_page=page)
    return None


# ── Per-document-type extractors ──

def _extract_salary_slip(text: str) -> list[EntityDraft]:
    out: list[EntityDraft] = []
    for d in (
        _name_via_labels(text),
        _labeled_text(text, ["Employer", "Company Name", "Company", "Organisation"], EntityType.EMPLOYER),
        _labeled_text(text, ["Designation", "Title"], EntityType.DESIGNATION),
        _labeled_amount(text, ["Net Pay", "Net Salary", "Net Amount", "Take Home"], EntityType.NET_SALARY),
        _labeled_amount(text, ["Gross Salary", "Gross Earnings", "Gross Pay", "Total Earnings"], EntityType.GROSS_SALARY),
        _labeled_text(text, ["Pay Period", "Salary for the Month", "Month", "Pay Date"], EntityType.PAY_PERIOD),
    ):
        if d:
            out.append(d)
    return out


def _extract_pan_card(text: str) -> list[EntityDraft]:
    out: list[EntityDraft] = []
    for d in (_name_via_labels(text), _dob(text)):
        if d:
            out.append(d)
    return out


def _extract_aadhaar(text: str) -> list[EntityDraft]:
    out: list[EntityDraft] = []
    for d in (_name_via_labels(text), _dob(text)):
        if d:
            out.append(d)
    g, page = search_labeled_value(text, ["Gender", "Sex"])
    if g:
        out.append(EntityDraft(EntityType.GENDER, g.split()[0], confidence=0.7, source_page=page))
    return out


def _extract_bank_statement(text: str) -> list[EntityDraft]:
    out: list[EntityDraft] = []
    acc, page = search_labeled_value(text, ["Account Number", "Account No", "A/c No", "A/c Number"])
    if acc:
        digits = re.sub(r"\D", "", acc)
        if 9 <= len(digits) <= 18:
            out.append(EntityDraft(EntityType.ACCOUNT_NUMBER, digits, confidence=0.85, source_page=page))
    for d in (
        _name_via_labels(text),
        _labeled_text(text, ["Bank Name", "Bank"], EntityType.BANK_NAME),
        _labeled_amount(text, ["Closing Balance", "Available Balance", "Balance"], EntityType.CLOSING_BALANCE),
    ):
        if d:
            out.append(d)
    return out


def _extract_form16(text: str) -> list[EntityDraft]:
    out: list[EntityDraft] = []
    for d in (
        _labeled_text(text, ["Name of the Employer", "Employer"], EntityType.EMPLOYER),
        _labeled_amount(text, ["Gross Salary", "Gross Total Income"], EntityType.GROSS_SALARY),
    ):
        if d:
            out.append(d)
    return out


_ROUTES = {
    DocumentType.SALARY_SLIP: _extract_salary_slip,
    DocumentType.PAN: _extract_pan_card,
    DocumentType.AADHAAR: _extract_aadhaar,
    DocumentType.BANK_STATEMENT: _extract_bank_statement,
    DocumentType.FORM_16: _extract_form16,
}


def extract(document_type: DocumentType, text: str) -> list[EntityDraft]:
    """Extract entities for a document. Always runs the identity sweep, then the
    type-specific extractor; de-dups on (type, value), keeping the highest confidence."""
    if not text or not text.strip():
        return []
    drafts = _identity_sweep(text)
    route = _ROUTES.get(document_type)
    if route:
        drafts.extend(route(text))
    # Names: labeled first, NER fallback only if nothing labeled was found.
    if not any(d.entity_type == EntityType.NAME for d in drafts):
        ner = _name_via_ner(text)
        if ner:
            drafts.append(ner)

    best: dict[tuple, EntityDraft] = {}
    for d in drafts:
        key = (d.entity_type, d.value)
        if key not in best or d.confidence > best[key].confidence:
            best[key] = d
    return list(best.values())
