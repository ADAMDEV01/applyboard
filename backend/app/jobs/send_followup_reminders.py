import hashlib
import logging
import os
import smtplib
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import and_, or_, select, update

from app.db.database import SessionLocal
from app.models import (
    Application,
    ApplicationStatus,
    ReminderOutbox,
    User,
)

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = (
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
    ApplicationStatus.GHOSTED,
)
MAX_ATTEMPTS = 5
LEASE_DURATION = timedelta(minutes=5)
MAX_RETRY_DELAY_SECONDS = 6 * 60 * 60


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
        scheduled = (
            application.follow_up_at.isoformat()
            if application.follow_up_at
            else "soon"
        )
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


def reminder_dedupe_key(application_id: int, scheduled_for: datetime) -> str:
    normalized = scheduled_for.astimezone(timezone.utc).isoformat(timespec="microseconds")
    value = f"follow-up:{application_id}:{normalized}".encode()
    return hashlib.sha256(value).hexdigest()


def due_reminder_statement(now: datetime, cutoff: datetime):
    """Lock due applications while their durable outbox rows are created."""
    return (
        select(Application, User.email)
        .join(User, User.id == Application.user_id)
        .where(
            Application.follow_up_at >= now,
            Application.follow_up_at <= cutoff,
            Application.follow_up_reminder_sent_at.is_(None),
            Application.status.not_in(TERMINAL_STATUSES),
        )
        .order_by(User.email, Application.follow_up_at, Application.id)
        .with_for_update(skip_locked=True, of=Application)
    )


def enqueue_due_reminders(
    db,
    now: datetime,
    cutoff: datetime,
) -> int:
    """Persist one idempotent outbox event for every due application reminder."""
    rows = db.execute(due_reminder_statement(now, cutoff)).all()
    created = 0

    for application, recipient in rows:
        scheduled_for = application.follow_up_at
        if scheduled_for is None:
            continue
        dedupe_key = reminder_dedupe_key(application.id, scheduled_for)
        existing = db.scalar(
            select(ReminderOutbox).where(ReminderOutbox.dedupe_key == dedupe_key)
        )
        if existing is not None:
            # A user may move a reminder away and later restore the exact same
            # timestamp. Re-arm the cancelled deduplicated row instead of losing it.
            if existing.status == "cancelled":
                existing.status = "pending"
                existing.attempts = 0
                existing.available_at = now
                existing.locked_at = None
                existing.lock_owner = None
                existing.sent_at = None
                existing.last_error = None
                created += 1
            continue
        db.add(
            ReminderOutbox(
                application_id=application.id,
                recipient_email=recipient,
                company=application.company,
                role=application.role,
                scheduled_for=scheduled_for,
                dedupe_key=dedupe_key,
                status="pending",
                attempts=0,
                available_at=now,
            )
        )
        created += 1

    db.commit()
    return created


def claim_pending_outbox(
    db,
    *,
    worker_id: str,
    now: datetime,
    batch_size: int = 50,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Claim pending or abandoned rows with SKIP LOCKED and a recoverable lease."""
    lease_expired_before = now - LEASE_DURATION
    db.execute(
        update(ReminderOutbox)
        .where(
            ReminderOutbox.status == "processing",
            ReminderOutbox.locked_at < lease_expired_before,
            ReminderOutbox.attempts >= max_attempts,
        )
        .values(
            status="failed",
            lock_owner=None,
            locked_at=None,
            last_error="Worker lease expired after the final delivery attempt.",
        )
    )

    claimable = or_(
        and_(
            ReminderOutbox.status == "pending",
            ReminderOutbox.available_at <= now,
        ),
        and_(
            ReminderOutbox.status == "processing",
            ReminderOutbox.locked_at < lease_expired_before,
            ReminderOutbox.attempts < max_attempts,
        ),
    )
    rows = db.scalars(
        select(ReminderOutbox)
        .where(claimable)
        .order_by(ReminderOutbox.available_at, ReminderOutbox.created_at, ReminderOutbox.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()

    claimed: list[int] = []
    for row in rows:
        row.status = "processing"
        row.attempts += 1
        row.locked_at = now
        row.lock_owner = worker_id
        claimed.append(row.id)

    db.commit()
    return claimed


def retry_delay(attempts: int) -> timedelta:
    seconds = min(60 * (2 ** max(attempts - 1, 0)), MAX_RETRY_DELAY_SECONDS)
    return timedelta(seconds=seconds)


def process_claimed_message(message_id: int, *, worker_id: str) -> str:
    """Send one leased item while locking its source application row.

    SMTP is an external side effect, so delivery is intentionally at-least-once:
    a process crash after SMTP accepts a message but before the database commit can
    cause a retry. A stable Message-ID is reused to help downstream deduplication.
    """
    try:
        with SessionLocal() as db:
            with db.begin():
                outbox = db.scalar(
                    select(ReminderOutbox)
                    .where(
                        ReminderOutbox.id == message_id,
                        ReminderOutbox.status == "processing",
                        ReminderOutbox.lock_owner == worker_id,
                    )
                    .with_for_update()
                )
                if outbox is None:
                    return "skipped"

                application = db.scalar(
                    select(Application)
                    .where(Application.id == outbox.application_id)
                    .with_for_update()
                )
                if (
                    application is None
                    or application.follow_up_at is None
                    or application.follow_up_at != outbox.scheduled_for
                    or application.follow_up_reminder_sent_at is not None
                    or application.status in TERMINAL_STATUSES
                ):
                    outbox.status = "cancelled"
                    outbox.lock_owner = None
                    outbox.locked_at = None
                    outbox.last_error = "Reminder became stale before delivery."
                    return "cancelled"

                current_user = db.get(User, application.user_id)
                if current_user is None:
                    outbox.status = "cancelled"
                    outbox.lock_owner = None
                    outbox.locked_at = None
                    outbox.last_error = "Application owner no longer exists."
                    return "cancelled"
                outbox.recipient_email = current_user.email

                message = build_reminder_email([application])
                message["Message-ID"] = f"<applyboard-reminder-{outbox.dedupe_key}@applyboard>"
                send_message(message, current_user.email)

                sent_at = datetime.now(timezone.utc)
                application.follow_up_reminder_sent_at = sent_at
                outbox.status = "sent"
                outbox.sent_at = sent_at
                outbox.lock_owner = None
                outbox.locked_at = None
                outbox.last_error = None
                return "sent"
    except Exception as error:
        logger.warning("Reminder outbox delivery failed for message %s: %s", message_id, error)
        with SessionLocal() as db:
            with db.begin():
                outbox = db.scalar(
                    select(ReminderOutbox)
                    .where(
                        ReminderOutbox.id == message_id,
                        ReminderOutbox.status == "processing",
                        ReminderOutbox.lock_owner == worker_id,
                    )
                    .with_for_update()
                )
                if outbox is None:
                    return "skipped"
                outbox.last_error = str(error)[:2_000]
                outbox.lock_owner = None
                outbox.locked_at = None
                if outbox.attempts >= MAX_ATTEMPTS:
                    outbox.status = "failed"
                    logger.error(
                        "Reminder outbox message %s exhausted %s attempts.",
                        message_id,
                        outbox.attempts,
                    )
                    return "failed"
                outbox.status = "pending"
                outbox.available_at = datetime.now(timezone.utc) + retry_delay(outbox.attempts)
                return "retry"


def process_pending_outbox(
    *,
    batch_size: int = 50,
    worker_id: str | None = None,
) -> dict[str, int]:
    worker_id = worker_id or uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        claimed_ids = claim_pending_outbox(
            db,
            worker_id=worker_id,
            now=now,
            batch_size=batch_size,
        )

    counts: dict[str, int] = defaultdict(int)
    for message_id in claimed_ids:
        counts[process_claimed_message(message_id, worker_id=worker_id)] += 1
    return dict(counts)


def main() -> int:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        enqueued = enqueue_due_reminders(db, now, now + timedelta(hours=24))

    results = process_pending_outbox()
    logger.info("Enqueued %s reminder(s); outbox results: %s", enqueued, results)

    # A temporary SMTP failure is durably scheduled for retry, so the cron run
    # succeeds. Exhausted messages remain visible as FAILED rows for operations.
    if results.get("failed", 0):
        logger.error("%s reminder(s) exhausted their retry budget.", results["failed"])
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    raise SystemExit(main())
