from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.database import get_db


def test_health_check_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_check_returns_ready(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_database_errors_are_cors_accessible(
    client: TestClient,
) -> None:
    def unavailable_database() -> Generator[None, None, None]:
        raise OperationalError("SELECT", {}, RuntimeError("database unavailable"))
        yield

    client.app.dependency_overrides[get_db] = unavailable_database
    response = client.get(
        "/health/ready",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable. Verify DATABASE_URL and apply Alembic migrations."
    }
    assert (
        response.headers["access-control-allow-origin"]
        == "http://localhost:5173"
    )


def test_api_cors_allows_configured_origin_and_rejects_unknown_origin(client: TestClient) -> None:
    allowed = client.options(
        "/auth/me",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    rejected = client.options(
        "/auth/me",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
