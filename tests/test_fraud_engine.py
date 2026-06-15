"""Pure fraud-engine tests — no DB, no app wiring (the engine is standalone)."""
from app.fraud_engine import RuleContext, run_rules, score
from app.fraud_engine.scorer import score_to_tier
from app.fraud_engine.validators import is_valid_aadhaar, is_valid_pan


def _ctx(**kw) -> RuleContext:
    base = {"document_id": "d1", "document_type": "SALARY_SLIP"}
    base.update(kw)
    return RuleContext(**base)


# ── Validators ──

def test_pan_validator():
    assert is_valid_pan("ABCDE1234F")
    assert not is_valid_pan("ABCD1234F")   # too short
    assert not is_valid_pan("ABCDE12345")  # wrong final char
    assert not is_valid_pan(None)


def test_aadhaar_verhoeff():
    # Build a valid 12-digit Aadhaar: find the check digit that validates an 11-digit base.
    base = "23412341234"  # leading 2 (Aadhaar never starts 0/1)
    valid = next(base + str(d) for d in range(10) if is_valid_aadhaar(base + str(d)))
    assert is_valid_aadhaar(valid)
    # Flipping the last digit breaks the checksum.
    other = valid[:-1] + str((int(valid[-1]) + 1) % 10)
    assert not is_valid_aadhaar(other)
    assert not is_valid_aadhaar("1234")  # wrong length


# ── Rules ──

def test_net_exceeds_gross_is_critical():
    results = run_rules(_ctx(ocr_confidence=0.95, entities={"NET_SALARY": ["80000"], "GROSS_SALARY": ["65000"]}))
    types = {r.signal_type for r in results}
    assert "NET_EXCEEDS_GROSS" in types
    crit = next(r for r in results if r.signal_type == "NET_EXCEEDS_GROSS")
    assert crit.severity == "CRITICAL"


def test_invalid_pan_format_fires():
    results = run_rules(_ctx(entities={"PAN": ["NOTAPAN"]}))
    assert any(r.signal_type == "INVALID_PAN_FORMAT" for r in results)


def test_valid_pan_no_signal():
    results = run_rules(_ctx(entities={"PAN": ["ABCDE1234F"]}))
    assert not any(r.signal_type == "INVALID_PAN_FORMAT" for r in results)


def test_low_ocr_confidence_severity_bands():
    # Use a non-salary doc type so only the OCR-confidence rule is in play.
    assert any(r.signal_type == "LOW_OCR_CONFIDENCE" and r.severity == "HIGH"
               for r in run_rules(_ctx(document_type="PAN", ocr_confidence=0.3)))
    assert any(r.signal_type == "LOW_OCR_CONFIDENCE" and r.severity == "MEDIUM"
               for r in run_rules(_ctx(document_type="PAN", ocr_confidence=0.5)))
    assert not run_rules(_ctx(document_type="PAN", ocr_confidence=0.9))


def test_duplicate_document_signal():
    results = run_rules(_ctx(ocr_confidence=0.95, duplicate_of_document_id="other-doc"))
    assert any(r.signal_type == "DUPLICATE_DOCUMENT" for r in results)


# ── Scoring ──

def test_score_to_tier_thresholds():
    assert score_to_tier(0) == "LOW"
    assert score_to_tier(45) == "MEDIUM"
    assert score_to_tier(70) == "HIGH"
    assert score_to_tier(90) == "CRITICAL"


def test_score_aggregates_and_caps_at_100():
    ctx = _ctx(ocr_confidence=0.3, entities={"NET_SALARY": ["80000"], "GROSS_SALARY": ["65000"], "PAN": ["BAD"]})
    outcome = score(run_rules(ctx))
    assert 0 < outcome.total_score <= 100
    assert outcome.risk_tier in {"MEDIUM", "HIGH", "CRITICAL"}
    assert outcome.reasons  # explainable breakdown present
