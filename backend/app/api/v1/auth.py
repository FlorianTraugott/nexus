"""Authentication endpoints."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.middleware import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.models import User
from app.db.repositories import token as token_repo
from app.db.repositories import user as user_repo
from app.db.session import get_db
from app.schemas.token import RefreshRequest, Token
from app.schemas.user import UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_token_pair(db: AsyncSession, user_id: uuid.UUID) -> Token:
    access_token = create_access_token(str(user_id))
    refresh_token = create_refresh_token(str(user_id))
    expires_at = datetime.now(UTC) + timedelta(
        days=get_settings().REFRESH_TOKEN_EXPIRE_DAYS
    )
    await token_repo.store_refresh_token(
        db, user_id, hash_token(refresh_token), expires_at
    )
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request, payload: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    # Env-gated: closed in the public demo (default true leaves dev/tests open).
    if not get_settings().REGISTRATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled"
        )
    if await user_repo.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    user = await user_repo.create_user(
        db, payload.email, hash_password(payload.password)
    )
    await db.commit()
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request, payload: UserLogin, db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    user = await user_repo.get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )
    tokens = await _issue_token_pair(db, user.id)
    await db.commit()
    return tokens


@router.post("/refresh", response_model=Token)
async def refresh(
    payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
    )
    try:
        claims = decode_token(payload.refresh_token)
    except jwt.InvalidTokenError:
        raise invalid from None
    if claims.get("type") != "refresh":
        raise invalid

    token_hash = hash_token(payload.refresh_token)
    stored = await token_repo.get_active_refresh_token(db, token_hash)
    if stored is None:
        raise invalid

    await token_repo.revoke_refresh_token(db, token_hash)
    tokens = await _issue_token_pair(db, stored.user_id)
    await db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    await token_repo.revoke_refresh_token(db, hash_token(payload.refresh_token))
    await db.commit()


@router.get("/me", response_model=UserRead)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
