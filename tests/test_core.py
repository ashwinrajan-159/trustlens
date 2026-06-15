"""Unit tests for core primitives: hashing, JWT, encryption, masking."""
import pytest

from app.core.encryption import (
    decrypt,
    encrypt,
    mask_aadhaar,
    mask_account,
    mask_pan,
)
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("supersecret1")
    assert h != "supersecret1"
    assert verify_password("supersecret1", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip_and_type_enforcement():
    access = create_access_token("user-1", "CUSTOMER", fid="fam-1")
    payload = decode_token(access, expected_type="access")
    assert payload["sub"] == "user-1"
    assert payload["fid"] == "fam-1"
    refresh = create_refresh_token("user-1", "CUSTOMER", fid="fam-1", jti="j1")
    with pytest.raises(AuthenticationError):
        decode_token(refresh, expected_type="access")


def test_encryption_roundtrip():
    ct = encrypt("ABCDE1234F")
    assert ct != "ABCDE1234F"
    assert decrypt(ct) == "ABCDE1234F"
    assert decrypt(None) is None


def test_masking():
    assert mask_pan("ABCDE1234F") == "XXXXXE1234F"
    assert mask_aadhaar("1234 5678 9012") == "XXXX XXXX 9012"
    assert mask_account("000123456789").endswith("6789")
    assert mask_account("000123456789").startswith("X")
