"""Secrets at rest and opaque tokens.

- Stream URLs and TOTP secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256).
- One-time tokens (invitations, resets, enrolment, refresh, device credentials) are random 256-bit
  values; only their SHA-256 is stored, so a database dump does not hand out working tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from vision_cloud.settings import get_settings


@lru_cache(maxsize=4)
def _fernet(key: str) -> Fernet:
    return Fernet(key.encode())


def fernet() -> Fernet:
    return _fernet(get_settings().encryption_key.get_secret_value())


def encrypt(value: str) -> str:
    return fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("cannot decrypt value: wrong VISION_ENCRYPTION_KEY?") from exc


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def generate_key() -> str:
    return Fernet.generate_key().decode()
