"""Passwords, tokens and field encryption (CLD-03, ADR 008).

- Passwords: argon2id via argon2-cffi with its default (RFC 9106 low-memory) parameters.
- Access tokens: short-lived HS256 JWTs carrying the user id and the organisation they act in.
- Refresh tokens, invitation tokens, enrolment tokens and device credentials: random opaque
  strings; only their SHA-256 is stored, so a database leak does not leak usable tokens. They are
  high-entropy, so a fast hash is enough (argon2 is for low-entropy human passwords).
- Camera stream URLs (they contain NVR credentials) are encrypted with Fernet (AES-128-CBC +
  HMAC-SHA256) under `VISION_CLOUD_FIELD_ENCRYPTION_KEY`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from vision_cloud.db import new_id

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-ish time: verifies against a dummy hash when the user has no password."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.strip() != password or len(set(password)) < 4:
        raise ValueError("password is too weak")


def new_token(prefix: str) -> str:
    """Opaque token with a readable prefix (e.g. `cxr_` refresh, `cxd_` device)."""
    return f"{prefix}{secrets.token_urlsafe(32)}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hmac_sign(key: str, message: str) -> str:
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_verify(key: str, message: str, signature: str) -> bool:
    return hmac.compare_digest(hmac_sign(key, message), signature)


# --------------------------------------------------------------------------- JWT


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    organisation_id: str
    token_id: str
    expires_at: datetime


class TokenError(Exception):
    pass


def issue_access_token(
    *, secret: str, issuer: str, user_id: str, organisation_id: str, ttl_s: int
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_s)
    payload: dict[str, Any] = {
        "iss": issuer,
        "sub": user_id,
        "org": organisation_id,
        "typ": "access",
        "jti": new_id(),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256"), exp


def decode_access_token(token: str, *, secret: str, issuer: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "iss", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("typ") != "access" or not isinstance(payload.get("org"), str):
        raise TokenError("not an access token")
    return AccessClaims(
        user_id=str(payload["sub"]),
        organisation_id=payload["org"],
        token_id=str(payload["jti"]),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
    )


# --------------------------------------------------------------------------- field encryption


class FieldCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "cannot decrypt field: wrong VISION_CLOUD_FIELD_ENCRYPTION_KEY?"
            ) from exc


def generate_field_key() -> str:
    return Fernet.generate_key().decode("ascii")
