"""TOTP-based MFA for privileged roles (#25).

Secrets are generated server-side, stored encrypted (``User.mfa_secret`` is an
``EncryptedString``), and only marked enabled after the user proves possession by
submitting a valid code. Customers are exempt; analyst/admin logins are gated.
"""
from __future__ import annotations

import pyotp

_ISSUER = "TrustLens AI"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=_ISSUER)


def verify_totp(secret: str | None, code: str | None) -> bool:
    if not secret or not code:
        return False
    # valid_window=1 tolerates ~30s clock skew on either side.
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
