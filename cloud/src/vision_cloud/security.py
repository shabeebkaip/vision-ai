"""Passwords (argon2id), access tokens (JWT, HS256) and authenticator-app codes (TOTP). CLD-03."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from vision_cloud.settings import CloudSettings

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256
TOTP_ISSUER = "Code-Ox Vision"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        # Spend the same time as a real check so missing accounts are not detectable by timing.
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"password must be at most {MAX_PASSWORD_LENGTH} characters"
    return None


# --------------------------------------------------------------------------- access tokens


def create_access_token(
    settings: CloudSettings, user_id: uuid.UUID, token_version: int, now: datetime | None = None
) -> str:
    now = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "typ": "access",
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_s)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access_token(settings: CloudSettings, token: str) -> dict[str, Any]:
    """Raises `jwt.InvalidTokenError` on any problem (signature, expiry, issuer, type)."""
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "exp", "iat", "iss", "ver", "typ"]},
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


# --------------------------------------------------------------------------- TOTP


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def verify_totp(secret: str, code: str, at: datetime | None = None) -> bool:
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    # Accept the previous and next 30 s step to absorb phone clock drift.
    return pyotp.TOTP(secret).verify(
        code, for_time=at or datetime.now(timezone.utc), valid_window=1
    )
