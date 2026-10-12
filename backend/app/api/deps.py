from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token, is_expired
from app.db.models import AuthSession, User


bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


Db = Annotated[Session, Depends(get_db)]


def get_current_context(request: Request, db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    error = HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录", headers={"WWW-Authenticate": "Bearer"})
    if not credentials or credentials.scheme.lower() != "bearer":
        raise error
    try:
        claims = decode_access_token(credentials.credentials, request.app.state.settings)
    except jwt.PyJWTError:
        raise error from None
    session = db.get(AuthSession, claims["sid"])
    if not session or session.user_id != claims["sub"] or session.revoked_at or is_expired(session.expires_at):
        raise error
    user = db.get(User, session.user_id)
    if not user:
        raise error
    return user, session


CurrentContext = Annotated[tuple[User, AuthSession], Depends(get_current_context)]
