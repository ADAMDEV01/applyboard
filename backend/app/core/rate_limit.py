from __future__ import annotations

from hashlib import sha256
from math import ceil
from time import time
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.rate_limit_bucket import RateLimitBucket

_RATE_LIMIT_RETENTION_SECONDS = 7 * 24 * 60 * 60


def rate_limit(scope: str, *, limit: int, window_seconds: int) -> Callable:
    """Return a shared, atomic PostgreSQL/SQLite rate-limit dependency.

    Only a one-way hash of the route scope and remote address is stored. The
    upsert is performed by the database, so concurrent instances share one
    counter and cannot race through a read-then-write check.
    """
    if not scope or limit < 1 or window_seconds < 1:
        raise ValueError("A scope, positive limit, and positive window are required.")

    def enforce_rate_limit(
        request: Request,
        db: Session = Depends(get_db),
    ) -> None:
        remote_address = request.client.host if request.client else "unknown"
        bucket_key = sha256(f"{scope}:{remote_address}".encode("utf-8")).hexdigest()
        now = time()
        window_floor = now - window_seconds

        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            insert = postgresql_insert
        elif dialect == "sqlite":
            insert = sqlite_insert
        else:
            raise RuntimeError("Rate limiting requires PostgreSQL or SQLite.")

        statement = insert(RateLimitBucket).values(
            bucket_key=bucket_key,
            window_started_at=now,
            hit_count=1,
            updated_at=now,
        )
        expired = RateLimitBucket.window_started_at <= window_floor
        statement = statement.on_conflict_do_update(
            index_elements=[RateLimitBucket.bucket_key],
            set_={
                "window_started_at": case(
                    (expired, now),
                    else_=RateLimitBucket.window_started_at,
                ),
                "hit_count": case(
                    (expired, 1),
                    else_=RateLimitBucket.hit_count + 1,
                ),
                "updated_at": now,
            },
        ).returning(
            RateLimitBucket.hit_count,
            RateLimitBucket.window_started_at,
        )

        try:
            bucket = db.execute(statement).one()
            db.commit()
        except Exception:
            db.rollback()
            raise

        if bucket.hit_count == 1:
            # Keep hashed client identifiers only for a bounded period.
            db.execute(
                delete(RateLimitBucket).where(
                    RateLimitBucket.updated_at < now - _RATE_LIMIT_RETENTION_SECONDS
                )
            )
            db.commit()

        if bucket.hit_count > limit:
            retry_after = max(
                1,
                ceil(window_seconds - (now - bucket.window_started_at)),
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    return enforce_rate_limit
