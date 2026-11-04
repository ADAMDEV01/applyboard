from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.test_applications import authenticated_headers, create_application


def test_analytics_count_unique_responses_and_separate_ghosting_from_inactivity(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "person@example.com")
    now = datetime.now(timezone.utc)
    create_application(
        client,
        headers,
        company="Long Wait Co",
        applied_at=(now - timedelta(days=20)).isoformat(),
        platform="LinkedIn",
    )
    first_response = create_application(
        client,
        headers,
        company="Responded Co",
        applied_at=(now - timedelta(days=5)).isoformat(),
        platform="Indeed",
        follow_up_at=(now + timedelta(days=7)).isoformat(),
    )
    client.patch(
        f"/applications/{first_response['id']}",
        headers=headers,
        json={"status": "replied"},
    )
    create_application(
        client,
        headers,
        company="Outcome Co",
        applied_at=(now - timedelta(days=2)).isoformat(),
        platform="Indeed",
        status="rejected",
        follow_up_at=(now + timedelta(days=3)).isoformat(),
    )
    create_application(
        client,
        headers,
        company="Old Follow-up Co",
        applied_at=(now - timedelta(days=30)).isoformat(),
        follow_up_at=(now - timedelta(days=1)).isoformat(),
    )
    create_application(
        client,
        headers,
        company="Recent Application",
        applied_at=(now - timedelta(days=13)).isoformat(),
    )
    create_application(
        client,
        headers,
        company="Interviewing",
        applied_at=(now - timedelta(days=20)).isoformat(),
        status="interview",
    )

    summary = client.get("/stats/summary", headers=headers).json()
    assert summary["total_applications"] == 6
    assert summary["responded_applications"] == 1
    assert summary["response_rate"] == pytest.approx(1 / 6, abs=0.0001)
    assert summary["average_time_to_first_response_days"] is not None
    assert {item["status"]: item["count"] for item in summary["by_status"]} == {
        "applied": 3,
        "replied": 1,
        "rejected": 1,
        "interview": 1,
        "offer": 0,
        "ghosted": 0,
    }
    assert [item["application"]["company"] for item in summary["may_be_ghosted"]] == [
        "Old Follow-up Co",
        "Long Wait Co",
    ]
    assert [
        item["application"]["company"] for item in summary["upcoming_followups"]
    ] == ["Responded Co"]

    by_platform = client.get("/stats/platforms", headers=headers).json()
    assert len(by_platform) == 2
    indeed = next(item for item in by_platform if item["platform"] == "Indeed")
    assert indeed["total_applications"] == 2
    assert indeed["responded_applications"] == 1
    assert indeed["response_rate"] == 0.5

    responses = client.get("/stats/responses", headers=headers).json()
    assert responses["total_applications"] == 6
    assert responses["responded_applications"] == 1
    assert responses["response_rate"] == pytest.approx(1 / 6, abs=0.0001)


def test_initial_outcome_status_does_not_fabricate_response_time(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "person@example.com")
    create_application(
        client,
        headers,
        status="offer",
        applied_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
    )

    metrics = client.get("/stats/responses", headers=headers).json()

    assert metrics["total_applications"] == 1
    assert metrics["responded_applications"] == 0
    assert metrics["response_rate"] == 0.0
    assert metrics["average_time_to_first_response_days"] is None


def test_empty_user_analytics_return_zero_and_empty_groups(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "person@example.com")

    summary = client.get("/stats/summary", headers=headers).json()
    platforms = client.get("/stats/platforms", headers=headers).json()
    responses = client.get("/stats/responses", headers=headers).json()

    assert summary["total_applications"] == 0
    assert summary["response_rate"] == 0.0
    assert platforms == []
    assert responses["average_time_to_first_response_days"] is None


def test_analytics_are_user_scoped(client: TestClient) -> None:
    owner_headers = authenticated_headers(client, "owner@example.com")
    other_headers = authenticated_headers(client, "other@example.com")
    create_application(client, owner_headers)

    summary = client.get("/stats/summary", headers=other_headers).json()

    assert summary["total_applications"] == 0
    assert summary["may_be_ghosted"] == []
