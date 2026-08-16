import os
import tempfile
from pathlib import Path

test_database_path = Path(tempfile.gettempdir()) / "cockpit-test.sqlite3"

os.environ.update(
    COCKPIT_DATABASE_URL=f"sqlite+pysqlite:///{test_database_path.as_posix()}",
    COCKPIT_SECRET_KEY="test-secret-key-that-is-at-least-thirty-two-characters",
    COCKPIT_ENV="development",
    COCKPIT_ALLOWED_HOSTS="testserver,localhost",
    COCKPIT_COOKIE_SECURE="false",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import attempts  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    attempts.clear()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
