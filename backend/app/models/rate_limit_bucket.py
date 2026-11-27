from sqlalchemy import CheckConstraint, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RateLimitBucket(Base):
    """A hashed remote-client window used by the shared API rate limiter."""

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("hit_count >= 1", name="hit_count_positive"),
        Index("ix_rate_limit_buckets_updated_at", "updated_at"),
    )

    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[float] = mapped_column(Float, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
