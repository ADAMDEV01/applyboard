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

from app.models import Application, ApplicationStatus, RefreshSession, User


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
