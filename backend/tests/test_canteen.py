import threading
from collections import Counter
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.config import IST
from app.db import engine
from app.errors import ApiError
from app.main import app
from app.models import MenuItem, Order, OrderItem, Student
from app.seed import MENU
from app.services import canteen_service, maintenance
from tests.conftest import login


def as_user(kind: str, username: str) -> TestClient:
    client = TestClient(app)
    assert login(client, kind, username).status_code == 200
    return client


def set_demo(local: str) -> None:
    admin = as_user("staff", "admin")
    assert admin.put("/api/admin/demo-time", json={"local": local}).status_code == 200


def item_id(name: str) -> int:
    with Session(engine) as session:
        return session.exec(select(MenuItem.id).where(MenuItem.name == name)).one()


def stock(name: str) -> int:
    with Session(engine) as session:
        return session.exec(select(MenuItem.stock_today).where(MenuItem.name == name)).one()


def cart(*pairs, pickup: str | None = None) -> dict:
    body = {"items": [{"menu_item_id": item_id(n), "qty": q} for n, q in pairs]}
    if pickup:
        body["pickup_time"] = pickup
    return body


@pytest.fixture(autouse=True)
def fresh_canteen():
    """No orders, seeded stock and availability, Monday 12:20 (TOC on, lunch at 12:40)."""
    with Session(engine) as session:
        session.exec(delete(OrderItem))
        session.exec(delete(Order))
        for name, _c, price, _v, _m, stock_today, _w in MENU:
            item = session.exec(select(MenuItem).where(MenuItem.name == name)).one()
            item.stock_today, item.is_available, item.price = stock_today, True, price
            session.add(item)
        session.commit()
    set_demo("2026-10-05T12:20")
    yield


@pytest.fixture
def ananya():
    return as_user("student", "22CS001")


@pytest.fixture
def priya():
    return as_user("student", "22CS002")


@pytest.fixture
def kitchen():
    return as_user("staff", "canteen")


# --- menu and quotes ------------------------------------------------------------

def test_menu_shows_what_can_be_ordered(ananya, kitchen):
    kitchen.patch(f"/api/canteen/menu/{item_id('Poha')}", json={"is_available": False})
    kitchen.patch(f"/api/canteen/menu/{item_id('Egg puff')}", json={"stock_today": 0})
    items = {i["name"]: i for i in ananya.get("/api/canteen/menu").json()["items"]}
    assert len(items) == 12
    assert items["Poha"]["can_order"] is False and items["Egg puff"]["can_order"] is False
    assert items["Samosa"]["can_order"] is True and items["Chicken biryani"]["is_veg"] is False


def test_quote_total_and_default_pickup_is_lunch_break(ananya):
    q = ananya.post("/api/canteen/quote", json=cart(("Veg fried rice", 2), ("Masala chai", 1))).json()
    assert q["total"] == 2 * 6000 + 1200
    assert q["pickup_time"].startswith("2026-10-05T12:40")  # food ready by 12:30; lunch starts 12:40
    assert q["pickup_reason"] == "Your lunch break starts at 12:40."
    assert q["earliest_pickup"].startswith("2026-10-05T12:30")
    assert q["pickup_slots"][0].startswith("2026-10-05T12:30") and q["pickup_slots"][-1].startswith("2026-10-05T16:30")


def test_default_pickup_when_no_breaks_left_is_earliest(ananya):
    set_demo("2026-10-05T15:00")  # in the lab until 16:00, no more breaks
    q = ananya.post("/api/canteen/quote", json=cart(("Veg fried rice", 1))).json()
    assert q["pickup_time"].startswith("2026-10-05T15:10")
    assert q["pickup_reason"] == "That's the earliest your food can be ready."


def test_canteen_closed(ananya):
    set_demo("2026-10-05T16:25")
    response = ananya.post("/api/canteen/quote", json=cart(("Veg fried rice", 1)))
    assert response.status_code == 409 and response.json()["error"]["code"] == "canteen_closed"


@pytest.mark.parametrize("pickup,code", [
    ("2026-10-05T12:42", "bad_pickup_step"),
    ("2026-10-05T12:25", "pickup_too_soon"),
    ("2026-10-05T16:45", "pickup_outside_hours"),
])
def test_pickup_validation(ananya, pickup, code):
    response = ananya.post("/api/canteen/quote", json=cart(("Veg fried rice", 1), pickup=pickup))
    assert response.status_code == 422 and response.json()["error"]["code"] == code


def test_custom_pickup_accepted(ananya):
    q = ananya.post("/api/canteen/quote", json=cart(("Samosa", 1), pickup="2026-10-05T13:05")).json()
    assert q["pickup_time"].startswith("2026-10-05T13:05") and q["pickup_is_default"] is False


def test_unavailable_and_out_of_stock_rejected(ananya, kitchen):
    kitchen.patch(f"/api/canteen/menu/{item_id('Poha')}", json={"is_available": False})
    r = ananya.post("/api/canteen/orders", json=cart(("Poha", 1)))
    assert r.status_code == 409 and r.json()["error"]["code"] == "item_unavailable"
    kitchen.patch(f"/api/canteen/menu/{item_id('Egg puff')}", json={"stock_today": 2})
    r = ananya.post("/api/canteen/orders", json=cart(("Egg puff", 3)))
    assert r.status_code == 409 and r.json()["error"]["code"] == "out_of_stock"
    assert stock("Egg puff") == 2


# --- placing, tokens, stock ---------------------------------------------------------

def test_place_order_tokens_stock_and_today(ananya, priya, kitchen):
    before = stock("Veg fried rice")
    first = ananya.post("/api/canteen/orders", json=cart(("Veg fried rice", 2)))
    assert first.status_code == 200, first.text
    second = priya.post("/api/canteen/orders", json=cart(("Veg fried rice", 1), ("Masala chai", 1))).json()
    first = first.json()
    assert (first["token_no"], second["token_no"]) == (1, 2)
    assert first["status"] == "placed" and first["payment_status"] == "paid_demo"
    assert first["items"] == [{"menu_item_id": item_id("Veg fried rice"), "name": "Veg fried rice", "qty": 2,
                               "unit_price": 6000, "is_veg": True}]
    assert stock("Veg fried rice") == before - 3
    assert [o["token_no"] for o in ananya.get("/api/today").json()["orders"]] == [1]
    assert [t["token_no"] for t in kitchen.get("/api/canteen/board").json()["placed"]] == [1, 2]


def test_token_numbers_reset_daily(ananya):
    assert ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()["token_no"] == 1
    assert ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()["token_no"] == 2
    set_demo("2026-10-06T10:00")
    assert ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()["token_no"] == 1


def _place_concurrently(names: list[str], dish: str, workers: int) -> list:
    """Many students order the same dish at the same instant, each on their own DB session."""
    with Session(engine) as session:
        students = {s.roll_no: s for s in session.exec(select(Student)).all()}
    barrier = threading.Barrier(workers)
    results: list = [None] * workers

    def run(index: int) -> None:
        student = students[names[index % len(names)]]
        barrier.wait()
        with Session(engine) as session:
            try:
                results[index] = canteen_service.place_order(
                    session, student, [canteen_service.CartLine(item_id(dish), 1)]
                ).token_no
            except ApiError as exc:
                results[index] = exc.code

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_stock_never_goes_negative_under_simultaneous_orders(kitchen):
    kitchen.patch(f"/api/canteen/menu/{item_id('Chicken biryani')}", json={"stock_today": 1})
    results = _place_concurrently(["22CS001", "22CS002"], "Chicken biryani", workers=8)
    assert Counter(type(r) for r in results)[int] == 1
    assert all(r == "out_of_stock" for r in results if not isinstance(r, int))
    assert stock("Chicken biryani") == 0


def test_simultaneous_orders_get_unique_tokens(kitchen):
    kitchen.patch(f"/api/canteen/menu/{item_id('Samosa')}", json={"stock_today": 5})
    results = _place_concurrently(["22CS001", "22CS002", "22CS003"], "Samosa", workers=8)
    tokens = [r for r in results if isinstance(r, int)]
    assert sorted(tokens) == [1, 2, 3, 4, 5]
    assert stock("Samosa") == 0


def test_cancel_restores_stock_only_while_placed(ananya, kitchen):
    before = stock("Masala dosa")
    order = ananya.post("/api/canteen/orders", json=cart(("Masala dosa", 2))).json()
    cancelled = ananya.post(f"/api/canteen/orders/{order['id']}/cancel").json()
    assert cancelled["status"] == "cancelled" and stock("Masala dosa") == before

    order = ananya.post("/api/canteen/orders", json=cart(("Masala dosa", 1))).json()
    kitchen.post(f"/api/canteen/orders/{order['id']}/status", json={"status": "preparing"})
    r = ananya.post(f"/api/canteen/orders/{order['id']}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_cancel"
    assert stock("Masala dosa") == before - 1


# --- kitchen --------------------------------------------------------------------------

def test_kitchen_moves_tickets_and_steps_cannot_be_skipped(ananya, kitchen):
    order = ananya.post("/api/canteen/orders", json=cart(("Veg thali", 1))).json()
    skip = kitchen.post(f"/api/canteen/orders/{order['id']}/status", json={"status": "ready"})
    assert skip.status_code == 409 and skip.json()["error"]["code"] == "bad_transition"
    for status in ("preparing", "ready", "collected"):
        r = kitchen.post(f"/api/canteen/orders/{order['id']}/status", json={"status": status})
        assert r.status_code == 200 and r.json()["status"] == status
    board = kitchen.get("/api/canteen/board").json()
    assert board == {"placed": [], "preparing": [], "ready": []}
    mine = ananya.get("/api/canteen/orders/mine").json()["orders"][0]
    assert mine["status"] == "collected" and mine["ready_at"] and mine["collected_at"]


def test_orders_can_be_collected_in_any_order(ananya, priya, kitchen):
    first = ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()
    second = priya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()
    for status in ("preparing", "ready", "collected"):
        assert kitchen.post(f"/api/canteen/orders/{second['id']}/status", json={"status": status}).status_code == 200
    assert [t["token_no"] for t in kitchen.get("/api/canteen/board").json()["placed"]] == [first["token_no"]]


def test_prep_list_totals_match_tickets(ananya, priya, kitchen):
    ananya.post("/api/canteen/orders", json=cart(("Veg fried rice", 2), ("Masala chai", 1)))  # 12:40
    priya.post("/api/canteen/orders", json=cart(("Veg fried rice", 3), pickup="2026-10-05T12:50"))
    late = priya.post("/api/canteen/orders", json=cart(("Samosa", 4), pickup="2026-10-05T13:15")).json()
    done = ananya.post("/api/canteen/orders", json=cart(("Curd rice", 5))).json()
    kitchen.post(f"/api/canteen/orders/{late['id']}/status", json={"status": "preparing"})
    for status in ("preparing", "ready"):  # ready food is already cooked: not on the prep list
        kitchen.post(f"/api/canteen/orders/{done['id']}/status", json={"status": status})

    prep = kitchen.get("/api/canteen/prep-list").json()
    assert [(w["start"][11:16], w["end"][11:16]) for w in prep["windows"]] == [("12:30", "12:45"), ("12:45", "13:00"), ("13:15", "13:30")]
    assert prep["windows"][0]["items"] == [{"name": "Veg fried rice", "qty": 2}, {"name": "Masala chai", "qty": 1}]

    board = kitchen.get("/api/canteen/board").json()
    from_tickets, from_prep = Counter(), Counter()
    for ticket in board["placed"] + board["preparing"]:
        for line in ticket["items"]:
            from_tickets[line["name"]] += line["qty"]
    for window in prep["windows"]:
        for line in window["items"]:
            from_prep[line["name"]] += line["qty"]
    assert from_prep == from_tickets == Counter({"Veg fried rice": 5, "Samosa": 4, "Masala chai": 1})


def test_suggested_prep_is_same_weekday_average(ananya, kitchen):
    samosa = item_id("Samosa")
    with Session(engine) as session:
        student_id = session.exec(select(Student.id)).first()

        def past(days_back: int, qty: int, status: str = "collected") -> None:
            pickup = datetime(2026, 10, 5, 12, 40, tzinfo=IST) - timedelta(days=days_back)
            order = Order(student_id=student_id, token_no=1, status=status, pickup_time=pickup, total=qty * 1500,
                          payment_status="paid_demo", created_at=pickup - timedelta(hours=1))
            session.add(order)
            session.flush()
            session.add(OrderItem(order_id=order.id, menu_item_id=samosa, qty=qty, unit_price=1500))

        past(7, 10)
        past(14, 12)
        past(21, 0)
        past(28, 6)
        past(28, 50, status="cancelled")  # cancelled orders don't count
        past(35, 99)  # five weeks ago: outside the window
        past(1, 99)  # a Sunday, not a Monday
        session.commit()
    ananya.post("/api/canteen/orders", json=cart(("Samosa", 3)))

    data = kitchen.get("/api/canteen/suggested-prep").json()
    assert data["label"] == "Based on the last 4 Mondays"
    row = next(i for i in data["items"] if i["name"] == "Samosa")
    assert row["suggested"] == 7  # (10 + 12 + 0 + 6) / 4
    assert row["preordered_today"] == 3


def test_ready_orders_become_no_show_after_setting_minutes(ananya, kitchen, fixed_real_time):
    order = ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()  # pickup 12:40
    for status in ("preparing", "ready"):
        kitchen.post(f"/api/canteen/orders/{order['id']}/status", json={"status": status})
    fixed_real_time["now"] += timedelta(minutes=45)  # 13:05: only 25 minutes after pickup
    maintenance.run_once()
    assert ananya.get("/api/canteen/orders/mine").json()["orders"][0]["status"] == "ready"
    fixed_real_time["now"] += timedelta(minutes=10)  # 13:15: 35 minutes after pickup
    maintenance.run_once()
    assert ananya.get("/api/canteen/orders/mine").json()["orders"][0]["status"] == "no_show"


def test_menu_control(kitchen, ananya):
    patched = kitchen.patch(f"/api/canteen/menu/{item_id('Cold coffee')}", json={"price": 4500, "stock_today": 7}).json()
    assert patched["price"] == 4500 and patched["stock_today"] == 7
    assert kitchen.patch(f"/api/canteen/menu/{item_id('Cold coffee')}", json={"stock_today": -1}).status_code == 422
    assert kitchen.patch("/api/canteen/menu/9999", json={"is_available": False}).status_code == 404
    q = ananya.post("/api/canteen/quote", json=cart(("Cold coffee", 2))).json()
    assert q["total"] == 9000


# --- permissions and realtime --------------------------------------------------------

def test_permissions(ananya, priya, kitchen):
    order = ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()
    assert priya.post(f"/api/canteen/orders/{order['id']}/cancel").status_code == 404
    assert ananya.get("/api/canteen/board").status_code == 403
    assert ananya.get("/api/canteen/prep-list").status_code == 403
    assert ananya.patch(f"/api/canteen/menu/{item_id('Samosa')}", json={"price": 100}).status_code == 403
    assert ananya.post(f"/api/canteen/orders/{order['id']}/status", json={"status": "preparing"}).status_code == 403
    assert kitchen.post("/api/canteen/orders", json=cart(("Samosa", 1))).status_code == 403
    printer = as_user("staff", "print")
    assert printer.get("/api/canteen/board").status_code == 403
    assert printer.get("/api/canteen/menu").status_code == 403


def test_kitchen_and_student_get_order_events_live(client):
    login(client, "staff", "canteen")
    with client.websocket_connect("/ws") as kitchen_ws:
        ananya = as_user("student", "22CS001")
        order = ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()
        events = [kitchen_ws.receive_json() for _ in range(2)]
    created = next(e for e in events if e["type"] == "order.created")
    assert created["payload"]["token_no"] == order["token_no"]
    assert created["payload"]["student_name"] == "Ananya Rao"
    assert any(e["type"] == "menu.updated" for e in events)


# --- regressions from the Phase 3 review -----------------------------------------

def test_kitchen_step_after_cancel_is_refused_and_stock_counted_once(ananya, kitchen):
    """A cancel and a kitchen step that race: the second one loses with 409."""
    before = stock("Veg fried rice")
    order = ananya.post("/api/canteen/orders", json=cart(("Veg fried rice", 3))).json()
    with Session(engine) as kitchen_session:
        loaded = canteen_service._get_order(kitchen_session, order["id"])  # kitchen reads "placed"
        assert loaded.status == "placed"
        assert ananya.post(f"/api/canteen/orders/{order['id']}/cancel").status_code == 200
        with pytest.raises(ApiError) as refused:
            canteen_service._transition(kitchen_session, loaded, "placed", "preparing", "changed")
        assert refused.value.status == 409
    assert stock("Veg fried rice") == before
    assert ananya.get("/api/canteen/orders/mine").json()["orders"][0]["status"] == "cancelled"


def test_cancel_after_kitchen_started_is_refused(ananya, kitchen):
    order = ananya.post("/api/canteen/orders", json=cart(("Samosa", 1))).json()
    with Session(engine) as student_session:
        loaded = canteen_service._get_order(student_session, order["id"])  # student reads "placed"
        kitchen.post(f"/api/canteen/orders/{order['id']}/status", json={"status": "preparing"})
        with pytest.raises(ApiError) as refused:
            canteen_service._transition(student_session, loaded, "placed", "cancelled", "started")
        assert refused.value.status == 409


def test_earlier_days_unfinished_orders_close_without_returning_stock(ananya, kitchen):
    order = ananya.post("/api/canteen/orders", json=cart(("Veg thali", 2))).json()  # Monday, left placed
    set_demo("2026-10-06T09:00")  # Tuesday
    kitchen.patch(f"/api/canteen/menu/{item_id('Veg thali')}", json={"stock_today": 40})
    refused = ananya.post(f"/api/canteen/orders/{order['id']}/cancel")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "order_closed"
    maintenance.run_once()
    assert ananya.get("/api/canteen/orders/mine").json()["orders"][0]["status"] == "no_show"
    assert stock("Veg thali") == 40
    assert ananya.get("/api/today").json()["orders"] == []


def test_price_change_before_paying_is_refused(ananya, kitchen):
    q = ananya.post("/api/canteen/quote", json=cart(("Veg fried rice", 2))).json()
    kitchen.patch(f"/api/canteen/menu/{item_id('Veg fried rice')}", json={"price": 7000})
    body = cart(("Veg fried rice", 2)) | {"expected_total": q["total"]}
    r = ananya.post("/api/canteen/orders", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "price_changed"
    assert stock("Veg fried rice") == dict((n, st) for n, _c, _p, _v, _m, st, _w in MENU)["Veg fried rice"]
    body["expected_total"] = 14000
    assert ananya.post("/api/canteen/orders", json=body).status_code == 200


def test_menu_updates_only_reach_students_and_kitchen(client, kitchen):
    from app.events import hub

    with client.websocket_connect("/ws") as anonymous:  # no login
        kitchen.patch(f"/api/canteen/menu/{item_id('Samosa')}", json={"stock_today": 12})  # publishes menu.updated
        hub.publish("settings.updated", {"keys": []})
        assert anonymous.receive_json()["type"] == "settings.updated"  # the menu event never arrived
