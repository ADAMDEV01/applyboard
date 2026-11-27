import pytest
from sqlalchemy.engine import make_url

from app.core.config import normalize_database_url, validate_production_config


def test_normalize_postgresql_url_uses_psycopg_driver() -> None:
    normalized = normalize_database_url(
        "postgresql://postgres.example:secret@db.example.com:5432/postgres"
    )
    assert make_url(normalized).drivername == "postgresql+psycopg"


def test_normalize_legacy_postgres_url_uses_psycopg_driver() -> None:
    normalized = normalize_database_url(
        "postgres://postgres:secret@db.example.com:5432/postgres"
    )
    assert make_url(normalized).drivername == "postgresql+psycopg"


def test_normalize_database_url_preserves_other_drivers() -> None:
    normalized = normalize_database_url("sqlite:///./job_tracker.db")
    assert normalized == "sqlite:///./job_tracker.db"


def _valid_production_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://user:password@db.example.com:5432/app",
        "jwt_secret": "a-cryptographically-random-secret-with-more-than-32-bytes",
        "cors_allowed_origins": ["https://applyboard.example.com"],
        "cookie_secure": True,
    }
    config.update(overrides)
    return config


def test_production_accepts_durable_secure_configuration() -> None:
    validate_production_config(**_valid_production_config())  # type: ignore[arg-type]


@pytest.mark.parametrize("database_url", ["sqlite:///./job_tracker.db", "", "not a url"])
def test_production_rejects_non_postgresql_or_invalid_database_urls(database_url: str) -> None:
    with pytest.raises(RuntimeError, match="PostgreSQL DATABASE_URL"):
        validate_production_config(**_valid_production_config(database_url=database_url))  # type: ignore[arg-type]


@pytest.mark.parametrize("jwt_secret", [None, "", "short-secret"])
def test_production_requires_a_strong_jwt_secret(jwt_secret: str | None) -> None:
    with pytest.raises(RuntimeError, match="32 random bytes"):
        validate_production_config(**_valid_production_config(jwt_secret=jwt_secret))  # type: ignore[arg-type]


def test_production_rejects_insecure_cookies() -> None:
    with pytest.raises(RuntimeError, match="COOKIE_SECURE=true"):
        validate_production_config(**_valid_production_config(cookie_secure=False))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "origins",
    [
        [],
        ["*"],
        ["http://applyboard.example.com"],
        ["https://applyboard.example.com/"],
        ["https://applyboard.example.com/path"],
        ["https://user:password@applyboard.example.com"],
    ],
)
def test_production_rejects_non_exact_or_insecure_cors_origins(origins: list[str]) -> None:
    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        validate_production_config(**_valid_production_config(cors_allowed_origins=origins))  # type: ignore[arg-type]


def test_development_keeps_sqlite_memory_rate_limits_and_local_origins() -> None:
    validate_production_config(
        app_env="development",
        database_url="sqlite:///./job_tracker.db",
        jwt_secret=None,
        cors_allowed_origins=["http://localhost:5173"],
        cookie_secure=False,
    )
