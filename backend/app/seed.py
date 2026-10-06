"""Reset the database and fill it with placeholder data.

    python -m app.seed

Everything here is placeholder data, to be replaced through CSV import
(Phase 6). Timings, rooms and attendance are not real college data.
Seeds people, rooms, subjects, timetable, attendance, settings, the canteen
menu and six weeks of past canteen orders (so "Suggested prep" has history),
and clears uploaded print files.
"""

import json
import random
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, SQLModel

from app import clock, models  # noqa: F401  (models registers tables)
from app.auth import hash_pin
from app.config import IST, settings
from app.db import engine
from app.models import (
    Attendance, MenuItem, Order, OrderItem, Room, Setting, Staff, Student, Subject, TimetableSlot,
)
from app.services import omi_client, settings_service

DEMO_PIN = "1234"
SECTION = "CSE-3A"

STUDENTS = [
    # roll_no, name. The ID card's barcode carries the roll number, so card_uid = roll_no.
    ("22CS001", "Ananya Rao"),
    ("22CS002", "Priya Nair"),
    ("22CS003", "Rohan Kulkarni"),
    ("22CS004", "Arjun Mehta"),
    ("22CS005", "Sneha Patil"),
    ("22CS006", "Karthik Reddy"),
]

STAFF = [
    ("canteen", "Lakshmi Devi", "canteen"),
    ("print", "Ramesh Gowda", "print"),
    ("admin", "Meera Joshi", "admin"),
]

SUBJECTS = [
    # code, name, short name, kind
    ("CS301", "Database Management Systems", "DBMS", "theory"),
    ("CS302", "Operating Systems", "OS", "theory"),
    ("CS303", "Computer Networks", "CN", "theory"),
    ("CS304", "Theory of Computation", "TOC", "theory"),
    ("CS305", "Software Engineering", "SE", "theory"),
    ("MA301", "Probability and Statistics", "P&S", "theory"),
    ("CS351", "DBMS Lab", "DBMS lab", "lab"),
    ("CS352", "Computer Networks Lab", "CN lab", "lab"),
]

ROOMS = [
    # code, name, block, floor, directions
    ("A-101", "Classroom A-101", "A", 1, "Enter A block from the main gate side. First door on the left after the stairs."),
    ("A-102", "Classroom A-102", "A", 1, "A block ground-floor corridor, second door on the left."),
    ("A-103", "Classroom A-103", "A", 1, "A block ground floor, end of the corridor facing the garden."),
    ("A-201", "Classroom A-201", "A", 2, "A block, take the main stairs to the first floor. First room on the right."),
    ("A-202", "Seminar hall A-202", "A", 2, "A block first floor, double doors opposite the stairs."),
    ("B-101", "Physics lab", "B", 1, "B block ground floor, left wing behind the notice board."),
    ("B-102", "Electronics lab", "B", 1, "B block ground floor, right wing, last room."),
    ("B-201", "Computer lab 1", "B", 2, "B block first floor, turn left at the top of the stairs."),
    ("B-204", "Database lab", "B", 2, "B block first floor, turn right at the top of the stairs. Fourth door."),
    ("B-205", "Networks lab", "B", 2, "B block first floor, right wing, room at the far end."),
    ("C-101", "Library", "C", 1, "C block ground floor, main entrance straight ahead."),
    ("C-102", "Reading room", "C", 1, "C block ground floor, inside the library on the left."),
    ("C-201", "Classroom C-201", "C", 2, "C block first floor, first room past the lift."),
    ("C-202", "Classroom C-202", "C", 2, "C block first floor, second room past the lift."),
    ("C-301", "Drawing hall", "C", 3, "C block second floor, take the lift and turn left."),
]

# Placeholder periods (local time). Breaks live in the `breaks` setting.
PERIODS = [
    (time(9, 0), time(9, 50)),
    (time(9, 50), time(10, 40)),
    (time(11, 0), time(11, 50)),
    (time(11, 50), time(12, 40)),
    (time(13, 30), time(14, 20)),
    (time(14, 20), time(15, 10)),
    (time(15, 10), time(16, 0)),
]
AFTERNOON_LAB = (time(13, 30), time(16, 0))

# Per weekday: four morning periods, then either three afternoon periods or a lab.
# None means a free period.
WEEK = {
    0: (["DBMS", "OS", "CN", "TOC"], "DBMS lab"),
    1: (["OS", "CN", "SE", "P&S"], ["TOC", "DBMS", None]),
    2: (["TOC", "SE", "DBMS", None], "CN lab"),
    3: (["CN", "P&S", "OS", "DBMS"], ["SE", "TOC", None]),
    4: (["SE", "DBMS", "P&S", "OS"], ["CN", None, None]),
    5: (["P&S", "TOC", "CN", "SE"], ["OS", None, None]),
}

THEORY_ROOMS = {"DBMS": "A-101", "OS": "A-101", "CN": "A-102", "TOC": "A-102", "SE": "A-201", "P&S": "A-201"}
LAB_ROOMS = {"DBMS lab": "B-204", "CN lab": "B-205"}

# First student: two subjects below 75%, one exactly at 75%, the rest above.
FIRST_STUDENT_ATTENDANCE = {
    "DBMS": (40, 28),
    "OS": (36, 25),
    "CN": (40, 30),
    "TOC": (40, 36),
    "SE": (38, 33),
    "P&S": (41, 35),
    "DBMS lab": (12, 11),
    "CN lab": (12, 10),
}


# Placeholder menu. Prices in paise; replace through the kitchen's menu control.
MENU = [
    # name, category, price, is_veg, prep_minutes, stock_today, popularity weight
    ("Idli vada", "breakfast", 3000, True, 4, 40, 4),
    ("Masala dosa", "breakfast", 4500, True, 8, 35, 5),
    ("Poha", "breakfast", 2500, True, 3, 30, 3),
    ("Veg fried rice", "meals", 6000, True, 10, 50, 9),
    ("Veg thali", "meals", 8000, True, 5, 40, 7),
    ("Chicken biryani", "meals", 11000, False, 5, 35, 8),
    ("Curd rice", "meals", 4000, True, 3, 30, 4),
    ("Samosa", "snacks", 1500, True, 2, 60, 6),
    ("Veg puff", "snacks", 2000, True, 2, 40, 4),
    ("Egg puff", "snacks", 2500, False, 2, 30, 3),
    ("Masala chai", "drinks", 1200, True, 3, 100, 8),
    ("Cold coffee", "drinks", 4000, True, 4, 40, 4),
]
PAST_DAYS = 42


def _past_orders(students: list[Student], menu: list[MenuItem], today: date) -> tuple[list[Order], list[list[OrderItem]]]:
    """Six weeks of plausible collected orders, Monday to Saturday, for suggested prep."""
    rng = random.Random(7)
    weights = [w for *_, w in MENU]
    by_category: dict[str, list[int]] = {}
    for index, item in enumerate(menu):
        by_category.setdefault(item.category, []).append(index)
    windows = [  # (start, end, categories, share)
        (time(8, 30), time(9, 0), ["breakfast", "drinks"], 0.15),
        (time(10, 40), time(11, 0), ["snacks", "drinks", "breakfast"], 0.25),
        (time(12, 40), time(13, 25), ["meals", "drinks", "snacks"], 0.60),
    ]
    orders, lines = [], []
    for back in range(1, PAST_DAYS + 1):
        day = today - timedelta(days=back)
        if day.weekday() == 6:
            continue
        token = 0
        for _ in range(rng.randint(35, 60)):
            start, end, categories, _share = rng.choices(windows, weights=[w[3] for w in windows])[0]
            span = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
            minute = start.hour * 60 + start.minute + 5 * rng.randint(0, span // 5)
            pickup = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=IST)
            pool = [i for c in categories for i in by_category[c]]
            picks = rng.choices(pool, weights=[weights[i] for i in pool], k=rng.choice([1, 1, 2]))
            chosen: dict[int, int] = {}
            for i in picks:
                chosen[i] = chosen.get(i, 0) + rng.choice([1, 1, 1, 2])
            token += 1
            total = sum(menu[i].price * q for i, q in chosen.items())
            status = rng.choices(["collected", "no_show", "cancelled"], weights=[93, 4, 3])[0]
            created = pickup - timedelta(minutes=rng.randint(15, 120))
            orders.append(Order(
                student_id=rng.choice(students).id, token_no=token, status=status, pickup_time=pickup,
                total=total, payment_status="paid_demo", created_at=created,
                ready_at=pickup - timedelta(minutes=2) if status != "cancelled" else None,
                collected_at=pickup + timedelta(minutes=rng.randint(0, 10)) if status == "collected" else None,
            ))
            lines.append([OrderItem(menu_item_id=menu[i].id, qty=q, unit_price=menu[i].price) for i, q in chosen.items()])
    return orders, lines


def _timetable(subjects: dict[str, Subject], rooms: dict[str, Room]) -> list[TimetableSlot]:
    slots = []
    for weekday, (morning, afternoon) in WEEK.items():
        for (start, end), short in zip(PERIODS[:4], morning):
            if short:
                slots.append(TimetableSlot(section=SECTION, weekday=weekday, start_time=start, end_time=end,
                                           subject_id=subjects[short].id, room_id=rooms[THEORY_ROOMS[short]].id))
        if isinstance(afternoon, str):
            slots.append(TimetableSlot(section=SECTION, weekday=weekday, start_time=AFTERNOON_LAB[0],
                                       end_time=AFTERNOON_LAB[1], subject_id=subjects[afternoon].id,
                                       room_id=rooms[LAB_ROOMS[afternoon]].id))
        else:
            for (start, end), short in zip(PERIODS[4:], afternoon):
                if short:
                    slots.append(TimetableSlot(section=SECTION, weekday=weekday, start_time=start, end_time=end,
                                               subject_id=subjects[short].id, room_id=rooms[THEORY_ROOMS[short]].id))
    return slots


def _attendance(students: list[Student], subjects: dict[str, Subject]) -> list[Attendance]:
    rng = random.Random(42)
    rows = []
    for index, student in enumerate(students):
        for short, subject in subjects.items():
            if index == 0:
                held, attended = FIRST_STUDENT_ATTENDANCE[short]
            else:
                held = 12 if subject.kind == "lab" else rng.randint(36, 42)
                attended = round(held * rng.uniform(0.66, 0.97))
            rows.append(Attendance(student_id=student.id, subject_id=subject.id,
                                   classes_held=held, classes_attended=attended))
    return rows


def _clear_uploads() -> None:
    """Uploaded PDFs belong to jobs that are about to be wiped, so delete them too."""
    if settings.upload_dir.is_dir():
        for path in settings.upload_dir.glob("*.pdf"):
            path.unlink(missing_ok=True)


def _demo_memories(start: datetime, menu_ids: dict[str, int]) -> None:
    """Ananya's history in shared memory, so the agents' demo has something to remember:
    her usual Monday lunch (the last three Mondays), how she printed last time, and a deadline."""
    from app.services import memory_service

    usual = [("Veg fried rice", 1), ("Masala chai", 1)]
    items = [{"menu_item_id": menu_ids[name], "name": name, "qty": qty} for name, qty in usual]
    text = ", ".join(f"{name} × {qty}" for name, qty in usual)
    student_id = 1  # Ananya, the first seeded student
    try:
        for weeks in (3, 2, 1):
            ordered = start - timedelta(weeks=weeks, minutes=5)
            memory_service.remember(
                student_id, f"Ordered {text} for 12:40 pm pickup on a Monday", kind="action", written_by="canteen",
                data={"order_id": None, "weekday": 0, "pickup": "12:40", "items": items}, at=ordered)
        memory_service.remember(
            student_id, "Printed DBMS_lab_record.pdf: 2 copies, black and white, double sided", kind="action",
            written_by="print", data={"copies": 2, "color": False, "double_sided": True, "pages": 4},
            at=start - timedelta(days=4, hours=2))
        # As if Omi heard it in a conversation (addendum G: the print agent uses an Omi fact for a deadline).
        thursday = start.date() + timedelta(days=(3 - start.weekday()) % 7)
        memory_service.remember(
            student_id, "DBMS lab record is due Thursday", kind="fact", written_by="omi", source_ref="omi:demo",
            data={"category": "deadline", "due": thursday.isoformat(), "nudge": True, "conversation": "demo"},
            at=start - timedelta(days=2, hours=5))
    except Exception as exc:  # memory being down mustn't stop a reset
        print(f"Couldn't write the demo memories: {exc!r}")


def seed(demo: bool | None = None) -> None:
    """Reset every table and load placeholder data.

    With `demo` (default: the DEMO_MODE setting) the clock is set to this week's
    Monday 12:20 and canteen history is built from the weeks before it.
    """
    from app import demo as demo_mode  # local import: demo imports seed lazily too

    demo = settings.demo_mode if demo is None else demo
    _clear_uploads()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    settings_service.invalidate()  # old settings (e.g. a previous demo time) are gone with the tables
    start = demo_mode.demo_start() if demo else None
    today = start.date() if start else clock.today()
    pin_hash = hash_pin(DEMO_PIN)

    with Session(engine) as session:
        students = [
            Student(roll_no=roll, name=name, branch="CSE", year=3, section=SECTION,
                    pin_hash=pin_hash, card_uid=roll,
                    # Demo: a pretend Omi id per student, so the Omi simulator works without a device.
                    omi_uid=f"{omi_client.DEMO_UID_PREFIX}{roll}" if demo else None)
            for roll, name in STUDENTS
        ]
        staff = [Staff(username=u, name=n, role=r, pin_hash=pin_hash) for u, n, r in STAFF]
        subjects = {short: Subject(code=code, name=name, short_name=short, kind=kind)
                    for code, name, short, kind in SUBJECTS}
        rooms = {code: Room(code=code, name=name, block=block, floor=floor, directions=directions)
                 for code, name, block, floor, directions in ROOMS}
        session.add_all([*students, *staff, *subjects.values(), *rooms.values()])
        session.commit()
        for row in [*students, *subjects.values(), *rooms.values()]:
            session.refresh(row)

        menu = [MenuItem(name=n, category=c, price=p, is_veg=v, prep_minutes=m, stock_today=st, is_available=True)
                for n, c, p, v, m, st, _w in MENU]
        session.add_all(menu)
        session.commit()
        for item in menu:
            session.refresh(item)
        orders, order_lines = _past_orders(students, menu, today)
        session.add_all(orders)
        session.flush()
        for order, items in zip(orders, order_lines):
            for line in items:
                line.order_id = order.id
            session.add_all(items)

        session.add_all(_timetable(subjects, rooms))
        session.add_all(_attendance(students, subjects))

        values = dict(settings_service.DEFAULTS) | {"demo_pin": DEMO_PIN}
        session.add_all(Setting(key=k, value=json.dumps(v)) for k, v in values.items())
        session.commit()
        menu_ids = {item.name: item.id for item in menu}

    settings_service.invalidate()
    if start:
        clock.set_demo_time(start)
    # Memories live in Qdrant, which survives a reset; old ones would point at
    # orders and jobs that no longer exist.
    from app.services import memory_service

    memory_service.forget_students(list(range(1, len(STUDENTS) + 1)))
    if start:
        _demo_memories(start, menu_ids)
    print(f"Seeded {len(STUDENTS)} students, {len(STAFF)} staff, {len(SUBJECTS)} subjects, "
          f"{len(ROOMS)} rooms, {len(MENU)} menu items and {PAST_DAYS} days of past orders. "
          f"PIN for every account: {DEMO_PIN}"
          + (f". Demo time: {start:%a %d %b %H:%M}" if start else ""))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reset the database and load placeholder data.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--demo", dest="demo", action="store_true", default=None,
                       help="start the demo clock at this week's Monday 12:20 (default: DEMO_MODE)")
    group.add_argument("--no-demo", dest="demo", action="store_false", help="real time, no demo clock")
    seed(demo=parser.parse_args().demo)
