from collections.abc import Sequence
from typing import Any
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, extract, func, select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
)
from app.schemas.stats import (
    DashboardSummary,
    FollowUpItem,
    PlatformMetrics,
    ResponseMetrics,
    StatusCount,
)
from app.schemas.application import ApplicationRead

RESPONSE_STATUSES = (
    ApplicationStatus.REPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
)
TERMINAL_STATUSES = (
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
    ApplicationStatus.GHOSTED,
)
GHOSTED_AFTER = timedelta(days=14)
FOLLOW_UP_HORIZON = timedelta(days=30)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(
        timezone.utc
    )


def _round_rate(responded: int, total: int) -> float:
    return round(responded / total, 4) if total else 0.0


def _average_days(durations: list[float]) -> float | None:
    return round(sum(durations) / len(durations) / 86400, 2) if durations else None


def calculate_response_metrics(
    rows: list[tuple[Application, datetime | None]],
) -> ResponseMetrics:
    durations: list[float] = []
    responded = 0
    for application, first_response_at in rows:
        if first_response_at is None:
            continue
        duration = (
            _as_utc(first_response_at) - _as_utc(application.applied_at)
        ).total_seconds()
        if duration >= 0:
            responded += 1
            durations.append(duration)

    return ResponseMetrics(
        total_applications=len(rows),
        responded_applications=responded,
        response_rate=_round_rate(responded, len(rows)),
        average_time_to_first_response_days=_average_days(durations),
    )


def _first_response_subquery():
    return (
        select(
            ApplicationEvent.application_id.label("application_id"),
            func.min(ApplicationEvent.created_at).label("first_response_at"),
        )
        .join(Application, Application.id == ApplicationEvent.application_id)
        .where(
            ApplicationEvent.event_type == ApplicationEventType.STATUS_CHANGED,
            ApplicationEvent.new_status.in_(RESPONSE_STATUSES),
        )
        .group_by(ApplicationEvent.application_id)
        .subquery()
    )


def _duration_seconds(db: Session, first_response_at):
    if db.get_bind().dialect.name == "sqlite":
        return (
            func.julianday(first_response_at) - func.julianday(Application.applied_at)
        ) * 86400
    return extract("epoch", first_response_at - Application.applied_at)


def _aggregate_metrics(
    db: Session,
    user_id: int,
    *,
    group_by_platform: bool = False,
) -> list[tuple[str | None, ResponseMetrics]]:
    first_response = _first_response_subquery()
    duration = _duration_seconds(db, first_response.c.first_response_at)
    valid_response = case(
        (
            first_response.c.first_response_at.is_not(None) & (duration >= 0),
            Application.id,
        ),
        else_=None,
    )
    average_duration = case((duration >= 0, duration), else_=None)
    columns: list[Any] = [
        func.count(Application.id),
        func.count(valid_response),
        func.avg(average_duration),
    ]
    if group_by_platform:
        columns.insert(0, Application.platform)
    statement = (
        select(*columns)
        .outerjoin(
            first_response,
            first_response.c.application_id == Application.id,
        )
        .where(Application.user_id == user_id)
    )
    if group_by_platform:
        statement = statement.group_by(Application.platform).order_by(
            func.lower(Application.platform)
        )

    results: list[tuple[str | None, ResponseMetrics]] = []
    for row in db.execute(statement):
        if group_by_platform:
            platform, total, responded, average_seconds = row
        else:
            total, responded, average_seconds = row
            platform = None
        average_days = (
            round(float(average_seconds) / 86400, 2)
            if average_seconds is not None
            else None
        )
        metrics = ResponseMetrics(
            total_applications=int(total or 0),
            responded_applications=int(responded or 0),
            response_rate=_round_rate(int(responded or 0), int(total or 0)),
            average_time_to_first_response_days=average_days,
        )
        results.append((platform, metrics))
    return results


def _follow_up_items(
    applications: Sequence[Application],
    current_time: datetime,
) -> list[FollowUpItem]:
    return [
        FollowUpItem(
            application=ApplicationRead.model_validate(application),
            days_since_applied=(current_time - _as_utc(application.applied_at)).days,
        )
        for application in applications
    ]


def get_dashboard_summary(
    db: Session,
    user_id: int,
    now: datetime | None = None,
) -> DashboardSummary:
    current_time = _as_utc(now or datetime.now(timezone.utc))
    metrics = _aggregate_metrics(db, user_id)[0][1]
    first_response = _first_response_subquery()
    ghosted_cutoff = current_time - GHOSTED_AFTER
    follow_up_cutoff = current_time + FOLLOW_UP_HORIZON

    ghosted_applications = db.scalars(
        select(Application)
        .outerjoin(
            first_response,
            first_response.c.application_id == Application.id,
        )
        .where(
            Application.user_id == user_id,
            Application.status == ApplicationStatus.APPLIED,
            Application.applied_at <= ghosted_cutoff,
            first_response.c.application_id.is_(None),
        )
        .order_by(Application.applied_at)
    ).all()
    upcoming_applications = db.scalars(
        select(Application)
        .where(
            Application.user_id == user_id,
            Application.follow_up_at >= current_time,
            Application.follow_up_at <= follow_up_cutoff,
            Application.status.not_in(TERMINAL_STATUSES),
        )
        .order_by(Application.follow_up_at)
    ).all()

    status_rows = db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == user_id)
        .group_by(Application.status)
    ).all()
    status_counts = {status: count for status, count in status_rows}

    return DashboardSummary(
        **metrics.model_dump(),
        by_status=[
            StatusCount(status=application_status, count=status_counts.get(application_status, 0))
            for application_status in ApplicationStatus
        ],
        upcoming_followups=_follow_up_items(upcoming_applications, current_time),
        may_be_ghosted=_follow_up_items(ghosted_applications, current_time),
    )


def get_platform_metrics(db: Session, user_id: int) -> list[PlatformMetrics]:
    return [
        PlatformMetrics(platform=platform or "", **metrics.model_dump())
        for platform, metrics in _aggregate_metrics(
            db,
            user_id,
            group_by_platform=True,
        )
    ]


def get_response_metrics(db: Session, user_id: int) -> ResponseMetrics:
    return _aggregate_metrics(db, user_id)[0][1]
