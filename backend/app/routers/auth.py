import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import COOKIE_SECURE, CORS_ALLOWED_ORIGINS
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
    RefreshSession,
    User,
)
from app.schemas.auth import SessionRead, UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])
DEMO_EMAIL = "demo@applyboard.dev"
ACCESS_COOKIE = "applyboard_access"
REFRESH_COOKIE = "applyboard_refresh"
REFRESH_TOKEN_TTL = timedelta(days=14)


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/auth")


def _require_same_origin(request: Request) -> None:
    if request.headers.get("origin") not in CORS_ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A trusted Origin header is required for cookie-authenticated requests.",
        )


def _issue_session(
    response: Response,
    db: Session,
    user: User,
) -> SessionRead:
    now = datetime.now(timezone.utc)
    try:
        access_token = create_access_token(str(user.id))
    except JWTConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        ) from exc

    refresh_token = secrets.token_urlsafe(48)
    db.add(
        RefreshSession(
            user_id=user.id,
            token_hash=_hash_refresh_token(refresh_token),
            expires_at=now + REFRESH_TOKEN_TTL,
            created_at=now,
        )
    )
    db.commit()

    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=30 * 60,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        path="/auth",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return SessionRead()


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


@router.post("/login", response_model=SessionRead)
@limiter.limit("10/minute")
def login(
    request: Request,
    response: Response,
    payload: UserLogin,
    db: Annotated[Session, Depends(get_db)],
) -> SessionRead:
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    hashed_password = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    if not verify_password(payload.password, hashed_password) or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_session(response, db, user)


@router.post("/refresh", response_model=SessionRead)
@limiter.limit("30/minute")
def refresh_session(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> SessionRead:
    _require_same_origin(request)
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        _clear_session_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session is missing or expired.",
        )

    now = datetime.now(timezone.utc)
    token_hash = _hash_refresh_token(token)
    session = db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == token_hash,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
        )
    )
    if session is None:
        _clear_session_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session is missing, expired, or revoked.",
        )
    user = db.get(User, session.user_id)
    if user is None:
        _clear_session_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session is no longer valid.",
        )

    # PostgreSQL rechecks this predicate after waiting on a concurrent row lock.
    # Therefore only one request can consume a given refresh session.
    consumed = db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.id == session.id,
            RefreshSession.token_hash == token_hash,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
        )
        .values(revoked_at=now)
    )
    if consumed.rowcount != 1:
        db.rollback()
        _clear_session_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session has already been used.",
        )

    # The replacement session is committed together with revocation.
    return _issue_session(response, db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    _require_same_origin(request)
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        session = db.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == _hash_refresh_token(token),
                RefreshSession.revoked_at.is_(None),
            )
        )
        if session is not None:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: CurrentUser) -> User:
    return current_user


@router.post("/demo", response_model=SessionRead)
@limiter.limit("3/hour")
def demo_login(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> SessionRead:
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
    return _issue_session(response, db, user)
