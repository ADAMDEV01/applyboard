from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.database import create_database_engine
from app.jobs import send_followup_reminders as job
from app.models import (
    Application,
    ApplicationStatus,
    ReminderOutbox,
    User,
)


def make_database(tmp_path: Path) -> tuple[sessionmaker[Session], object]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory, engine


def create_due_application(factory: sessionmaker[Session]) -> tuple[int, datetime]:
    now = datetime.now(timezone.utc)
    with factory() as db:
        user = User(
            email="outbox-user@example.test",
            password_hash="integration-only",
        )
        application = Application(
            user=user,
            company="Outbox Labs",
            role="Backend Engineer",
            platform="Company website",
            status=ApplicationStatus.APPLIED,
            applied_at=now - timedelta(days=3),
            follow_up_at=now + timedelta(hours=2),
        )
        db.add(application)
        db.commit()
        return application.id, application.follow_up_at


def enqueue_one(factory: sessionmaker[Session], now: datetime) -> int:
    with factory() as db:
        return job.enqueue_due_reminders(db, now, now + timedelta(hours=24))


def test_enqueue_is_idempotent_per_application_and_scheduled_time(tmp_path: Path) -> None:
    factory, engine = make_database(tmp_path)
    try:
        application_id, scheduled_for = create_due_application(factory)
        now = datetime.now(timezone.utc)

        assert enqueue_one(factory, now) == 1
        assert enqueue_one(factory, now) == 0

        with factory() as db:
            rows = db.scalars(
                select(ReminderOutbox).where(
                    ReminderOutbox.application_id == application_id
                )
            ).all()
            assert len(rows) == 1
            assert rows[0].scheduled_for == scheduled_for
            assert rows[0].status == "pending"
            assert rows[0].attempts == 0
    finally:
        engine.dispose()


def test_successful_delivery_marks_outbox_and_application_sent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    factory, engine = make_database(tmp_path)
    monkeypatch.setenv("SMTP_FROM_EMAIL", "reminders@example.test")
    try:
        application_id, _ = create_due_application(factory)
        enqueue_one(factory, datetime.now(timezone.utc))
        with factory() as db:
            owner = db.scalar(select(User).where(User.email == "outbox-user@example.test"))
            assert owner is not None
            owner.email = "updated-outbox-user@example.test"
            db.commit()
            claimed = job.claim_pending_outbox(
                db,
                worker_id="worker-test",
                now=datetime.now(timezone.utc),
                batch_size=1,
            )
        assert len(claimed) == 1
        captured = []

        def capture_message(message, recipient):
            captured.append((message, recipient))

        monkeypatch.setattr(job, "SessionLocal", factory)
        monkeypatch.setattr(job, "send_message", capture_message)

        assert job.process_claimed_message(
            claimed[0],
            worker_id="worker-test",
        ) == "sent"

        with factory() as db:
            outbox = db.get(ReminderOutbox, claimed[0])
            application = db.get(Application, application_id)
            assert outbox is not None
            assert application is not None
            assert outbox.status == "sent"
            assert outbox.sent_at is not None
            assert outbox.lock_owner is None
            assert application.follow_up_reminder_sent_at is not None
            assert captured[0][1] == "updated-outbox-user@example.test"
            assert captured[0][0]["Message-ID"] == (
                f"<applyboard-reminder-{outbox.dedupe_key}@applyboard>"
            )
    finally:
        engine.dispose()


def test_smtp_failure_is_requeued_with_backoff_and_not_marked_sent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    factory, engine = make_database(tmp_path)
    monkeypatch.setenv("SMTP_FROM_EMAIL", "reminders@example.test")
    try:
        application_id, _ = create_due_application(factory)
        enqueue_one(factory, datetime.now(timezone.utc))
        with factory() as db:
            claimed = job.claim_pending_outbox(
                db,
                worker_id="worker-retry",
                now=datetime.now(timezone.utc),
                batch_size=1,
            )
        monkeypatch.setattr(job, "SessionLocal", factory)

        def fail_delivery(_message, _recipient):
            raise OSError("temporary SMTP outage")

        monkeypatch.setattr(job, "send_message", fail_delivery)
        before = datetime.now(timezone.utc)

        assert job.process_claimed_message(
            claimed[0],
            worker_id="worker-retry",
        ) == "retry"

        with factory() as db:
            outbox = db.get(ReminderOutbox, claimed[0])
            application = db.get(Application, application_id)
            assert outbox is not None
            assert application is not None
            assert outbox.status == "pending"
            assert outbox.attempts == 1
            assert outbox.available_at >= before + timedelta(seconds=59)
            assert outbox.last_error == "temporary SMTP outage"
            assert outbox.lock_owner is None
            assert application.follow_up_reminder_sent_at is None
    finally:
        engine.dispose()


def test_changed_follow_up_cancels_stale_outbox_without_sending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    factory, engine = make_database(tmp_path)
    try:
        application_id, _ = create_due_application(factory)
        enqueue_one(factory, datetime.now(timezone.utc))
        with factory() as db:
            claimed = job.claim_pending_outbox(
                db,
                worker_id="worker-stale",
                now=datetime.now(timezone.utc),
                batch_size=1,
            )
            application = db.get(Application, application_id)
            assert application is not None
            application.follow_up_at = datetime.now(timezone.utc) + timedelta(days=3)
            db.commit()

        monkeypatch.setattr(job, "SessionLocal", factory)
        sent = []
        monkeypatch.setattr(job, "send_message", lambda *args: sent.append(args))

        assert job.process_claimed_message(
            claimed[0],
            worker_id="worker-stale",
        ) == "cancelled"
        assert sent == []

        with factory() as db:
            outbox = db.get(ReminderOutbox, claimed[0])
            assert outbox is not None
            assert outbox.status == "cancelled"
    finally:
        engine.dispose()


def test_expired_worker_lease_can_be_reclaimed(tmp_path: Path) -> None:
    factory, engine = make_database(tmp_path)
    try:
        create_due_application(factory)
        enqueue_one(factory, datetime.now(timezone.utc))
        first_now = datetime.now(timezone.utc)
        with factory() as db:
            first = job.claim_pending_outbox(
                db,
                worker_id="worker-crashed",
                now=first_now,
                batch_size=1,
            )
            assert len(first) == 1

        with factory() as db:
            second = job.claim_pending_outbox(
                db,
                worker_id="worker-recovery",
                now=first_now + timedelta(minutes=6),
                batch_size=1,
            )
        assert second == first

        with factory() as db:
            row = db.get(ReminderOutbox, first[0])
            assert row is not None
            assert row.status == "processing"
            assert row.lock_owner == "worker-recovery"
            assert row.attempts == 2
    finally:
        engine.dispose()


def test_retry_backoff_is_bounded() -> None:
    assert job.retry_delay(1) == timedelta(seconds=60)
    assert job.retry_delay(2) == timedelta(seconds=120)
    assert job.retry_delay(20) == timedelta(hours=6)



def test_cancelled_outbox_is_rearmed_when_user_restores_the_same_schedule(
    tmp_path: Path,
    monkeypatch,
) -> None:
    factory, engine = make_database(tmp_path)
    try:
        application_id, scheduled_for = create_due_application(factory)
        enqueue_one(factory, datetime.now(timezone.utc))
        with factory() as db:
            claimed = job.claim_pending_outbox(
                db,
                worker_id="worker-rearm",
                now=datetime.now(timezone.utc),
                batch_size=1,
            )
            application = db.get(Application, application_id)
            assert application is not None
            application.follow_up_at = scheduled_for + timedelta(days=2)
            db.commit()

        monkeypatch.setattr(job, "SessionLocal", factory)
        monkeypatch.setattr(job, "send_message", lambda *_args: None)
        assert job.process_claimed_message(
            claimed[0],
            worker_id="worker-rearm",
        ) == "cancelled"

        with factory() as db:
            application = db.get(Application, application_id)
            assert application is not None
            application.follow_up_at = scheduled_for
            db.commit()

        assert enqueue_one(factory, datetime.now(timezone.utc)) == 1
        with factory() as db:
            row = db.get(ReminderOutbox, claimed[0])
            assert row is not None
            assert row.status == "pending"
            assert row.attempts == 0
            assert row.lock_owner is None
            assert row.last_error is None
    finally:
        engine.dispose()
