import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import CORS_ALLOWED_ORIGINS
from app.core.limiter import limiter
from app.db.database import get_db
from app.models import User
from app.routers.applications import router as applications_router
from app.routers.auth import router as auth_router
from app.routers.events import router as events_router
from app.routers.stats import router as stats_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Job Tracker API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.error("Database operation failed", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(
        status_code=503,
        content={"detail": "Database unavailable. Verify DATABASE_URL and apply Alembic migrations."},
    )


app.include_router(auth_router)
app.include_router(applications_router)
app.include_router(events_router)
app.include_router(stats_router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness_check(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(select(User.id).limit(1))
    return {"status": "ready"}
