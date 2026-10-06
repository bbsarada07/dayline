"""Phase 5 (addendum F): health check, demo clock, reset demo, secure cookies."""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, func, select

from app import clock, demo
from app.config import IST
from app.db import engine
from app.models import MenuItem, Order
from tests.conftest import login


@pytest.fixture(autouse=True)
def fresh_reset_state():
    demo._last_reset = None
    yield
    demo._last_reset = None


def test_health_reports_integrations_without_secrets(client, monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://example.invalid")
    monkeypatch.setenv("QDRANT_API_KEY", "super-secret-qdrant-key")
    monkeypatch.setenv("LYZR_API_KEY", "super-secret-lyzr-key")
    monkeypatch.setenv("LYZR_ORCHESTRATOR_AGENT_ID", "agent-1")
    monkeypatch.delenv("OMI_APP_ID", raising=False)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok" and data["database"] == {"ok": True, "students": 6}
    assert data["qdrant"]["configured"] is True
    assert data["lyzr"]["configured"] is True and data["lyzr"]["agents_configured"] == 1
    assert data["omi"]["configured"] is False
    assert "super-secret" not in response.text


@pytest.mark.parametrize("real_utc,expected", [
    (datetime(2026, 10, 5, 2, 30, tzinfo=timezone.utc), "2026-10-05T12:20"),   # Monday morning
    (datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc), "2026-10-05T12:20"),   # Thursday
    (datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc), "2026-10-05T12:20"),  # Sunday 23:30 IST
    (datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc), "2026-10-12T12:20"),  # Monday 00:30 IST
])
def test_demo_starts_this_weeks_monday_1220(fixed_real_time, real_utc, expected):
    fixed_real_time["now"] = real_utc
    assert demo.demo_start().isoformat().startswith(expected)


def test_reset_demo_restores_data_and_clock(client, fixed_real_time):
    login(client, "student", "22CS001")
    samosa = None
    with Session(engine) as session:
        samosa = session.exec(select(MenuItem.id).where(MenuItem.name == "Samosa")).one()
    clock.set_demo_time(datetime(2026, 10, 5, 12, 20))
    placed = client.post("/api/canteen/orders", json={"items": [{"menu_item_id": samosa, "qty": 1}]})
    assert placed.status_code == 200
    assert len(client.get("/api/canteen/orders/mine").json()["orders"]) >= 1
    clock.set_demo_time(datetime(2026, 10, 5, 15, 45))  # someone moved the clock

    reset = client.post("/api/demo/reset")
    assert reset.status_code == 200 and reset.json()["now"].startswith("2026-10-05T12:20")
    assert client.get("/api/clock").json()["now"].startswith("2026-10-05T12:20")
    # The same login still works after the reset (ids are stable), and today's order is gone.
    assert client.get("/api/auth/me").json()["roll_no"] == "22CS001"
    assert [o for o in client.get("/api/canteen/orders/mine").json()["orders"] if o["status"] == "placed"] == []


def test_reset_is_rate_limited(client):
    assert client.post("/api/demo/reset").status_code == 200
    again = client.post("/api/demo/reset")
    assert again.status_code == 429 and again.json()["error"]["code"] == "reset_too_soon"


def test_reset_refused_outside_demo_mode(client, monkeypatch):
    monkeypatch.setattr(demo, "settings", dataclasses.replace(demo.settings, demo_mode=False))
    response = client.post("/api/demo/reset")
    assert response.status_code == 403 and response.json()["error"]["code"] == "demo_off"


def test_seeded_history_is_before_the_demo_day(client):
    assert client.post("/api/demo/reset").status_code == 200
    start = demo.demo_start()
    day = datetime.combine(start.date(), datetime.min.time(), tzinfo=IST)
    with Session(engine) as session:
        on_demo_day = session.exec(
            select(func.count(Order.id)).where(Order.pickup_time >= day, Order.pickup_time < day + timedelta(days=1))
        ).one()
        history = session.exec(select(func.count(Order.id))).one()
    assert on_demo_day == 0 and history > 500
    login(client, "staff", "canteen")
    label = client.get("/api/canteen/suggested-prep").json()["label"]
    assert label == "Based on the last 4 Mondays"


def test_clock_endpoint_says_demo_mode(client):
    assert client.get("/api/clock").json()["demo_mode"] is True


def test_session_cookie_is_secure_over_https(client, monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, public_base_url="https://dayline.example"))
    response = login(client, "student", "22CS001")
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
