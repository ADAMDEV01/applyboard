from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from tests.test_applications import authenticated_headers, create_application


def test_analytics_include_exact_ghosting_and_follow_up_cutoffs(
    client: TestClient,
) -> None:
    headers = authenticated_headers(client, "boundary@example.com")
    now = datetime.now(timezone.utc)
    create_application(
        client,
        headers,
        company="Exactly Fourteen Days",
        applied_at=(now - timedelta(days=14)).isoformat(),
    )
    create_application(
        client,
        headers,
        company="Not Yet Fourteen Days",
        applied_at=(now - timedelta(days=14) + timedelta(minutes=1)).isoformat(),
    )
    create_application(
        client,
        headers,
        company="Exactly Thirty Day Follow-up",
        follow_up_at=(now + timedelta(days=30)).isoformat(),
    )
    create_application(
        client,
        headers,
        company="Beyond Thirty Day Follow-up",
        follow_up_at=(now + timedelta(days=30, minutes=1)).isoformat(),
    )

    summary = client.get("/stats/summary", headers=headers).json()

    assert [
        item["application"]["company"] for item in summary["may_be_ghosted"]
    ] == ["Exactly Fourteen Days"]
    assert [
        item["application"]["company"] for item in summary["upcoming_followups"]
    ] == ["Exactly Thirty Day Follow-up"]
