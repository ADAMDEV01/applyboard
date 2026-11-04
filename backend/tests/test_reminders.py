from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app.jobs.send_followup_reminders import build_reminder_email
from app.models import Application, ApplicationStatus


def test_build_reminder_email_lists_each_follow_up(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SMTP_FROM_EMAIL", "reminders@example.com")
    application = Application(
        company="Example Labs",
        role="Backend Engineer",
        platform="Company website",
        status=ApplicationStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
        follow_up_at=datetime.now(timezone.utc) + timedelta(hours=4),
        user_id=1,
    )

    message = build_reminder_email([application])

    assert isinstance(message, EmailMessage)
    assert message["From"] == "reminders@example.com"
    assert "1 upcoming job follow-up" in message["Subject"]
    assert "Example Labs — Backend Engineer" in message.get_content()


def test_build_reminder_email_supports_multiple_applications(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SMTP_FROM_EMAIL", "reminders@example.com")
    applications = [
        Application(
            company=company,
            role="Software Engineer",
            platform="LinkedIn",
            status=ApplicationStatus.APPLIED,
            applied_at=datetime.now(timezone.utc),
            follow_up_at=datetime.now(timezone.utc) + timedelta(hours=3),
            user_id=1,
        )
        for company in ("Northstar", "Orbit")
    ]

    message = build_reminder_email(applications)

    assert "2 upcoming job follow-up" in message["Subject"]
    assert "Northstar" in message.get_content()
    assert "Orbit" in message.get_content()
