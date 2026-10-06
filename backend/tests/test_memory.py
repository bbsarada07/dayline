"""Phase 6: shared agent memory (addendum G), on an in-process Qdrant with the offline embedder."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlmodel import Session, select

from app.agents import mock_router
from app.db import engine
from app.errors import ApiError
from app.main import app
from app.models import MenuItem
from app.services import memory_service
from app.services.memory_backends import QdrantBackend, TemporaryBackend
from tests.conftest import login

ANANYA, PRIYA = 1, 2


def as_user(kind: str, username: str) -> TestClient:
    client = TestClient(app)
    assert login(client, kind, username).status_code == 200
    return client


def item_id(name: str) -> int:
    with Session(engine) as session:
        return session.exec(select(MenuItem.id).where(MenuItem.name == name)).one()


def texts(memories) -> list[str]:
    return [m.text if hasattr(m, "text") else m["text"] for m in memories]


@pytest.fixture(autouse=True)
def clean_memory():
    memory_service.configure(QdrantBackend.local())
    memory_service.backend().ensure()
    yield
    memory_service.drain()
    memory_service.configure(QdrantBackend.local())
    memory_service.backend().ensure()


@pytest.fixture
def ananya():
    return as_user("student", "22CS001")


@pytest.fixture
def priya():
    return as_user("student", "22CS002")


def remember(student_id: int, text: str, **kw):
    kw.setdefault("kind", "fact")
    kw.setdefault("written_by", "student")
    return memory_service.remember(student_id, text, **kw)


# --- isolation: student A can never reach student B's memories ------------------------

def test_isolation_every_operation():
    mine = remember(ANANYA, "My lab record is due Thursday")
    secret = remember(PRIYA, "Priya's secret: lab record due Thursday, prefers paneer")

    # Search with words that match B's memory best still only returns A's.
    assert texts(memory_service.recall(ANANYA, "Priya secret paneer lab record Thursday")) == [mine.text]
    assert texts(memory_service.list_memories(ANANYA)) == [mine.text]

    # A deleting B's memory by its id does nothing (404), and B's memory is still there.
    with pytest.raises(ApiError) as missing:
        memory_service.forget(ANANYA, secret.id)
    assert missing.value.status == 404
    assert texts(memory_service.list_memories(PRIYA)) == [secret.text]

    # Delete-all only touches A; recall by A never marks B's memory as used.
    assert memory_service.forget_all(ANANYA) == 1
    priya_rows = memory_service.list_memories(PRIYA)
    assert texts(priya_rows) == [secret.text] and priya_rows[0].last_used_at is None


def test_isolation_through_the_api(ananya, priya):
    note = ananya.post("/api/memory/notes", json={"text": "Remember that my locker code is 4412"}).json()
    assert texts(priya.get("/api/memory").json()["memories"]) == []
    assert texts(priya.get("/api/memory", params={"q": "locker code"}).json()["memories"]) == []
    assert priya.delete(f"/api/memory/{note['id']}").status_code == 404
    assert priya.delete("/api/memory").json() == {"deleted": 0}
    assert texts(ananya.get("/api/memory").json()["memories"]) == ["My locker code is 4412"]


def test_memory_routes_are_student_only():
    staff = as_user("staff", "canteen")
    assert staff.get("/api/memory").status_code == 403
    assert TestClient(app).get("/api/memory").status_code == 401


# --- writes after orders and print jobs ----------------------------------------------

def test_order_and_print_job_write_memories(ananya):
    admin = as_user("staff", "admin")
    admin.put("/api/admin/demo-time", json={"local": "2026-10-05T12:20"})  # a Monday
    body = {"items": [{"menu_item_id": item_id("Veg fried rice"), "qty": 1}, {"menu_item_id": item_id("Masala chai"), "qty": 1}]}
    order = ananya.post("/api/canteen/orders", json=body).json()

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    pdf = io.BytesIO()
    writer.write(pdf)
    up = ananya.post("/api/print/uploads", files={"file": ("lab_record.pdf", pdf.getvalue(), "application/pdf")}).json()
    ananya.post("/api/print/jobs", json={"upload_id": up["upload_id"], "copies": 2, "double_sided": True})
    memory_service.drain()

    rows = ananya.get("/api/memory").json()["memories"]
    assert [r["written_by"] for r in rows] == ["print", "canteen"]  # newest first
    assert rows[0]["text"] == "Printed lab_record.pdf: 2 copies, black and white, double sided"
    assert rows[1]["text"] == "Ordered Veg fried rice × 1, Masala chai × 1 for 12:40 pickup on a Monday"
    assert rows[1]["source_ref"] == f"order:{order['id']}" and rows[1]["data"]["weekday"] == 0
    assert all(r["kind"] == "action" for r in rows)


def test_memory_write_failure_never_blocks_the_order(ananya):
    class Broken(TemporaryBackend):
        name = "temporary"

        def upsert(self, *args, **kwargs):
            raise RuntimeError("store down")

    memory_service.configure(Broken(), reason="test")
    admin = as_user("staff", "admin")
    admin.put("/api/admin/demo-time", json={"local": "2026-10-05T12:20"})
    r = ananya.post("/api/canteen/orders", json={"items": [{"menu_item_id": item_id("Samosa"), "qty": 1}]})
    memory_service.drain()
    assert r.status_code == 200


# --- "remember that ..." through the mock router -------------------------------------------

@pytest.mark.parametrize("said,fact,kind", [
    ("Remember that my lab record is due Thursday.", "My lab record is due Thursday", "fact"),
    ("hey dayline, remember I prefer veg fried rice", "I prefer veg fried rice", "preference"),
    ("Don't forget: the DBMS viva moved to Friday", "The DBMS viva moved to Friday", "fact"),
    ("note down that I'm allergic to peanuts", "I'm allergic to peanuts", "preference"),
])
def test_mock_router_remember(said, fact, kind):
    intent = mock_router.route(said)
    assert intent is not None and intent.name == "remember"
    assert intent.slots == {"fact": fact, "kind": kind}


@pytest.mark.parametrize("said", ["what's my attendance?", "remember", "print this", ""])
def test_mock_router_ignores_other_messages(said):
    assert mock_router.route(said) is None


def test_remember_that_through_the_api(ananya):
    saved = ananya.post("/api/memory/notes", json={"text": "Remember that my lab record is due Thursday"})
    assert saved.status_code == 200
    assert saved.json()["written_by"] == "student" and saved.json()["kind"] == "fact"
    refused = ananya.post("/api/memory/notes", json={"text": "my lab record is due Thursday"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "not_a_memory"


# --- search, list, delete ----------------------------------------------------------------

def test_search_finds_by_meaning_and_marks_used(ananya):
    ananya.post("/api/memory/notes", json={"text": "Remember that my lab record is due Thursday"})
    ananya.post("/api/memory/notes", json={"text": "Remember that I like masala dosa for breakfast"})
    found = ananya.get("/api/memory", params={"q": "when is the lab record due"}).json()["memories"]
    assert found[0]["text"] == "My lab record is due Thursday" and found[0]["score"] is not None
    listed = {m["text"]: m for m in ananya.get("/api/memory").json()["memories"]}
    assert listed["My lab record is due Thursday"]["last_used_at"] is not None
    assert listed["I like masala dosa for breakfast"]["last_used_at"] is None  # only the best match counts as used


def test_list_is_newest_first_and_delete_works(ananya):
    for word in ("first", "second", "third"):
        ananya.post("/api/memory/notes", json={"text": f"Remember that this is the {word} note"})
    rows = ananya.get("/api/memory").json()["memories"]
    assert texts(rows) == ["This is the third note", "This is the second note", "This is the first note"]
    assert ananya.delete(f"/api/memory/{rows[1]['id']}").json() == {"deleted": 1}
    assert ananya.delete("/api/memory/not-a-uuid").status_code == 404
    assert ananya.delete("/api/memory").json() == {"deleted": 2}
    assert ananya.get("/api/memory").json()["memories"] == []


def test_kind_and_writer_are_validated():
    with pytest.raises(ApiError):
        memory_service.remember(ANANYA, "x", kind="gossip", written_by="student")
    with pytest.raises(ApiError):
        memory_service.remember(ANANYA, "x", kind="fact", written_by="someone")
    with pytest.raises(ApiError):
        memory_service.remember(ANANYA, "   ", kind="fact", written_by="student")
    assert len(memory_service.remember(ANANYA, "y" * 900, kind="fact", written_by="student").text) == 500


# --- behaviour that depends on memory ----------------------------------------------------

def _order_memory(student_id: int, weekday: int, items: list[tuple[int, str, int]], pickup: str = "12:40"):
    memory_service.remember(
        student_id, f"Ordered {items} on day {weekday}", kind="action", written_by="canteen",
        data={"weekday": weekday, "pickup": pickup, "items": [{"menu_item_id": i, "name": n, "qty": q} for i, n, q in items]},
    )


def test_usual_order_comes_from_memory_and_changes_with_it():
    rice = [(4, "Veg fried rice", 1), (11, "Masala chai", 1)]
    biryani = [(6, "Chicken biryani", 1)]
    assert memory_service.usual_order(ANANYA, 0) is None
    _order_memory(ANANYA, 0, rice)
    _order_memory(ANANYA, 0, rice, pickup="12:45")
    _order_memory(ANANYA, 0, biryani)
    _order_memory(ANANYA, 2, biryani)  # a Wednesday: not a Monday usual
    _order_memory(PRIYA, 0, biryani)  # someone else's
    usual = memory_service.usual_order(ANANYA, 0)
    assert [i["name"] for i in usual["items"]] == ["Veg fried rice", "Masala chai"] and usual["times"] == 2
    for _ in range(2):
        _order_memory(ANANYA, 0, biryani)
    assert [i["name"] for i in memory_service.usual_order(ANANYA, 0)["items"]] == ["Chicken biryani"]
    used = [m for m in memory_service.list_memories(ANANYA) if m.last_used_at]
    assert used and all(m.written_by == "canteen" for m in used)


def test_print_like_last_time_uses_the_newest_print_memory():
    assert memory_service.last_print_settings(ANANYA) is None
    for copies, color in ((1, False), (3, True)):
        memory_service.remember(ANANYA, f"Printed x: {copies}", kind="action", written_by="print",
                                data={"copies": copies, "color": color, "double_sided": True})
    settings = memory_service.last_print_settings(ANANYA)
    assert (settings["copies"], settings["color"], settings["double_sided"]) == (3, True, True)
    assert memory_service.last_print_settings(PRIYA) is None


# --- fallback, reset, realtime ---------------------------------------------------------------

def test_temporary_store_works_and_says_so(ananya):
    memory_service.configure(TemporaryBackend(), reason="Qdrant can't be reached right now.")
    ananya.post("/api/memory/notes", json={"text": "Remember that I sit in the front row"})
    data = ananya.get("/api/memory").json()
    assert data["status"]["backend"] == "temporary" and "until the server restarts" in data["status"]["notice"]
    assert texts(data["memories"]) == ["I sit in the front row"]
    assert texts(ananya.get("/api/memory", params={"q": "front row"}).json()["memories"]) == ["I sit in the front row"]


def test_qdrant_failure_mid_run_falls_back(ananya):
    class Flaky(QdrantBackend):
        def scroll(self, *args, **kwargs):
            raise ConnectionError("network down")

    memory_service.configure(Flaky.local())
    data = ananya.get("/api/memory").json()
    assert data["status"]["backend"] == "temporary" and data["memories"] == []


def test_reset_demo_clears_memories(ananya):
    from app import demo

    demo._last_reset = None
    ananya.post("/api/memory/notes", json={"text": "Remember that I take the 8:10 bus"})
    assert ananya.post("/api/demo/reset").status_code == 200
    demo._last_reset = None
    texts_after = texts(ananya.get("/api/memory").json()["memories"])
    # The note is gone; only the seeded demo history is back (Phase 7: her usual lunch, last print, a deadline).
    assert "I take the 8:10 bus" not in texts_after
    assert texts_after == [
        "My DBMS lab record is due Thursday",
        "Printed DBMS_lab_record.pdf: 2 copies, black and white, double sided",
        *["Ordered Veg fried rice × 1, Masala chai × 1 for 12:40 pm pickup on a Monday"] * 3,
    ]


def test_memory_events_reach_only_the_owner(client):
    from app.events import hub

    login(client, "student", "22CS002")  # Priya listens
    with client.websocket_connect("/ws") as priya_ws:
        ananya = as_user("student", "22CS001")
        with ananya.websocket_connect("/ws") as ananya_ws:
            ananya.post("/api/memory/notes", json={"text": "Remember that my bus is at 8:10"})
            assert ananya_ws.receive_json()["type"] == "memory.updated"
            hub.publish("settings.updated", {"keys": []})
            assert priya_ws.receive_json()["type"] == "settings.updated"
