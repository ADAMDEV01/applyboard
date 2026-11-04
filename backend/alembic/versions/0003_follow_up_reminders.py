"""Track follow-up reminder delivery.

Revision ID: 0003_follow_up_reminders
Revises: 0002_followups_and_event_types
Create Date: 2026-11-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_follow_up_reminders"
down_revision: Union[str, None] = "0002_followups_and_event_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(
            sa.Column("follow_up_reminder_sent_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("follow_up_reminder_sent_at")
