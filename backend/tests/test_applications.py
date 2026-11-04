from datetime import datetime, timezone

from fastapi.testclient import TestClient


def authenticated_headers(client: TestClient, email: str) -> dict[str, str]:
    registration = client.post(
        "/auth/register",
        json={"email": email, "password": "safe-password-123"},
    )
    assert registration.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "safe-password-123"},
    )
    assert login.status_code == 200
    token = login.cookies.get("applyboard_access")
    assert token, "login did not set the HttpOnly access cookie"
    return {"Authorization": f"Bearer {token}"}


def create_application(
    client: TestClient,
    headers: dict[str, str],
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Northwind",
        "role": "Backend Engineer",
        "platform": "LinkedIn",
    }
    payload.update(overrides)
    response = client.post("/applications", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_application_create_list_read_update_delete(client: TestClient) -> None:
    headers = authenticated_headers(client, "person@example.com")
    application = create_application(
        client,
        headers,
        url="https://example.com/jobs/123",
        notes="Follow up next week",
    )

    assert application["company"] == "Northwind"
    assert application["status"] == "applied"
    assert application["url"] == "https://example.com/jobs/123"

    listing = client.get("/applications", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == application["id"]

    detail = client.get(f"/applications/{application['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["notes"] == "Follow up next week"

    updated = client.patch(
        f"/applications/{application['id']}",
        headers=headers,
        json={"notes": "Interview scheduled", "status": "replied"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "replied"
    assert updated.json()["notes"] == "Interview scheduled"
    assert datetime.fromisoformat(updated.json()["last_update_at"]) >= datetime.fromisoformat(
        application["last_update_at"]
    )

    deleted = client.delete(f"/applications/{application['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(
        f"/applications/{application['id']}",
        headers=headers,
    ).status_code == 404


def test_create_accepts_custom_application_date_and_optional_fields(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "person@example.com")
    applied_at = datetime(2025, 1, 15, 12, 30, tzinfo=timezone.utc).isoformat()

    application = create_application(
        client,
        headers,
        applied_at=applied_at,
        status="interview",
    )

    assert application["status"] == "interview"
    assert datetime.fromisoformat(application["applied_at"]) == datetime.fromisoformat(
        applied_at
    )
    assert application["url"] is None
    assert application["notes"] is None


def test_list_paginates_filters_searches_and_sorts(client: TestClient) -> None:
    headers = authenticated_headers(client, "person@example.com")
    create_application(
        client,
        headers,
        company="Beta Labs",
        role="Data Scientist",
        platform="Indeed",
        status="replied",
    )
    create_application(
        client,
        headers,
        company="Acme",
        role="Platform Engineer",
        platform="LinkedIn",
        status="interview",
    )
    create_application(
        client,
        headers,
        company="Acme",
        role="QA Engineer",
        platform="LinkedIn",
    )

    first_page = client.get(
        "/applications?page=1&page_size=2&sort_by=company&order=asc",
        headers=headers,
    ).json()
    second_page = client.get(
        "/applications?page=2&page_size=2&sort_by=company&order=asc",
        headers=headers,
    ).json()
    assert first_page["total"] == 3
    assert first_page["pages"] == 2
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1
    assert first_page["items"][0]["company"] == "Acme"

    filtered = client.get(
        "/applications?status=interview&platform=linkedin&search=Platform",
        headers=headers,
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["role"] == "Platform Engineer"

    role_search = client.get(
        "/applications?search=Scientist",
        headers=headers,
    ).json()
    assert role_search["total"] == 1
    assert role_search["items"][0]["company"] == "Beta Labs"


def test_user_cannot_read_update_or_delete_another_users_application(
    client: TestClient,
) -> None:
    owner_headers = authenticated_headers(client, "owner@example.com")
    other_headers = authenticated_headers(client, "other@example.com")
    application = create_application(client, owner_headers)
    application_id = application["id"]

    assert client.get(
        f"/applications/{application_id}",
        headers=other_headers,
    ).status_code == 404
    assert client.patch(
        f"/applications/{application_id}",
        headers=other_headers,
        json={"company": "Stolen"},
    ).status_code == 404
    assert client.delete(
        f"/applications/{application_id}",
        headers=other_headers,
    ).status_code == 404

    other_list = client.get("/applications", headers=other_headers).json()
    assert other_list["total"] == 0


def test_private_application_routes_require_authentication(
    client: TestClient,
) -> None:
    assert client.get("/applications").status_code == 401
    assert client.post(
        "/applications",
        json={
            "company": "Northwind",
            "role": "Engineer",
            "platform": "LinkedIn",
        },
    ).status_code == 401


def test_application_validation_and_status_transitions(client: TestClient) -> None:
    headers = authenticated_headers(client, "person@example.com")

    invalid_status = client.post(
        "/applications",
        headers=headers,
        json={
            "company": "Northwind",
            "role": "Engineer",
            "platform": "LinkedIn",
            "status": "not-a-status",
        },
    )
    invalid_url = client.post(
        "/applications",
        headers=headers,
        json={
            "company": "Northwind",
            "role": "Engineer",
            "platform": "LinkedIn",
            "url": "not a URL",
        },
    )
    blank_company = client.post(
        "/applications",
        headers=headers,
        json={
            "company": "   ",
            "role": "Engineer",
            "platform": "LinkedIn",
        },
    )
    assert invalid_status.status_code == 422
    assert invalid_url.status_code == 422
    assert blank_company.status_code == 422

    application = create_application(client, headers, status="interview")
    backward = client.patch(
        f"/applications/{application['id']}",
        headers=headers,
        json={"status": "applied"},
    )
    assert backward.status_code == 409
    assert client.patch(
        f"/applications/{application['id']}",
        headers=headers,
        json={"company": None},
    ).status_code == 422
    assert client.patch(
        f"/applications/{application['id']}",
        headers=headers,
        json={},
    ).status_code == 422

    advanced = client.patch(
        f"/applications/{application['id']}",
        headers=headers,
        json={"status": "offer"},
    )
    assert advanced.status_code == 200
    terminal = client.patch(
        f"/applications/{application['id']}",
        headers=headers,
        json={"status": "rejected"},
    )
    assert terminal.status_code == 409


def test_application_pagination_parameters_are_bounded(client: TestClient) -> None:
    headers = authenticated_headers(client, "person@example.com")

    invalid_page = client.get("/applications?page=0", headers=headers)
    oversized_page = client.get("/applications?page_size=101", headers=headers)
    invalid_sort = client.get("/applications?sort_by=notes", headers=headers)

    assert invalid_page.status_code == 422
    assert oversized_page.status_code == 422
    assert invalid_sort.status_code == 422

