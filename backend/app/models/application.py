from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.application_event import ApplicationEvent
    from app.models.user import User


class ApplicationStatus(str, Enum):
    APPLIED = "applied"
    REPLIED = "replied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"


def status_enum(constraint_name: str) -> SQLAlchemyEnum:
    return SQLAlchemyEnum(
        ApplicationStatus,
        values_callable=lambda status_values: [
            status.value for status in status_values
        ],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=constraint_name,
    )


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_user_status", "user_id", "status"),
        Index("ix_applications_user_applied_at", "user_id", "applied_at"),
        Index("ix_applications_user_follow_up_at", "user_id", "follow_up_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    follow_up_reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[ApplicationStatus] = mapped_column(
        status_enum("application_status"),
        nullable=False,
        default=ApplicationStatus.APPLIED,
        server_default=ApplicationStatus.APPLIED.value,
    )
    applied_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=func.now(),
    )
    last_update_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ApplicationEvent.created_at",
    )
