import os

from sqlalchemy.engine import make_url


def normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


DATABASE_URL = normalize_database_url(
    os.getenv("DATABASE_URL", "sqlite:///./job_tracker.db")
)
JWT_SECRET = os.getenv("JWT_SECRET")
ACCESS_TOKEN_EXPIRE_MINUTES = 30

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if origin.strip()
]

APP_ENV = os.getenv("APP_ENV", "development").lower()
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://").strip()

if APP_ENV == "production" and not COOKIE_SECURE:
    raise RuntimeError("COOKIE_SECURE=true is required when APP_ENV=production.")
if APP_ENV == "production" and RATE_LIMIT_STORAGE_URI.startswith("memory://"):
    raise RuntimeError(
        "A shared Redis RATE_LIMIT_STORAGE_URI is required in production."
    )
