import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError

from app.core.config import Settings


hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("not-a-real-password")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_expired(value: datetime) -> bool:
    return value.replace(tzinfo=timezone.utc) <= utcnow() if value.tzinfo is None else value <= utcnow()


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHash):
        return False


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user_id: str, session_id: str, settings: Settings) -> str:
    issued_at = utcnow()
    return jwt.encode(
        {
            "sub": user_id,
            "sid": session_id,
            "jti": str(uuid.uuid4()),
            "typ": "access",
            "iss": "mindpilot-local",
            "aud": "mindpilot-api",
            "iat": issued_at,
            "nbf": issued_at,
            "exp": issued_at + timedelta(minutes=settings.access_minutes),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: Settings) -> dict:
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience="mindpilot-api",
        issuer="mindpilot-local",
        options={"require": ["sub", "sid", "jti", "typ", "iss", "aud", "iat", "nbf", "exp"]},
    )
    if claims["typ"] != "access":
        raise jwt.InvalidTokenError("Wrong token type")
    return claims
