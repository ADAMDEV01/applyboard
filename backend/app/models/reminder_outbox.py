from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReminderOutbox(Base):
    """Durable per-application email work item with lease and retry metadata."""

    __tablename__ = "reminder_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed', 'cancelled')",
            name="reminder_outbox_status",
        ),
        CheckConstraint("attempts >= 0", name="reminder_outbox_attempts_nonnegative"),
        UniqueConstraint("dedupe_key", name="uq_reminder_outbox_dedupe_key"),
        Index("ix_reminder_outbox_due", "status", "available_at", "created_at"),
        Index("ix_reminder_outbox_application", "application_id", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(200), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lock_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow, nullable=False)
