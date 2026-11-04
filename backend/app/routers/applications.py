from datetime import datetime, timezone
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import CurrentUser
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
    User,
)
from app.schemas.application import (
    ApplicationCreate,
    ApplicationPage,
    ApplicationRead,
    ApplicationSort,
    ApplicationUpdate,
    SortOrder,
)
from app.services.applications import is_valid_status_transition

router = APIRouter(prefix="/applications", tags=["applications"])
DEMO_EMAIL = "demo@applyboard.dev"


def ensure_writable_user(current_user: User) -> None:
    if current_user.email == DEMO_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The demo workspace is read-only. Create an account to manage applications.",
        )


def get_owned_application(
    application_id: int,
    user_id: int,
    db: Session,
) -> Application:
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == user_id,
        )
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    return application


@router.get("", response_model=ApplicationPage)
def list_applications(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=200)] = None,
    application_status: Annotated[
        ApplicationStatus | None,
        Query(alias="status"),
    ] = None,
    platform: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_by: ApplicationSort = ApplicationSort.APPLIED_AT,
    order: SortOrder = SortOrder.DESC,
) -> ApplicationPage:
    filters = [Application.user_id == current_user.id]
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            Application.company.ilike(pattern) | Application.role.ilike(pattern)
        )
    if application_status is not None:
        filters.append(Application.status == application_status)
    if platform is not None:
        filters.append(func.lower(Application.platform) == platform.strip().lower())

    total = db.scalar(
        select(func.count()).select_from(Application).where(*filters)
    ) or 0

    sort_column = {
        ApplicationSort.APPLIED_AT: Application.applied_at,
        ApplicationSort.COMPANY: Application.company,
        ApplicationSort.LAST_UPDATE_AT: Application.last_update_at,
    }[sort_by]
    ordering = sort_column.asc() if order == SortOrder.ASC else sort_column.desc()
    applications = db.scalars(
        select(Application)
        .where(*filters)
        .order_by(ordering, Application.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return ApplicationPage(
        items=[ApplicationRead.model_validate(item) for item in applications],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total else 0,
    )


@router.post(
    "",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_application(
    payload: ApplicationCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Application:
    ensure_writable_user(current_user)
    application_data = payload.model_dump()
    if payload.url is not None:
        application_data["url"] = str(payload.url)
    if payload.applied_at is None:
        application_data.pop("applied_at")
    application = Application(user_id=current_user.id, **application_data)
    application.events.append(
        ApplicationEvent(
            previous_status=None,
            new_status=application.status,
            event_type=ApplicationEventType.CREATED,
            note="Application created",
        )
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


@router.get("/{application_id}", response_model=ApplicationRead)
def read_application(
    application_id: int,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Application:
    return get_owned_application(application_id, current_user.id, db)


@router.patch("/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Application:
    ensure_writable_user(current_user)
    application = get_owned_application(application_id, current_user.id, db)
    update_data = payload.model_dump(exclude_unset=True)

    requested_status = update_data.get("status")
    if requested_status is not None and not is_valid_status_transition(
        application.status,
        requested_status,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot change status from '{application.status.value}' "
                f"to '{requested_status.value}'."
            ),
        )

    if "url" in update_data and update_data["url"] is not None:
        update_data["url"] = str(update_data["url"])
    if "follow_up_at" in update_data:
        application.follow_up_reminder_sent_at = None
    previous_status = application.status
    for field_name, value in update_data.items():
        setattr(application, field_name, value)
    application.last_update_at = datetime.now(timezone.utc)
    event_type = (
        ApplicationEventType.STATUS_CHANGED
        if requested_status is not None and requested_status != previous_status
        else ApplicationEventType.UPDATED
    )
    application.events.append(
        ApplicationEvent(
            previous_status=previous_status,
            new_status=application.status,
            event_type=event_type,
            note=(
                "Application status changed"
                if event_type == ApplicationEventType.STATUS_CHANGED
                else "Application details updated"
            ),
        )
    )

    db.commit()
    db.refresh(application)
    return application


@router.delete(
    "/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_application(
    application_id: int,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    ensure_writable_user(current_user)
    application = get_owned_application(application_id, current_user.id, db)
    db.delete(application)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
