from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.limiter import limiter
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    JWTConfigurationError,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.dependencies.auth import CurrentUser
from app.models import User
from app.schemas.auth import TokenRead, UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
def register(
    request: Request,
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    email = str(payload.email).strip().lower()
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_user = db.scalar(select(User.id).where(User.email == email))
        if existing_user is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            ) from None
        raise
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenRead)
@limiter.limit("10/minute")
def login(
    request: Request,
    payload: UserLogin,
    db: Annotated[Session, Depends(get_db)],
) -> TokenRead:
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    hashed_password = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    if not verify_password(payload.password, hashed_password) or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        token = create_access_token(str(user.id))
    except JWTConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        ) from exc
    return TokenRead(access_token=token)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: CurrentUser) -> User:
    return current_user
