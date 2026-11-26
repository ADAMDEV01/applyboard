import os
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url


def normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def validate_production_config(
    *,
    app_env: str,
    database_url: str,
    jwt_secret: str | None,
    cors_allowed_origins: list[str],
    cookie_secure: bool,
    rate_limit_storage_uri: str,
) -> None:
    """Fail closed when production is missing durable, secure service configuration."""
    if app_env.strip().lower() != "production":
        return

    try:
        database_backend = make_url(database_url).get_backend_name()
    except (TypeError, ValueError) as error:
        raise RuntimeError("A valid PostgreSQL DATABASE_URL is required in production.") from error
    if database_backend != "postgresql":
        raise RuntimeError("A persistent PostgreSQL DATABASE_URL is required in production.")

    if jwt_secret is None or len(jwt_secret.encode()) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 random bytes in production.")

    if not cookie_secure:
        raise RuntimeError("COOKIE_SECURE=true is required when APP_ENV=production.")

    if not rate_limit_storage_uri or rate_limit_storage_uri.startswith("memory://"):
        raise RuntimeError("A shared Redis RATE_LIMIT_STORAGE_URI is required in production.")

    if not cors_allowed_origins or "*" in cors_allowed_origins:
        raise RuntimeError("Exact HTTPS CORS_ALLOWED_ORIGINS are required in production.")

    for origin in cors_allowed_origins:
        parsed = urlsplit(origin)
        canonical_origin = f"{parsed.scheme}://{parsed.netloc}"
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or origin != canonical_origin
        ):
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS must contain exact HTTPS origins without paths or wildcards."
            )


DATABASE_URL = normalize_database_url(
    os.getenv("DATABASE_URL", "sqlite:///./job_tracker.db")
)
JWT_SECRET = os.getenv("JWT_SECRET")
ACCESS_TOKEN_EXPIRE_MINUTES = 30

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    ).split(",")
    if origin.strip()
]

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"
RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://").strip()

validate_production_config(
    app_env=APP_ENV,
    database_url=DATABASE_URL,
    jwt_secret=JWT_SECRET,
    cors_allowed_origins=CORS_ALLOWED_ORIGINS,
    cookie_secure=COOKIE_SECURE,
    rate_limit_storage_uri=RATE_LIMIT_STORAGE_URI,
)
