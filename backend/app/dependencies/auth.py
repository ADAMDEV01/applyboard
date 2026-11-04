from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import CORS_ALLOWED_ORIGINS
from app.core.security import JWTConfigurationError, decode_access_token
from app.db.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token: str | None = None
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get("applyboard_access")
        if token and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") not in CORS_ALLOWED_ORIGINS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="A trusted Origin header is required for cookie-authenticated requests.",
                )
    if token is None:
        raise unauthorized

    try:
        payload = decode_access_token(token)
    except JWTConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        ) from exc
    except jwt.InvalidTokenError:
        raise unauthorized from None

    subject = payload.get("sub")
    try:
        user_id = int(subject) if isinstance(subject, str) else None
    except ValueError:
        raise unauthorized from None
    if user_id is None:
        raise unauthorized

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
