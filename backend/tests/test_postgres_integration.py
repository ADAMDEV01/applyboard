from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from fastapi import HTTPException
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
    RefreshSession,
    ReminderOutbox,
    User,
)
from app.jobs.send_followup_reminders import claim_pending_outbox, due_reminder_statement
from app.routers.applications import update_application
from app.schemas.application import ApplicationUpdate


@pytest.fixture(scope="module")
def postgres_sessions() -> sessionmaker[Session]:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration tests require DATABASE_URL")
    engine = create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield factory
    finally:
        engine.dispose()


def _new_user(db: Session) -> User:
    suffix = uuid.uuid4().hex
    user = User(email=f"pg-{suffix}@example.test", password_hash="test-hash")
    db.add(user)
    db.flush()
    return user


def test_postgres_foreign_keys_and_status_check_constraints(
    postgres_sessions: sessionmaker[Session],
) -> None:
    with postgres_sessions() as db:
        invalid_fk = text(
            """
            INSERT INTO applications
                (user_id, company, role, platform, status, applied_at, last_update_at, created_at)
            VALUES
                (-987654321, 'Bad FK', 'Engineer', 'Test', 'applied', NOW(), NOW(), NOW())
            """
        )
        with pytest.raises(IntegrityError):
            db.execute(invalid_fk)
        db.rollback()

        user = _new_user(db)
        db.commit()
        invalid_status = text(
            """
            INSERT INTO applications
                (user_id, company, role, platform, status, applied_at, last_update_at, created_at)
            VALUES
                (:user_id, 'Bad status', 'Engineer', 'Test', 'invalid', NOW(), NOW(), NOW())
            """
        )
        with pytest.raises(IntegrityError):
            db.execute(invalid_status, {"user_id": user.id})
        db.rollback()
        assert db.scalar(select(User.id).where(User.id == user.id)) == user.id


def test_postgres_transaction_rollback_leaves_no_application(
    postgres_sessions: sessionmaker[Session],
) -> None:
    with postgres_sessions() as db:
        user = _new_user(db)
        db.commit()
        application_id: int | None = None
        with pytest.raises(RuntimeError):
            with db.begin():
                application = Application(
                    user_id=user.id,
                    company="Rollback Co",
                    role="Engineer",
                    platform="Test",
                    status=ApplicationStatus.APPLIED,
                    applied_at=datetime.now(timezone.utc),
                )
                db.add(application)
                db.flush()
                application_id = application.id
                raise RuntimeError("force transaction rollback")
        assert application_id is not None
        assert db.get(Application, application_id) is None


def test_postgres_refresh_token_conditional_update_allows_one_consumer(
    postgres_sessions: sessionmaker[Session],
) -> None:
    token_hash = uuid.uuid4().hex + uuid.uuid4().hex
    with postgres_sessions() as db:
        user = _new_user(db)
        session = RefreshSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            created_at=datetime.now(timezone.utc),
        )
        db.add(session)
        db.commit()
        session_id = session.id

    barrier = threading.Barrier(2)

    def consume() -> int:
        with postgres_sessions() as db:
            barrier.wait(timeout=10)
            result = db.execute(
                update(RefreshSession)
                .where(
                    RefreshSession.id == session_id,
                    RefreshSession.token_hash == token_hash,
                    RefreshSession.revoked_at.is_(None),
                    RefreshSession.expires_at > datetime.now(timezone.utc),
                )
                .values(revoked_at=datetime.now(timezone.utc))
            )
            affected = int(result.rowcount or 0)
            db.commit()
            return affected

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: consume(), range(2)))

    assert sorted(outcomes) == [0, 1]
    with postgres_sessions() as db:
        stored = db.get(RefreshSession, session_id)
        assert stored is not None
        assert stored.revoked_at is not None


def test_postgres_unique_email_constraint_is_enforced(
    postgres_sessions: sessionmaker[Session],
) -> None:
    email = f"unique-{uuid.uuid4().hex}@example.test"
    with postgres_sessions() as db:
        db.add(User(email=email, password_hash="first"))
        db.commit()
        db.add(User(email=email, password_hash="second"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(User.id).where(User.email == email)) is not None



def test_postgres_concurrent_status_updates_keep_event_history_linear(
    postgres_sessions: sessionmaker[Session],
) -> None:
    with postgres_sessions() as db:
        user = _new_user(db)
        application = Application(
            user_id=user.id,
            company="Concurrent History Co",
            role="Engineer",
            platform="PostgreSQL integration",
            status=ApplicationStatus.APPLIED,
            applied_at=datetime.now(timezone.utc),
        )
        application.events.append(
            ApplicationEvent(
                previous_status=None,
                new_status=ApplicationStatus.APPLIED,
                event_type=ApplicationEventType.CREATED,
                note="Created for concurrency test",
            )
        )
        db.add(application)
        db.commit()
        user_id = user.id
        application_id = application.id

    barrier = threading.Barrier(2)

    def apply_status(target: ApplicationStatus) -> tuple[str, int | str]:
        with postgres_sessions() as db:
            user = db.get(User, user_id)
            assert user is not None
            barrier.wait(timeout=10)
            try:
                result = update_application(
                    application_id,
                    ApplicationUpdate(status=target),
                    user,
                    db,
                )
                return ("ok", result.status.value)
            except HTTPException as error:
                db.rollback()
                return ("http_error", error.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(
            apply_status,
            [ApplicationStatus.REPLIED, ApplicationStatus.INTERVIEW],
        ))

    successful_updates = sum(outcome[0] == "ok" for outcome in outcomes)
    assert successful_updates >= 1
    assert all(
        outcome[0] == "ok" or outcome == ("http_error", 409)
        for outcome in outcomes
    )

    with postgres_sessions() as db:
        saved = db.get(Application, application_id)
        assert saved is not None
        history = list(
            db.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application_id)
                .order_by(ApplicationEvent.id)
            )
        )
        transitions = [
            event for event in history
            if event.event_type == ApplicationEventType.STATUS_CHANGED
        ]
        assert len(transitions) == successful_updates
        previous = ApplicationStatus.APPLIED
        for event in transitions:
            assert event.previous_status == previous
            assert event.new_status is not None
            previous = event.new_status
        assert saved.status == previous
        user = db.get(User, user_id)
        assert user is not None
        db.delete(user)
        db.commit()


def test_postgres_follow_up_claims_skip_rows_locked_by_another_worker(
    postgres_sessions: sessionmaker[Session],
) -> None:
    now = datetime.now(timezone.utc)
    with postgres_sessions() as db:
        user = _new_user(db)
        application = Application(
            user_id=user.id,
            company="Reminder Lock Co",
            role="Engineer",
            platform="PostgreSQL integration",
            status=ApplicationStatus.APPLIED,
            applied_at=now,
            follow_up_at=now + timedelta(hours=4),
        )
        db.add(application)
        db.commit()
        user_id = user.id
        application_id = application.id

    first_worker = postgres_sessions()
    second_worker = postgres_sessions()
    try:
        window_now = datetime.now(timezone.utc)
        statement = due_reminder_statement(window_now, window_now + timedelta(hours=24))

        first_claim = first_worker.execute(statement).all()
        assert any(row[0].id == application_id for row in first_claim)

        # The first transaction still owns the row lock, so a concurrent worker
        # must skip it rather than sending the same reminder at the same time.
        second_claim = second_worker.execute(statement).all()
        assert not any(row[0].id == application_id for row in second_claim)

        first_worker.commit()
        reclaimed = second_worker.execute(statement).all()
        assert any(row[0].id == application_id for row in reclaimed)
        second_worker.rollback()
    finally:
        first_worker.close()
        second_worker.close()
        with postgres_sessions() as db:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
                db.commit()



def test_postgres_outbox_message_can_be_claimed_by_only_one_worker(
    postgres_sessions: sessionmaker[Session],
) -> None:
    now = datetime.now(timezone.utc)
    with postgres_sessions() as db:
        user = _new_user(db)
        application = Application(
            user_id=user.id,
            company="Outbox Lock Co",
            role="Engineer",
            platform="PostgreSQL integration",
            status=ApplicationStatus.APPLIED,
            applied_at=now - timedelta(days=1),
            follow_up_at=now + timedelta(hours=2),
        )
        db.add(application)
        db.flush()
        outbox = ReminderOutbox(
            application_id=application.id,
            recipient_email=user.email,
            company=application.company,
            role=application.role,
            scheduled_for=application.follow_up_at,
            dedupe_key=uuid.uuid4().hex,
            status="pending",
            attempts=0,
            available_at=now - timedelta(seconds=1),
        )
        db.add(outbox)
        db.commit()
        user_id = user.id
        outbox_id = outbox.id

    barrier = threading.Barrier(2)

    def claim(worker_id: str) -> list[int]:
        with postgres_sessions() as db:
            barrier.wait(timeout=10)
            return claim_pending_outbox(
                db,
                worker_id=worker_id,
                now=now,
                batch_size=1,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ["worker-a", "worker-b"]))

    assert sum(outbox_id in claimed for claimed in claims) == 1

    with postgres_sessions() as db:
        stored = db.get(ReminderOutbox, outbox_id)
        assert stored is not None
        assert stored.status == "processing"
        assert stored.attempts == 1
        user = db.get(User, user_id)
        assert user is not None
        db.delete(user)
        db.commit()
