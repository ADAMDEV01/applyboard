from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core import security
from app.db.base import Base
from app.db.database import create_database_engine, get_db
from app.main import app


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "test.db"
    engine = create_database_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        with test_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(security, "JWT_SECRET", "test-secret-" + "x" * 32)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()
