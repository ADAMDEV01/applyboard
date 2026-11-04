import secrets
from datetime import datetime, timedelta, timezone
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
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
    User,
)
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


DEMO_EMAIL = "demo@applyboard.local"


@router.post("/demo", response_model=TokenRead)
@limiter.limit("3/hour")
def demo_login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenRead:
    """Create or reuse a read-only demo workspace with realistic sample applications."""
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(secrets.token_urlsafe(48)),
        )
        db.add(user)
        db.flush()

        now = datetime.now(timezone.utc)
        samples = [
            ("Northstar Labs", "Junior Full-Stack Developer", "Company website", ApplicationStatus.INTERVIEW, 24, 2, "Technical interview scheduled"),
            ("Orbit Systems", "Backend Engineer", "LinkedIn", ApplicationStatus.REPLIED, 18, 5, "Recruiter asked for availability"),
            ("Cedar Technologies", "Frontend Developer", "Wellfound", ApplicationStatus.APPLIED, 9, 4, "Tailored CV submitted"),
            ("Brightpath", "Software Engineer Intern", "Company website", ApplicationStatus.REJECTED, 32, None, "Received a polite rejection"),
            ("Vertex Cloud", "Python Developer", "Indeed", ApplicationStatus.APPLIED, 4, 7, "Follow up with the hiring team"),
        ]
        for company, role, platform, app_status, days_ago, follow_up_days, note in samples:
            applied_at = now - timedelta(days=days_ago)
            application = Application(
                user_id=user.id,
                company=company,
                role=role,
                platform=platform,
                status=app_status,
                applied_at=applied_at,
                follow_up_at=now + timedelta(days=follow_up_days) if follow_up_days else None,
                notes=note,
            )
            application.events.append(
                ApplicationEvent(
                    previous_status=None,
                    new_status=ApplicationStatus.APPLIED,
                    event_type=ApplicationEventType.CREATED,
                    created_at=applied_at,
                    note="Demo application created",
                )
            )
            if app_status != ApplicationStatus.APPLIED:
                application.events.append(
                    ApplicationEvent(
                        previous_status=ApplicationStatus.APPLIED,
                        new_status=app_status,
                        event_type=ApplicationEventType.STATUS_CHANGED,
                        created_at=applied_at + timedelta(days=max(1, days_ago // 2)),
                        note="Demo status update",
                    )
                )
            db.add(application)
        db.commit()

    try:
        token = create_access_token(str(user.id))
    except JWTConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        ) from exc
    return TokenRead(access_token=token)
