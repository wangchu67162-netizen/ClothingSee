"""FastAPI dependencies: database session and optional/required JWT user."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def _user_from_credentials(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> User | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None
    return db.get(User, user_id)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_credentials(credentials, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    return _user_from_credentials(credentials, db)
