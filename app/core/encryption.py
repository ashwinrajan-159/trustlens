"""Field-level PII encryption + masking.

Dev uses Fernet (AES-128-CBC + HMAC). In production the key comes from AWS KMS/HSM
with rotation — the public surface (``encrypt``/``decrypt``) stays identical so the
backend can be swapped without touching models.

The ``EncryptedString`` SQLAlchemy ``TypeDecorator`` transparently encrypts on the way
into the DB and decrypts on the way out, so sensitive columns are ciphertext at rest.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import String, TypeDecorator

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class _Cipher:
    """Lazy MultiFernet wrapper supporting key rotation (#19).

    Encryption always uses the *primary* (first) key; decryption tries the primary
    then any ``fernet_old_keys`` in order. To rotate: generate a new key, make it the
    primary, move the previous primary into ``FERNET_OLD_KEYS``, then run a background
    re-encrypt sweep (re-save rows) to migrate ciphertext onto the new key.
    """

    _mf: MultiFernet | None = None

    @classmethod
    def _get(cls) -> MultiFernet:
        if cls._mf is None:
            primary = settings.fernet_key
            if not primary:
                if settings.is_production:  # belt-and-braces; config validator also guards
                    raise RuntimeError("FERNET_KEY must be set in production")
                # Dev/test convenience only — ephemeral key, loudly flagged.
                primary = Fernet.generate_key().decode()
                settings.fernet_key = primary
                log.warning("encryption.ephemeral_key_generated_dev_only")
            keys = [primary, *settings.fernet_old_keys]
            cls._mf = MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
        return cls._mf

    @classmethod
    def reset(cls) -> None:
        cls._mf = None


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _Cipher._get().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return _Cipher._get().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        # Never raise from a read path — return None so callers degrade gracefully.
        return None


# ── Masking helpers (used in API responses; never return raw PII) ──

def mask_pan(pan: str | None) -> str | None:
    """``ABCDE1234F`` -> ``XXXXXE1234F`` (mask first 4; keep 5th letter + digits + check)."""
    if not pan or len(pan) < 10:
        return "XXXXXXXXXX"
    return "X" * 5 + pan[4:]


def mask_aadhaar(aadhaar: str | None) -> str | None:
    """Keep last 4 only: ``XXXX XXXX 1234``."""
    if not aadhaar:
        return None
    digits = "".join(c for c in aadhaar if c.isdigit())
    if len(digits) < 4:
        return "XXXX XXXX XXXX"
    return f"XXXX XXXX {digits[-4:]}"


def mask_account(account: str | None) -> str | None:
    """Keep last 4 of an account number."""
    if not account or len(account) < 4:
        return "XXXX"
    return "X" * (len(account) - 4) + account[-4:]


def mask_generic(value: str | None, *, keep: int = 4) -> str | None:
    if not value:
        return value
    if len(value) <= keep:
        return "X" * len(value)
    return "X" * (len(value) - keep) + value[-keep:]


class EncryptedString(TypeDecorator):
    """Transparently encrypts a string column at rest (Fernet/KMS).

    Stored as text ciphertext; ``cache_ok`` is False because the encrypted form
    is non-deterministic (Fernet embeds a timestamp + IV).
    """

    impl = String
    cache_ok = False

    def process_bind_param(self, value: str | None, _dialect) -> str | None:
        return encrypt(value)

    def process_result_value(self, value: str | None, _dialect) -> str | None:
        return decrypt(value)
