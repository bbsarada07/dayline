"""Collect by barcode (addendum E): every status, the repeat guard, the simulator and permissions."""

import io
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlmodel import Session, delete, select

from app.db import engine
from app.main import app
from app.models import MenuItem, Order, OrderItem, PrintJob, PrintUpload, TapLog
from app.services import collect_service, settings_service
from tests.conftest import login


def as_user(kind: str, username: str) -> TestClient:
    client = TestClient(app)
    assert login(client, kind, username).status_code == 200
    return client


def set_demo(local: str) -> None:
    assert as_user("staff", "admin").put("/api/admin/demo-time", json={"local": local}).status_code == 200


def item_id(name: str) -> int:
    with Session(engine) as session:
        return session.exec(select(MenuItem.id).where(MenuItem.name == name)).one()


def order(client: TestClient, *pairs, pickup: str | None = None) -> dict:
    body = {"items": [{"menu_item_id": item_id(n), "qty": q} for n, q in pairs]}
    if pickup:
        body["pickup_time"] = pickup
    response = client.post("/api/canteen/orders", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def advance_order(kitchen: TestClient, order_id: int, *steps: str) -> None:
    for step in steps:
        assert kitchen.post(f"/api/canteen/orders/{order_id}/status", json={"status": step}).status_code == 200


def print_job(client: TestClient, pages: int = 3, name: str = "notes.pdf") -> dict:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    up = client.post("/api/print/uploads", files={"file": (name, buffer.getvalue(), "application/pdf")}).json()
    response = client.post("/api/print/jobs", json={"upload_id": up["upload_id"], "copies": 1})
    assert response.status_code == 200, response.text
    return response.json()


def advance_job(shop: TestClient, job_id: int, *steps: str) -> None:
    for step in steps:
        assert shop.post(f"/api/print/jobs/{job_id}/status", json={"status": step}).status_code == 200


@pytest.fixture(autouse=True)
def clean_desk():
    with Session(engine) as session:
        for path in session.exec(select(PrintJob.stored_path)).all() + session.exec(select(PrintUpload.stored_path)).all():
            if path:
                Path(path).unlink(missing_ok=True)
        for table in (TapLog, OrderItem, Order, PrintJob, PrintUpload):
            session.exec(delete(table))
        session.commit()
    collect_service._recent.clear()
    settings_service.set_value("demo_mode", True)
    set_demo("2026-10-05T12:20")
    yield
    collect_service._recent.clear()
    settings_service.set_value("demo_mode", True)


@pytest.fixture
def ananya():
    return as_user("student", "22CS001")


@pytest.fixture
def priya():
    return as_user("student", "22CS002")


@pytest.fixture
def kitchen():
    return as_user("staff", "canteen")


@pytest.fixture
def shop():
    return as_user("staff", "print")


def scan(desk: TestClient, code: str) -> dict:
    response = desk.post("/api/collect/scan", json={"code": code})
    assert response.status_code == 200, response.text
    return response.json()


def taplog() -> list[tuple[str, str, int | None, str]]:
    with Session(engine) as session:
        return [(t.reader_id, t.card_uid, t.student_id, t.result) for t in session.exec(select(TapLog).order_by(TapLog.id))]


# --- canteen counter ------------------------------------------------------------

def test_unknown_card(kitchen):
    result = scan(kitchen, "NOT-A-STUDENT")
    assert result["status"] == "unknown_card" and result["name"] is None
    assert taplog() == [("canteen-1", "NOT-A-STUDENT", None, "unknown_card")]


def test_ready_order_is_collected(ananya, kitchen):
    placed = order(ananya, ("Veg fried rice", 2))
    advance_order(kitchen, placed["id"], "preparing", "ready")
    result = scan(kitchen, " 22cs001\r")  # scanners may add whitespace; case doesn't matter
    assert result["status"] == "collected" and result["name"] == "Ananya Rao"
    assert result["summary"] == f"Token {placed['token_no']}: Veg fried rice × 2"
    mine = ananya.get("/api/canteen/orders/mine").json()["orders"][0]
    assert mine["status"] == "collected" and mine["collected_at"]
    assert taplog()[-1][1:] == ("22CS001", 1, "collected")


def test_all_ready_orders_collected_at_once_and_others_untouched(ananya, kitchen):
    first = order(ananya, ("Samosa", 1))
    second = order(ananya, ("Masala chai", 2))
    third = order(ananya, ("Veg thali", 1), pickup="2026-10-05T13:15")
    advance_order(kitchen, first["id"], "preparing", "ready")
    advance_order(kitchen, second["id"], "preparing", "ready")
    result = scan(kitchen, "22CS001")
    assert result["status"] == "collected"
    assert result["lines"] == [f"Token {first['token_no']}: Samosa × 1", f"Token {second['token_no']}: Masala chai × 2"]
    statuses = {o["id"]: o["status"] for o in ananya.get("/api/canteen/orders/mine").json()["orders"]}
    assert statuses == {first["id"]: "collected", second["id"]: "collected", third["id"]: "placed"}


def test_not_ready(ananya, kitchen):
    placed = order(ananya, ("Samosa", 1))
    cooking = order(ananya, ("Curd rice", 1))
    advance_order(kitchen, cooking["id"], "preparing")
    result = scan(kitchen, "22CS001")
    assert result["status"] == "not_ready"
    assert result["lines"] == [
        f"Token {placed['token_no']} is in the kitchen queue",
        f"Token {cooking['token_no']} is being prepared",
    ]


def test_nothing_to_collect(kitchen):
    result = scan(kitchen, "22CS002")
    assert result["status"] == "nothing_to_collect" and result["name"] == "Priya Nair" and result["summary"] is None


def test_counter_only_hands_over_its_own_station(ananya, shop, kitchen):
    job = print_job(ananya)
    advance_job(shop, job["id"], "printing", "ready")
    assert scan(kitchen, "22CS001")["status"] == "nothing_to_collect"  # a printout isn't food
    assert ananya.get("/api/print/jobs/mine").json()["jobs"][0]["status"] == "ready"


def test_only_todays_orders_are_collected(ananya, kitchen):
    placed = order(ananya, ("Samosa", 1))
    advance_order(kitchen, placed["id"], "preparing", "ready")
    set_demo("2026-10-06T09:00")  # next day; yesterday's ready order isn't handed over today
    assert scan(kitchen, "22CS001")["status"] == "nothing_to_collect"


# --- print desk ------------------------------------------------------------------------

def test_ready_printout_is_collected_and_file_deleted(ananya, shop):
    job = print_job(ananya, pages=3, name="Lab record.pdf")
    with Session(engine) as session:
        stored = session.get(PrintJob, job["id"]).stored_path
    advance_job(shop, job["id"], "printing", "ready")
    result = scan(shop, "22CS001")
    assert result["status"] == "collected"
    assert result["summary"] == f"{job['code']}: Lab record.pdf (3 pages × 1)"
    assert not Path(stored).exists()
    mine = ananya.get("/api/print/jobs/mine").json()["jobs"][0]
    assert mine["status"] == "collected" and mine["has_file"] is False
    assert taplog()[-1] == ("print-1", "22CS001", 1, "collected")


def test_printout_not_ready(ananya, shop):
    queued = print_job(ananya)
    result = scan(shop, "22CS001")
    assert result["status"] == "not_ready" and result["lines"] == [f"{queued['code']} is in the print queue"]
    advance_job(shop, queued["id"], "printing")
    collect_service._recent.clear()
    assert scan(shop, "22CS001")["lines"] == [f"{queued['code']} is printing"]


# --- repeat guard ------------------------------------------------------------------

def test_repeat_scan_within_three_seconds_is_ignored(ananya, kitchen, fixed_real_time):
    placed = order(ananya, ("Samosa", 1))
    advance_order(kitchen, placed["id"], "preparing", "ready")
    assert scan(kitchen, "22CS001")["status"] == "collected"
    fixed_real_time["now"] += timedelta(seconds=2)
    assert scan(kitchen, "22CS001")["status"] == "ignored"
    fixed_real_time["now"] += timedelta(seconds=2)  # 4 s after the first scan
    assert scan(kitchen, "22CS001")["status"] == "nothing_to_collect"
    assert [row[3] for row in taplog()] == ["collected", "ignored", "nothing_to_collect"]


def test_repeat_guard_is_per_reader(kitchen, shop):
    assert scan(kitchen, "22CS003")["status"] == "nothing_to_collect"
    assert scan(shop, "22CS003")["status"] == "nothing_to_collect"  # a different desk, not a repeat


def test_repeat_guard_ignores_demo_time_jumps(kitchen, fixed_real_time):
    assert scan(kitchen, "22CS004")["status"] == "nothing_to_collect"
    set_demo("2026-10-05T15:00")  # demo clock jumps ahead; wall clock hasn't moved
    assert scan(kitchen, "22CS004")["status"] == "ignored"


# --- simulator, input, permissions, realtime -----------------------------------------

def test_simulate_uses_the_same_path(ananya, kitchen):
    placed = order(ananya, ("Samosa", 1))
    advance_order(kitchen, placed["id"], "preparing", "ready")
    students = kitchen.get("/api/collect/candidates").json()
    assert students["demo_mode"] is True
    assert students["students"][0]["name"] == "Ananya Rao" and students["students"][0]["ready"] == 1
    result = kitchen.post("/api/collect/simulate", json={"student_id": students["students"][0]["id"]}).json()
    assert result["status"] == "collected" and result["summary"] == f"Token {placed['token_no']}: Samosa × 1"
    assert taplog()[-1][3] == "collected"


def test_simulate_only_in_demo_mode(kitchen):
    settings_service.set_value("demo_mode", False)
    r = kitchen.post("/api/collect/simulate", json={"student_id": 1})
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_off"
    assert kitchen.get("/api/collect/candidates").json() == {"demo_mode": False, "students": []}
    assert scan(kitchen, "22CS001")["status"] == "nothing_to_collect"  # real scans still work


def test_simulate_unknown_student(kitchen):
    assert kitchen.post("/api/collect/simulate", json={"student_id": 9999}).status_code == 404


@pytest.mark.parametrize("code,error", [("\r\n", "empty_code"), ("   ", "empty_code"), ("X" * 65, "bad_code")])
def test_bad_scans_get_a_plain_error(kitchen, code, error):
    r = kitchen.post("/api/collect/scan", json={"code": code})
    assert r.status_code == 422 and r.json()["error"]["code"] == error


def test_only_desk_staff_can_scan(ananya):
    assert ananya.post("/api/collect/scan", json={"code": "22CS001"}).status_code == 403
    admin = as_user("staff", "admin")
    assert admin.post("/api/collect/scan", json={"code": "22CS001"}).status_code == 403
    assert admin.post("/api/collect/simulate", json={"student_id": 1}).status_code == 403
    assert TestClient(app).post("/api/collect/scan", json={"code": "22CS001"}).status_code == 401


def test_result_is_broadcast_to_that_desk_only(client):
    from app.events import hub

    login(client, "staff", "print")
    with client.websocket_connect("/ws") as print_ws:
        kitchen = as_user("staff", "canteen")
        with kitchen.websocket_connect("/ws") as kitchen_ws:
            scan(kitchen, "22CS005")
            hub.publish("settings.updated", {"keys": []})
            event = kitchen_ws.receive_json()
            assert event["type"] == "tap.result"
            assert event["payload"]["status"] == "nothing_to_collect" and event["payload"]["name"] == "Sneha Patil"
            assert print_ws.receive_json()["type"] == "settings.updated"  # the print desk never saw it
