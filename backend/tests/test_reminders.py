from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest

from app.jobs.send_followup_reminders import build_reminder_email, send_message
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



def test_smtp_failure_is_propagated_so_the_job_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenSMTP:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def starttls(self) -> None:
            return None

        def send_message(self, _message: EmailMessage) -> None:
            raise OSError("temporary SMTP outage")

    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "reminders@example.test")
    monkeypatch.setattr("smtplib.SMTP", BrokenSMTP)
    message = EmailMessage()
    message["Subject"] = "Follow-up reminder"
    message.set_content("Test reminder")

    with pytest.raises(OSError, match="temporary SMTP outage"):
        send_message(message, "person@example.test")
