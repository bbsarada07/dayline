import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Point the app at a throwaway database before anything imports it.
_TMP = Path(tempfile.mkdtemp(prefix="dayline-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app import clock  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402
from app.services import settings_service  # noqa: E402

# Monday 5 Oct 2026, 08:00 IST, as real wall-clock time for every test.
REAL_NOW = datetime(2026, 10, 5, 2, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    seed()
    yield


@pytest.fixture(autouse=True)
def fixed_real_time(monkeypatch):
    """Freeze the wall clock; tests move it by reassigning `state['now']`."""
    state = {"now": REAL_NOW}
    monkeypatch.setattr(clock, "_real_utc_now", lambda: state["now"])
    yield state
    settings_service.set_value("clock_override", None)
    settings_service.set_value("attendance_threshold", 75)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client: TestClient, kind: str, username: str, pin: str = "1234"):
    return client.post("/api/auth/login", json={"kind": kind, "username": username, "pin": pin})


@pytest.fixture
def student(client):
    assert login(client, "student", "22CS001").status_code == 200
    return client


@pytest.fixture
def admin(client):
    assert login(client, "staff", "admin").status_code == 200
    return client
