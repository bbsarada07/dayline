"""Canteen: menu, quotes, orders, tokens, kitchen board, prep list (spec 5.4, trimmed by addendum K).

REST routes and (later) agent tools both call these functions; there is no
canteen logic anywhere else.
"""

import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, or_, update
from sqlmodel import Session, col, select

from app import clock
from app.config import IST
from app.errors import ApiError
from app.events import hub
from app.models import MenuItem, Order, OrderItem, Student
from app.services import memory_service, payments, settings_service, timetable_service

STEP_MINUTES = 5
WINDOW_MINUTES = 15
MAX_QTY_PER_ITEM = 10
MAX_LINES = 10
ACTIVE = ("placed", "preparing", "ready")
TO_COOK = ("placed", "preparing")
SUGGEST_WEEKS = 4
ALLOWED_STAFF_MOVES = {"placed": "preparing", "preparing": "ready", "ready": "collected"}
CATEGORY_ORDER = ["breakfast", "meals", "snacks", "drinks"]

# Placing an order reads the day's last token and decrements stock. One process
# serves the app, so a lock keeps two simultaneous orders from taking the same
# token; the conditional stock UPDATE below also guards stock on its own.
_order_lock = threading.Lock()


# --- helpers ------------------------------------------------------------------

def _load(value: datetime) -> datetime:
    """Stored (aware UTC) -> college time."""
    return value.astimezone(IST)


def short_time(value: datetime) -> str:
    local = value.astimezone(IST)
    return f"{local.hour % 12 or 12}:{local.minute:02d}"


def _hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _ceil_step(value: datetime, minutes: int = STEP_MINUTES) -> datetime:
    """Round up to the next multiple of `minutes` (seconds dropped)."""
    value = value.astimezone(IST)
    floor = value.replace(second=0, microsecond=0)
    if floor < value:
        floor += timedelta(minutes=1)
    extra = (-floor.minute) % minutes
    return floor + timedelta(minutes=extra)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """Start and end of a college-local day as aware datetimes."""
    start = datetime.combine(day, time(0, 0), tzinfo=IST)
    return start, start + timedelta(days=1)


def canteen_hours(day: date) -> tuple[datetime, datetime]:
    hours = settings_service.get("canteen_hours")
    return (
        datetime.combine(day, _hhmm(hours["open"]), tzinfo=IST),
        datetime.combine(day, _hhmm(hours["close"]), tzinfo=IST),
    )


def _publish_order(session: Session, order: Order, event: str) -> None:
    student = session.get(Student, order.student_id)
    hub.publish(event, order_view(session, order, student), student_id=order.student_id, roles=("canteen",))


def _publish_menu(items: list[MenuItem]) -> None:
    # Same audience as GET /canteen/menu: students and kitchen staff, not signed-out or other staff.
    hub.publish("menu.updated", {"items": [menu_item_view(i) for i in items]}, roles=("student", "canteen"))


# --- menu -----------------------------------------------------------------------

def menu_item_view(item: MenuItem) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "price": item.price,
        "category": item.category,
        "is_veg": item.is_veg,
        "prep_minutes": item.prep_minutes,
        "stock_today": item.stock_today,
        "is_available": item.is_available,
        "can_order": item.is_available and item.stock_today > 0,
    }


def menu(session: Session) -> list[MenuItem]:
    """Every menu item, by category then name."""
    items = session.exec(select(MenuItem)).all()
    rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(items, key=lambda i: (rank.get(i.category, len(rank)), i.name))


def update_menu_item(
    session: Session, item_id: int, *, is_available: bool | None = None,
    stock_today: int | None = None, price: int | None = None,
) -> MenuItem:
    """Staff: toggle availability, set today's stock, edit price."""
    item = session.get(MenuItem, item_id)
    if item is None:
        raise ApiError(404, "item_not_found", "That menu item doesn't exist.")
    if stock_today is not None:
        if not 0 <= stock_today <= 1000:
            raise ApiError(422, "bad_stock", "Stock must be between 0 and 1000.")
        item.stock_today = stock_today
    if price is not None:
        if not 100 <= price <= 100_000:
            raise ApiError(422, "bad_price", "Price must be between ₹1 and ₹1000.")
        item.price = price
    if is_available is not None:
        item.is_available = is_available
    session.add(item)
    session.commit()
    session.refresh(item)
    _publish_menu([item])
    return item


# --- quote ------------------------------------------------------------------------

@dataclass
class CartLine:
    menu_item_id: int
    qty: int


def _merge_lines(lines: list[CartLine]) -> dict[int, int]:
    if not lines:
        raise ApiError(422, "empty_cart", "Add at least one item.")
    merged: dict[int, int] = defaultdict(int)
    for line in lines:
        merged[line.menu_item_id] += line.qty
    if len(merged) > MAX_LINES:
        raise ApiError(422, "too_many_items", f"An order can have at most {MAX_LINES} different items.")
    for qty in merged.values():
        if not 1 <= qty <= MAX_QTY_PER_ITEM:
            raise ApiError(422, "bad_qty", f"Order between 1 and {MAX_QTY_PER_ITEM} of each item.")
    return dict(merged)


def _load_cart(session: Session, merged: dict[int, int]) -> list[tuple[MenuItem, int]]:
    rows = []
    for item_id, qty in merged.items():
        item = session.get(MenuItem, item_id)
        if item is None:
            raise ApiError(404, "item_not_found", "One of those items isn't on the menu.")
        if not item.is_available:
            raise ApiError(409, "item_unavailable", f"{item.name} isn't available right now. Remove it to continue.")
        if item.stock_today < qty:
            left = "is sold out" if item.stock_today == 0 else f"has only {item.stock_today} left"
            raise ApiError(409, "out_of_stock", f"{item.name} {left}. Change the quantity to continue.")
        rows.append((item, qty))
    return rows


@dataclass
class PickupPlan:
    earliest: datetime
    default: datetime
    reason: str
    slots: list[datetime]


def pickup_plan(session: Session, student: Student, max_prep: int) -> PickupPlan:
    """Earliest feasible pickup, the suggested default, and every 5-minute choice until closing.

    Default: start of the student's next free slot or break today (no earlier than the
    food can be ready); otherwise the earliest time that allows for the longest prep.
    """
    now = clock.local_now()
    opens, closes = canteen_hours(now.date())
    earliest = max(_ceil_step(now + timedelta(minutes=max_prep)), _ceil_step(opens))
    if earliest > closes:
        raise ApiError(409, "canteen_closed", f"The canteen takes orders for pickup until {short_time(closes)}. Try again tomorrow.")

    default, reason = earliest, "That's the earliest your food can be ready."
    for gap in timetable_service.free_slots(session, student.section):
        if gap.end <= earliest:
            continue
        candidate = max(_ceil_step(gap.start), earliest)
        if candidate < gap.end and candidate <= closes:
            default = candidate
            what = gap.label.lower() if gap.kind == "break" else "free time"
            reason = (f"Your {what} starts at {short_time(gap.start)}." if candidate == _ceil_step(gap.start)
                      else f"It's the earliest it can be ready during your {what}.")
            break

    slots = []
    t = earliest
    while t <= closes:
        slots.append(t)
        t += timedelta(minutes=STEP_MINUTES)
    return PickupPlan(earliest, default, reason, slots)


@dataclass
class QuoteLine:
    menu_item_id: int
    name: str
    qty: int
    unit_price: int
    line_total: int
    is_veg: bool


@dataclass
class Quote:
    lines: list[QuoteLine]
    total: int
    max_prep_minutes: int
    pickup_time: datetime
    pickup_is_default: bool
    pickup_reason: str | None
    earliest_pickup: datetime
    pickup_slots: list[datetime]


def _validate_pickup(pickup: datetime, plan: PickupPlan) -> datetime:
    if pickup.tzinfo is None:
        pickup = pickup.replace(tzinfo=IST)
    pickup = pickup.astimezone(IST)
    if pickup.second or pickup.microsecond or pickup.minute % STEP_MINUTES:
        raise ApiError(422, "bad_pickup_step", "Pick a pickup time on a 5-minute mark, like 12:40 or 12:45.")
    if pickup < plan.earliest:
        raise ApiError(422, "pickup_too_soon", f"Your food can't be ready before {short_time(plan.earliest)}. Pick a later time.")
    if pickup not in plan.slots:
        raise ApiError(422, "pickup_outside_hours", "That pickup time is outside canteen hours today.")
    return pickup


def quote(session: Session, student: Student, lines: list[CartLine], pickup: datetime | None = None) -> Quote:
    """Total, pickup suggestion and choices for a cart, without placing anything."""
    rows = _load_cart(session, _merge_lines(lines))
    max_prep = max(item.prep_minutes for item, _ in rows)
    plan = pickup_plan(session, student, max_prep)
    chosen = _validate_pickup(pickup, plan) if pickup is not None else plan.default
    quote_lines = [
        QuoteLine(item.id, item.name, qty, item.price, item.price * qty, item.is_veg) for item, qty in rows
    ]
    return Quote(
        quote_lines, sum(l.line_total for l in quote_lines), max_prep, chosen, pickup is None,
        plan.reason if pickup is None else None, plan.earliest, plan.slots,
    )


# --- orders -------------------------------------------------------------------------

def _items_for(session: Session, order_ids: list[int]) -> dict[int, list[dict]]:
    if not order_ids:
        return {}
    rows = session.exec(
        select(OrderItem, MenuItem)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .where(col(OrderItem.order_id).in_(order_ids))
        .order_by(OrderItem.id)
    ).all()
    out: dict[int, list[dict]] = defaultdict(list)
    for line, item in rows:
        out[line.order_id].append(
            {"menu_item_id": item.id, "name": item.name, "qty": line.qty, "unit_price": line.unit_price, "is_veg": item.is_veg}
        )
    return out


def order_view(session: Session, order: Order, student: Student | None = None, items: list[dict] | None = None) -> dict:
    view = {
        "id": order.id,
        "token_no": order.token_no,
        "status": order.status,
        "pickup_time": _load(order.pickup_time),
        "total": order.total,
        "payment_status": order.payment_status,
        "created_at": _load(order.created_at),
        "ready_at": _load(order.ready_at) if order.ready_at else None,
        "collected_at": _load(order.collected_at) if order.collected_at else None,
        "items": items if items is not None else _items_for(session, [order.id]).get(order.id, []),
    }
    if student is not None:
        view |= {"student_name": student.name, "roll_no": student.roll_no}
    return view


def _transition(session: Session, order: Order, expected: str, new: str, conflict: str) -> None:
    """Move an order from `expected` to `new` only if nobody changed it in between.

    The UPDATE is conditional on the current status, so a student's cancel and a
    kitchen step that race can't both win. Raises 409 with `conflict` otherwise.
    """
    values: dict = {"status": new}
    if new == "ready":
        values["ready_at"] = clock.to_utc(clock.now())
    if new == "collected":
        values["collected_at"] = clock.to_utc(clock.now())
    result = session.execute(update(Order).where(Order.id == order.id, Order.status == expected).values(**values))
    if result.rowcount != 1:
        session.rollback()
        raise ApiError(409, "status_changed", conflict)


def _next_token(session: Session) -> int:
    start, end = _day_bounds(clock.today())
    last = session.exec(
        select(Order.token_no).where(Order.created_at >= start, Order.created_at < end)
        .order_by(col(Order.token_no).desc())
    ).first()
    return (last or 0) + 1


def place_order(
    session: Session, student: Student, lines: list[CartLine], pickup: datetime | None = None,
    expected_total: int | None = None,
) -> Order:
    """Pay (demo) and place an order. Only called when the student confirms.

    `expected_total` is the total the student saw; if prices changed since, nothing is charged.
    """
    with _order_lock:
        q = quote(session, student, lines, pickup)
        if expected_total is not None and expected_total != q.total:
            raise ApiError(409, "price_changed", f"The total is now ₹{q.total / 100:g}. Check your order and confirm again.")
        payment = payments.provider().charge(q.total, f"canteen:{student.id}")
        try:
            for line in q.lines:
                # Atomic: never lets stock go below zero, even if another order slipped in.
                result = session.execute(
                    update(MenuItem)
                    .where(MenuItem.id == line.menu_item_id, MenuItem.stock_today >= line.qty, MenuItem.is_available)
                    .values(stock_today=MenuItem.stock_today - line.qty)
                )
                if result.rowcount != 1:
                    raise ApiError(409, "out_of_stock", f"{line.name} just sold out. Change your order to continue.")
            order = Order(
                student_id=student.id, token_no=_next_token(session), status="placed",
                pickup_time=clock.to_utc(q.pickup_time), total=q.total, payment_status=payment.status,
                created_at=clock.to_utc(clock.now()),
            )
            session.add(order)
            session.flush()
            session.add_all(
                OrderItem(order_id=order.id, menu_item_id=l.menu_item_id, qty=l.qty, unit_price=l.unit_price)
                for l in q.lines
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
    session.refresh(order)
    _publish_order(session, order, "order.created")
    _publish_menu([session.get(MenuItem, l.menu_item_id) for l in q.lines])
    _remember_order(student, order, q)
    return order


def _remember_order(student: Student, order: Order, q: Quote) -> None:
    """Shared memory: what was ordered, for when and on which weekday ("my usual Monday lunch")."""
    pickup = _load(order.pickup_time)
    items = ", ".join(f"{line.name} × {line.qty}" for line in q.lines)
    memory_service.remember_later(
        student.id, f"Ordered {items} for {short_time(pickup)} pickup on a {pickup:%A}",
        kind="action", written_by="canteen", source_ref=f"order:{order.id}",
        data={
            "order_id": order.id, "weekday": pickup.weekday(), "pickup": f"{pickup:%H:%M}",
            "items": [{"menu_item_id": l.menu_item_id, "name": l.name, "qty": l.qty} for l in q.lines],
        },
    )


def _get_order(session: Session, order_id: int) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise ApiError(404, "order_not_found", "That order doesn't exist.")
    return order


def get_own_order(session: Session, student_id: int, order_id: int) -> Order:
    order = session.get(Order, order_id)
    if order is None or order.student_id != student_id:
        raise ApiError(404, "order_not_found", "That order doesn't exist.")
    return order


def list_mine(session: Session, student_id: int) -> list[dict]:
    """The student's orders: active ones by pickup time, then the 20 most recent others."""
    orders = session.exec(select(Order).where(Order.student_id == student_id)).all()
    active = sorted((o for o in orders if o.status in ACTIVE), key=lambda o: (o.pickup_time, o.id))
    done = sorted((o for o in orders if o.status not in ACTIVE), key=lambda o: o.created_at, reverse=True)[:20]
    chosen = active + done
    items = _items_for(session, [o.id for o in chosen])
    return [order_view(session, o, items=items.get(o.id, [])) for o in chosen]


def orders_for_today(session: Session, student_id: int) -> list[dict]:
    """Orders to pin on the Today line: active ones, and ones picked up (or missed) today."""
    today = clock.today()
    return [
        o for o in list_mine(session, student_id)
        if o["status"] in ACTIVE or (o["status"] in ("collected", "no_show") and o["pickup_time"].date() == today)
    ]


def cancel(session: Session, student_id: int, order_id: int) -> Order:
    """Student cancels their own order while it's still `placed`. Stock goes back."""
    with _order_lock:
        order = get_own_order(session, student_id, order_id)
        if order.status != "placed":
            raise ApiError(409, "cannot_cancel", "This order can't be cancelled: the kitchen has already started it.")
        if _load(order.pickup_time).date() < clock.today():
            # Stock is per day; returning an old order's portions would add to today's.
            raise ApiError(409, "order_closed", "This order was for an earlier day, so it can't be cancelled now.")
        _transition(session, order, "placed", "cancelled",
                    "This order can't be cancelled: the kitchen has already started it.")
        lines = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        for line in lines:
            session.execute(
                update(MenuItem).where(MenuItem.id == line.menu_item_id)
                .values(stock_today=MenuItem.stock_today + line.qty)
            )
        payments.provider().refund(f"canteen:{order.id}", order.total)
        session.commit()
    session.refresh(order)
    _publish_order(session, order, "order.updated")
    _publish_menu([session.get(MenuItem, l.menu_item_id) for l in lines])
    return order


def set_status(session: Session, order_id: int, status: str) -> Order:
    """Kitchen moves an order one step: placed -> preparing -> ready -> collected."""
    order = _get_order(session, order_id)
    if ALLOWED_STAFF_MOVES.get(order.status) != status:
        raise ApiError(409, "bad_transition", f"Token {order.token_no} is {order.status}, so it can't be marked {status}. Refresh the board.")
    _transition(session, order, order.status, status,
                f"Token {order.token_no} just changed (it may have been cancelled). Refresh the board.")
    session.commit()
    session.refresh(order)
    _publish_order(session, order, "order.updated")
    return order


# --- kitchen ---------------------------------------------------------------------

def _today_orders(session: Session, statuses: tuple[str, ...]) -> list[Order]:
    start, end = _day_bounds(clock.today())
    return session.exec(
        select(Order).where(col(Order.status).in_(statuses), Order.pickup_time >= start, Order.pickup_time < end)
    ).all()


def board(session: Session) -> dict:
    """Today's tickets in three columns, each by pickup time then token."""
    orders = sorted(_today_orders(session, ACTIVE), key=lambda o: (o.pickup_time, o.token_no))
    students = {s.id: s for s in session.exec(select(Student)).all()}
    items = _items_for(session, [o.id for o in orders])
    columns: dict[str, list[dict]] = {status: [] for status in ACTIVE}
    for order in orders:
        columns[order.status].append(order_view(session, order, students.get(order.student_id), items.get(order.id, [])))
    return {"placed": columns["placed"], "preparing": columns["preparing"], "ready": columns["ready"]}


def prep_list(session: Session) -> dict:
    """What to cook: per 15-minute pickup window, total quantity per item (placed + preparing)."""
    orders = _today_orders(session, TO_COOK)
    items = _items_for(session, [o.id for o in orders])
    windows: dict[datetime, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for order in orders:
        local = _load(order.pickup_time)
        start = local.replace(minute=local.minute - local.minute % WINDOW_MINUTES, second=0, microsecond=0)
        for line in items.get(order.id, []):
            windows[start][line["name"]] += line["qty"]
    return {
        "window_minutes": WINDOW_MINUTES,
        "windows": [
            {
                "start": start,
                "end": start + timedelta(minutes=WINDOW_MINUTES),
                "items": [{"name": name, "qty": qty} for name, qty in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))],
                "total": sum(totals.values()),
            }
            for start, totals in sorted(windows.items())
        ],
    }


def suggested_prep(session: Session) -> dict:
    """Per item: rounded average quantity ordered on the same weekday over the last 4 weeks,
    beside today's pre-orders. A simple average (no forecasting)."""
    today = clock.today()
    past_days = [today - timedelta(weeks=w) for w in range(1, SUGGEST_WEEKS + 1)]
    history: dict[int, int] = defaultdict(int)
    for day in past_days:
        start, end = _day_bounds(day)
        rows = session.exec(
            select(OrderItem.menu_item_id, OrderItem.qty)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.pickup_time >= start, Order.pickup_time < end, Order.status != "cancelled")
        ).all()
        for item_id, qty in rows:
            history[item_id] += qty

    start, end = _day_bounds(today)
    preorders: dict[int, int] = defaultdict(int)
    for item_id, qty in session.exec(
        select(OrderItem.menu_item_id, OrderItem.qty)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.pickup_time >= start, Order.pickup_time < end, Order.status != "cancelled")
    ).all():
        preorders[item_id] += qty

    return {
        "label": f"Based on the last {SUGGEST_WEEKS} {today.strftime('%A')}s",
        "items": [
            {
                **menu_item_view(item),
                "suggested": int(history[item.id] / SUGGEST_WEEKS + 0.5),  # round half up
                "preordered_today": preorders[item.id],
            }
            for item in menu(session)
        ],
    }


# --- maintenance (runs every minute) ----------------------------------------------

def mark_no_shows(session: Session) -> int:
    """Close orders nobody will finish.

    - `ready` orders still uncollected N minutes after pickup (N is a setting) become `no_show`;
    - `placed`/`preparing` orders from an earlier day also become `no_show`. They are off the
      kitchen board (it shows today) and stock is per day, so no stock is returned.
    Each change is conditional on the status read, so it never overwrites a kitchen step.
    """
    minutes = int(settings_service.get("no_show_minutes"))
    cutoff = clock.now() - timedelta(minutes=minutes)
    day_start, _ = _day_bounds(clock.today())
    stale = session.exec(
        select(Order).where(or_(
            and_(Order.status == "ready", Order.pickup_time < cutoff),
            and_(col(Order.status).in_(TO_COOK), Order.pickup_time < day_start),
        ))
    ).all()
    closed = []
    for order in stale:
        result = session.execute(
            update(Order).where(Order.id == order.id, Order.status == order.status).values(status="no_show")
        )
        if result.rowcount == 1:
            closed.append(order.id)
    session.commit()
    for order_id in closed:
        _publish_order(session, session.get(Order, order_id), "order.updated")
    return len(closed)
