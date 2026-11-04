from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import func, select
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


def _response_rows(
    db: Session,
    user_id: int,
) -> list[tuple[Application, datetime | None]]:
    first_response = (
        select(
            ApplicationEvent.application_id.label("application_id"),
            func.min(ApplicationEvent.created_at).label("first_response_at"),
        )
        .join(Application, Application.id == ApplicationEvent.application_id)
        .where(
            Application.user_id == user_id,
            ApplicationEvent.event_type == ApplicationEventType.STATUS_CHANGED,
            ApplicationEvent.new_status.in_(RESPONSE_STATUSES),
        )
        .group_by(ApplicationEvent.application_id)
        .subquery()
    )
    return cast(
        list[tuple[Application, datetime | None]],
        list(db.execute(
            select(Application, first_response.c.first_response_at)
            .outerjoin(
                first_response,
                first_response.c.application_id == Application.id,
            )
            .where(Application.user_id == user_id)
        ).all()),
    )


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


def get_dashboard_summary(
    db: Session,
    user_id: int,
    now: datetime | None = None,
) -> DashboardSummary:
    current_time = _as_utc(now or datetime.now(timezone.utc))
    rows = _response_rows(db, user_id)
    metrics = calculate_response_metrics(rows)
    status_counts = {application_status: 0 for application_status in ApplicationStatus}
    upcoming_followups: list[FollowUpItem] = []
    may_be_ghosted: list[FollowUpItem] = []
    ghosted_cutoff = current_time - GHOSTED_AFTER
    follow_up_cutoff = current_time + FOLLOW_UP_HORIZON

    for application, first_response_at in rows:
        status_counts[application.status] += 1
        applied_at = _as_utc(application.applied_at)
        if (
            application.status == ApplicationStatus.APPLIED
            and first_response_at is None
            and applied_at <= ghosted_cutoff
        ):
            may_be_ghosted.append(
                FollowUpItem(
                    application=ApplicationRead.model_validate(application),
                    days_since_applied=(current_time - applied_at).days,
                )
            )
        if (
            application.follow_up_at is not None
            and current_time <= _as_utc(application.follow_up_at) <= follow_up_cutoff
            and application.status not in TERMINAL_STATUSES
        ):
            upcoming_followups.append(
                FollowUpItem(
                    application=ApplicationRead.model_validate(application),
                    days_since_applied=(current_time - applied_at).days,
                )
            )

    upcoming_followups.sort(
        key=lambda item: _as_utc(item.application.follow_up_at)
        if item.application.follow_up_at is not None
        else current_time
    )
    may_be_ghosted.sort(key=lambda item: item.application.applied_at)

    return DashboardSummary(
        **metrics.model_dump(),
        by_status=[
            StatusCount(status=application_status, count=count)
            for application_status, count in status_counts.items()
        ],
        upcoming_followups=upcoming_followups,
        may_be_ghosted=may_be_ghosted,
    )


def get_platform_metrics(db: Session, user_id: int) -> list[PlatformMetrics]:
    rows = _response_rows(db, user_id)
    grouped: dict[str, list[tuple[Application, datetime | None]]] = {}
    for row in rows:
        grouped.setdefault(row[0].platform, []).append(row)

    results: list[PlatformMetrics] = []
    for platform, platform_rows in grouped.items():
        metrics = calculate_response_metrics(platform_rows)
        results.append(PlatformMetrics(platform=platform, **metrics.model_dump()))
    return sorted(results, key=lambda item: item.platform.casefold())


def get_response_metrics(db: Session, user_id: int) -> ResponseMetrics:
    return calculate_response_metrics(_response_rows(db, user_id))
