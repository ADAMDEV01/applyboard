"""Add persistent PostgreSQL-backed API rate limits.

Revision ID: 0006_postgres_rate_limits
Revises: 0005_reminder_outbox
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_postgres_rate_limits"
down_revision: Union[str, None] = "0005_reminder_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        sa.Column("bucket_key", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.Float(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "hit_count >= 1",
            name=op.f("ck_rate_limit_buckets_hit_count_positive"),
        ),
        sa.PrimaryKeyConstraint("bucket_key", name=op.f("pk_rate_limit_buckets")),
    )
    op.create_index(
        "ix_rate_limit_buckets_updated_at",
        "rate_limit_buckets",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_buckets_updated_at", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
