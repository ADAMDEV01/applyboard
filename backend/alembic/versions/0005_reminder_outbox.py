"""Add durable reminder email outbox.

Revision ID: 0005_reminder_outbox
Revises: 0004_refresh_sessions
Create Date: 2026-11-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_reminder_outbox"
down_revision: Union[str, None] = "0004_refresh_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reminder_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=200), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_owner", sa.String(length=64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed', 'cancelled')",
            name="ck_reminder_outbox_reminder_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_reminder_outbox_reminder_outbox_attempts_nonnegative"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_reminder_outbox_dedupe_key"),
    )
    op.create_index(
        "ix_reminder_outbox_due",
        "reminder_outbox",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_reminder_outbox_application",
        "reminder_outbox",
        ["application_id", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_reminder_outbox_application", table_name="reminder_outbox")
    op.drop_index("ix_reminder_outbox_due", table_name="reminder_outbox")
    op.drop_table("reminder_outbox")
