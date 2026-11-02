"""Symmetric encryption for stored integration credentials (Fernet / AES-128-CBC + HMAC)."""
from __future__ import annotations

import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class EncryptionNotConfigured(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if key is None or not key.get_secret_value():
        raise EncryptionNotConfigured(
            "ENCRYPTION_KEY is not set. Generate one with: python -c \"from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())\" and add it to .env"
        )
    try:
        return Fernet(key.get_secret_value().encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionNotConfigured("ENCRYPTION_KEY is not a valid Fernet key") from exc


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionNotConfigured(
            "Stored credential could not be decrypted. The ENCRYPTION_KEY may have changed; "
            "re-enter the credential in Settings → Integrations."
        ) from exc


def secret_fingerprint(plaintext: str) -> str:
    """Short non-reversible fingerprint so the UI can show that a secret is set."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:8]


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
