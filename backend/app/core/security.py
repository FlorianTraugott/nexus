"""Password hashing and JSON Web Token helpers."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def create_access_token(subject: str) -> str:
    minutes = get_settings().ACCESS_TOKEN_EXPIRE_MINUTES
    return _create_token(subject, "access", timedelta(minutes=minutes))


def create_refresh_token(subject: str) -> str:
    days = get_settings().REFRESH_TOKEN_EXPIRE_DAYS
    return _create_token(subject, "refresh", timedelta(days=days))


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(  # type: ignore[no-any-return]
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
