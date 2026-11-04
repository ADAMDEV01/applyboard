import logging
import os
import smtplib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import select

from app.db.database import SessionLocal
from app.models import Application, ApplicationStatus, User

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = (
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
    ApplicationStatus.GHOSTED,
)


def build_reminder_email(applications: list[Application]) -> EmailMessage:
    sender = os.environ["SMTP_FROM_EMAIL"]
    message = EmailMessage()
    message["Subject"] = f"You have {len(applications)} upcoming job follow-up(s)"
    message["From"] = sender
    lines = [
        "Here are the job applications with follow-ups scheduled in the next 24 hours:",
        "",
    ]
    for application in applications:
        scheduled = application.follow_up_at.isoformat() if application.follow_up_at else "soon"
        lines.append(f"- {application.company} — {application.role} ({scheduled})")
    lines.extend(["", "Open Applyboard to review your next steps."])
    message.set_content("\n".join(lines))
    return message


def send_message(message: EmailMessage, recipient: str) -> None:
    message["To"] = recipient
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "20"))

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
            if username and password:
                server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(message)


def main() -> int:
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=24)
    with SessionLocal() as db:
        due_rows = db.execute(
            select(Application, User.email)
            .join(User, User.id == Application.user_id)
            .where(
                Application.follow_up_at >= now,
                Application.follow_up_at <= cutoff,
                Application.follow_up_reminder_sent_at.is_(None),
                Application.status.not_in(TERMINAL_STATUSES),
            )
            .order_by(User.email, Application.follow_up_at)
        ).all()

        grouped: dict[str, list[Application]] = defaultdict(list)
        for application, email in due_rows:
            grouped[email].append(application)

        sent_at = datetime.now(timezone.utc)
        for recipient, applications in grouped.items():
            message = build_reminder_email(applications)
            send_message(message, recipient)
            for application in applications:
                application.follow_up_reminder_sent_at = sent_at
            logger.info("Sent %s follow-up reminder(s) to %s", len(applications), recipient)

        db.commit()
        logger.info("Processed reminders for %s user(s)", len(grouped))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    raise SystemExit(main())
