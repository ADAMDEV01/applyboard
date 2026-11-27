from fastapi.testclient import TestClient

from app.core import rate_limit as rate_limit_module
from app.core import security


def test_rate_limit_window_resets_after_expiry(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(rate_limit_module, "time", lambda: 1_000_000.0)
    monkeypatch.setattr(security, "verify_password", lambda _password, _hashed: True)
    payload = {"email": "unknown@example.com", "password": "safe-password-123"}

    first_window = [client.post("/auth/login", json=payload) for _ in range(11)]
    assert all(response.status_code == 401 for response in first_window[:10])
    assert first_window[10].status_code == 429
    assert int(first_window[10].headers["retry-after"]) > 0

    monkeypatch.setattr(rate_limit_module, "time", lambda: 1_000_061.0)
    after_expiry = client.post("/auth/login", json=payload)

    assert after_expiry.status_code == 401


def test_rate_limits_are_isolated_by_authentication_endpoint(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(rate_limit_module, "time", lambda: 2_000_000.0)
    monkeypatch.setattr(security, "verify_password", lambda _password, _hashed: True)
    login_payload = {"email": "unknown@example.com", "password": "safe-password-123"}

    for _ in range(11):
        login = client.post("/auth/login", json=login_payload)
    assert login.status_code == 429

    registration = client.post(
        "/auth/register",
        json={"email": "new-user@example.com", "password": "safe-password-123"},
    )
    assert registration.status_code == 201
