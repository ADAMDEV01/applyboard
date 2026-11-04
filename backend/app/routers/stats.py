from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import CurrentUserfrom app.schemas.stats import DashboardSummary, PlatformMetrics, ResponseMetrics
from app.services.stats import (
    get_dashboard_summary,
    get_platform_metrics,
    get_response_metrics,
)

router = APIRouter(prefix="/stats", tags=["analytics"])


@router.get("/summary", response_model=DashboardSummary)
def read_summary(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> DashboardSummary:
    return get_dashboard_summary(db, current_user.id)


@router.get("/platforms", response_model=list[PlatformMetrics])
def read_platforms(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[PlatformMetrics]:
    return get_platform_metrics(db, current_user.id)


@router.get("/responses", response_model=ResponseMetrics)
def read_responses(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ResponseMetrics:
    return get_response_metrics(db, current_user.id)
