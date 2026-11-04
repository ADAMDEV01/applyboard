from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import security


def register_user(
    client: TestClient,
    email: str = "person@example.com",
    password: str = "safe-password-123",
) -> dict[str, object]:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return response.json()


def login_user(
    client: TestClient,
    email: str = "person@example.com",
    password: str = "safe-password-123",
) -> dict[str, object]:
    return client.post(
        "/auth/login",
        json={"email": email, "password": password},
    ).json()


def test_registration_persists_only_a_password_hash(client: TestClient) -> None:
    user = register_user(client)

    assert user["email"] == "person@example.com"
    assert "password" not in user
    assert "password_hash" not in user


def test_duplicate_registration_returns_conflict(client: TestClient) -> None:
    register_user(client)

    response = client.post(
        "/auth/register",
        json={"email": "PERSON@example.com", "password": "different-password"},
    )

    assert response.status_code == 409


def test_login_sets_httponly_session_cookies_and_me_returns_user(client: TestClient) -> None:
    register_user(client)
    login_response = client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "safe-password-123"},
    )

    assert login_response.status_code == 200
    assert login_response.json() == {"authenticated": True}
    cookies = login_response.headers.get_list("set-cookie")
    assert any("applyboard_access=" in cookie and "HttpOnly" in cookie for cookie in cookies)
    assert any("applyboard_refresh=" in cookie and "HttpOnly" in cookie for cookie in cookies)

    me_response = client.get("/auth/me")

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "person@example.com"
    assert "password_hash" not in me_response.json()


def test_invalid_credentials_return_generic_unauthorized(client: TestClient) -> None:
    register_user(client)

    wrong_password = client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "wrong-password"},
    )
    unknown_email = client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "wrong-password"},
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == "Invalid email or password."
    assert unknown_email.json()["detail"] == "Invalid email or password."


def test_me_rejects_missing_malformed_and_invalid_tokens(client: TestClient) -> None:
    expired_token = jwt.encode(
        {
            "sub": "1",
            "iat": datetime.now(timezone.utc) - timedelta(minutes=2),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        security.JWT_SECRET,
        algorithm=security.ALGORITHM,
    )
    missing = client.get("/auth/me")
    malformed = client.get(
        "/auth/me",
        headers={"Authorization": "not-a-bearer-token"},
    )
    invalid = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    expired = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert invalid.status_code == 401
    assert expired.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"


def test_registration_rejects_invalid_email_and_short_password(
    client: TestClient,
) -> None:
    bad_email = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "safe-password-123"},
    )
    short_password = client.post(
        "/auth/register",
        json={"email": "person@example.com", "password": "short"},
    )

    assert bad_email.status_code == 422
    assert short_password.status_code == 422


def test_login_reports_missing_jwt_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_user(client)

    monkeypatch.setattr(security, "JWT_SECRET", None)

    response = client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "safe-password-123"},
    )

    assert response.status_code == 503


def test_login_is_rate_limited(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security, "verify_password", lambda _password, _hashed: True)
    payload = {"email": "unknown@example.com", "password": "safe-password-123"}

    responses = [client.post("/auth/login", json=payload) for _ in range(11)]

    assert all(response.status_code == 401 for response in responses[:10])
    assert responses[10].status_code == 429


def test_demo_login_creates_seeded_read_only_workspace(client: TestClient) -> None:
    response = client.post("/auth/demo")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}

    me = client.get("/auth/me")
    applications = client.get("/applications")

    assert me.status_code == 200
    assert me.json()["email"] == "demo@applyboard.dev"
    assert applications.status_code == 200
    assert applications.json()["total"] == 5


def test_demo_workspace_rejects_application_mutations(client: TestClient) -> None:
    response = client.post("/auth/demo")
    assert response.status_code == 200
    headers = {"Origin": "http://localhost:5173"}
    payload = {
        "company": "New Company",
        "role": "Engineer",
        "platform": "Company website",
    }

    create = client.post("/applications", json=payload, headers=headers)
    assert create.status_code == 403
    assert create.json()["detail"] == (
        "The demo workspace is read-only. Create an account to manage applications."
    )



def test_refresh_rotates_and_revokes_previous_refresh_token(client: TestClient) -> None:
    register_user(client)
    login = client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "safe-password-123"},
    )
    old_refresh = login.cookies["applyboard_refresh"]

    refreshed = client.post("/auth/refresh", headers={"Origin": "http://localhost:5173"})
    assert refreshed.status_code == 200
    assert refreshed.json() == {"authenticated": True}
    new_refresh = refreshed.cookies["applyboard_refresh"]
    assert new_refresh != old_refresh

    replay = client.post(
        "/auth/refresh",
        headers={
            "Origin": "http://localhost:5173",
            "Cookie": f"applyboard_refresh={old_refresh}",
        },
    )
    assert replay.status_code == 401


def test_cookie_authenticated_mutations_require_trusted_origin(client: TestClient) -> None:
    register_user(client)
    client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "safe-password-123"},
    )
    payload = {
        "company": "Acme",
        "role": "Engineer",
        "platform": "Company website",
    }

    response = client.post("/applications", json=payload)

    assert response.status_code == 403


def test_logout_revokes_refresh_session(client: TestClient) -> None:
    register_user(client)
    client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "safe-password-123"},
    )

    logout = client.post("/auth/logout", headers={"Origin": "http://localhost:5173"})
    refresh = client.post("/auth/refresh", headers={"Origin": "http://localhost:5173"})

    assert logout.status_code == 204
    assert refresh.status_code == 401


def test_cookie_authenticated_write_succeeds_for_trusted_origin(client: TestClient) -> None:
    register_user(client)
    client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "safe-password-123"},
    )
    payload = {
        "company": "Acme",
        "role": "Engineer",
        "platform": "Company website",
    }

    response = client.post(
        "/applications",
        json=payload,
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 201
    assert response.json()["company"] == "Acme"
