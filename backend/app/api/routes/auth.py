from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentContext, Db, bearer
from app.core.security import DUMMY_HASH, create_access_token, decode_access_token, hash_password, hash_refresh_token, is_expired, new_refresh_token, utcnow, verify_password
from app.db.models import AuthSession, LoginAttempt, User
from app.schemas.auth import LoginIn, PasswordChangeIn, ProfileIn, RegisterIn, SessionOut, UserOut
from app.services.profile_statistics import profile_statistics


router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE_NAME = "mindpilot_refresh"


def set_refresh_cookie(response: Response, token: str, request: Request, remember: bool = True) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.refresh_days * 86400 if remember else None,
        httponly=True, secure=settings.secure_cookie, samesite="strict", path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/api/v1/auth", samesite="strict")


def issue_session(user: User, db: Db, response: Response, request: Request, remember: bool = True):
    refresh = new_refresh_token()
    settings = request.app.state.settings
    session = AuthSession(user_id=user.id, refresh_hash=hash_refresh_token(refresh), remember=remember, expires_at=utcnow() + timedelta(days=settings.refresh_days))
    db.add(session)
    db.commit()
    set_refresh_cookie(response, refresh, request, remember)
    return {"accessToken": create_access_token(user.id, session.id, settings), "user": UserOut.from_user(user)}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Db):
    user = User(
        username=payload.username,
        username_key=payload.username.casefold(),
        password_hash=hash_password(payload.password),
        display_name=payload.username,
        research_field=payload.research_field,
        default_domain=payload.default_domain,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户名已被注册") from None
    return UserOut.from_user(user)


@router.post("/login")
def login(payload: LoginIn, db: Db, response: Response, request: Request):
    key = payload.username.strip().casefold()
    attempt = db.get(LoginAttempt, key)
    if attempt and attempt.locked_until and not is_expired(attempt.locked_until):
        verify_password(payload.password, DUMMY_HASH)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "尝试次数过多，请稍后重试")
    user = db.scalar(select(User).where(User.username_key == key))
    if not verify_password(payload.password, user.password_hash if user else DUMMY_HASH) or not user:
        if not attempt:
            attempt = LoginAttempt(username_key=key, failures=0)
            db.add(attempt)
        attempt.failures += 1
        if attempt.failures >= 5:
            attempt.locked_until = utcnow() + timedelta(minutes=5)
            attempt.failures = 0
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码不正确")
    if attempt:
        db.delete(attempt)
        db.commit()
    return issue_session(user, db, response, request, payload.remember)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Db):
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "会话已失效")
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_hash == hash_refresh_token(raw)))
    if not session or session.revoked_at or is_expired(session.expires_at):
        invalid = JSONResponse({"detail": "会话已失效"}, status_code=status.HTTP_401_UNAUTHORIZED)
        clear_refresh_cookie(invalid)
        return invalid
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "会话已失效")
    rotated = new_refresh_token()
    session.refresh_hash = hash_refresh_token(rotated)
    db.commit()
    set_refresh_cookie(response, rotated, request, session.remember)
    return {"accessToken": create_access_token(user.id, session.id, request.app.state.settings), "user": UserOut.from_user(user)}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    raw = request.cookies.get(COOKIE_NAME)
    session = None
    if raw:
        session = db.scalar(select(AuthSession).where(AuthSession.refresh_hash == hash_refresh_token(raw)))
    if session is None and credentials and credentials.scheme.lower() == "bearer":
        try:
            claims = decode_access_token(credentials.credentials, request.app.state.settings)
            session = db.get(AuthSession, claims["sid"])
            if session and session.user_id != claims["sub"]:
                session = None
        except jwt.PyJWTError:
            pass
    if session:
        session.revoked_at = utcnow()
        db.commit()
    clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
def me(context: CurrentContext):
    return UserOut.from_user(context[0])


@router.patch("/me", response_model=UserOut)
def update_me(payload: ProfileIn, db: Db, context: CurrentContext):
    user, _ = context
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, key, value)
    db.commit()
    return UserOut.from_user(user)


@router.get("/me/statistics")
def statistics(db: Db, context: CurrentContext):
    return profile_statistics(db, context[0].id)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: PasswordChangeIn, db: Db, response: Response, context: CurrentContext):
    user, _ = context
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码不正确")
    user.password_hash = hash_password(payload.next_password)
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
        session.revoked_at = utcnow()
    db.commit()
    clear_refresh_cookie(response)


@router.get("/sessions")
def list_sessions(db: Db, context: CurrentContext):
    user, current = context
    items = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow()).order_by(AuthSession.created_at.desc())).all()
    return {"items": [SessionOut.model_validate({"id": item.id, "createdAt": item.created_at, "expiresAt": item.expires_at, "current": item.id == current.id}) for item in items]}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: str, db: Db, context: CurrentContext):
    user, _ = context
    session = db.get(AuthSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    session.revoked_at = utcnow()
    db.commit()
