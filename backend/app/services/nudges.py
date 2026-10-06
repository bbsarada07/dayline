"""Nudges on the Today screen (spec 5.6): at most two, from plain rules, never from a model.

Each nudge says one thing and offers one action: open a screen, or ask Dayline something.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlmodel import Session

from app import clock
from app.models import Student
from app.services import attendance_service, canteen_service, memory_service, print_service, timetable_service

log = logging.getLogger("dayline.nudges")

MAX_NUDGES = 2
LAB_WINDOW = timedelta(minutes=60)
LUNCH_WINDOW = timedelta(minutes=30)


@dataclass
class Nudge:
    id: str
    agent: str  # timetable | print | canteen | omi: the colour it's shown in
    text: str
    action: str  # button label
    to: str | None = None  # a screen to open
    ask: str | None = None  # or a question for Dayline


def _t(value) -> str:
    return print_service.short_time(value)


def _omi_nudge(session: Session, student: Student) -> Nudge | None:
    """Something Omi heard that needs printing or handing in by a day, until it's printed or the day passes."""
    try:
        heard = memory_service.list_memories(student.id, 30, written_by="omi")
    except Exception as exc:  # memory trouble must never break the Today screen
        log.warning("Omi nudge skipped: %r", exc)
        return None
    today = clock.today()
    for memory in heard:
        due = memory.data.get("due")
        if not memory.data.get("nudge") or not due or date.fromisoformat(due) < today:
            continue
        noted = datetime.fromisoformat(memory.created_at)
        if any(j.created_at >= noted for j in print_service.list_mine(session, student.id)):
            continue  # printed something since Omi heard it
        day = "today" if date.fromisoformat(due) == today else f"{date.fromisoformat(due):%A}"
        return Nudge(f"omi-{memory.id}", "omi", f"Omi heard: {memory.text.rstrip('.')}. Print it now?",
                     "Print a file", ask=f"Print this before {day}")
    return None


def nudges_for(session: Session, student: Student) -> list[Nudge]:
    """Today's nudges for this student, most urgent first."""
    now = clock.local_now()
    found: list[Nudge] = []
    jobs = print_service.jobs_for_today(session, student.id)
    orders = canteen_service.orders_for_today(session, student.id)

    for job in jobs:
        if job.status == "ready":
            found.append(Nudge(f"print-ready-{job.code}", "print", f"Your printout {job.code} is ready at the print shop.",
                               "See print jobs", to="/print"))
    for order in orders:
        if order["status"] == "ready":
            found.append(Nudge(f"order-ready-{order['token_no']}", "canteen",
                               f"Token {order['token_no']} is ready at the counter.", "See orders", to="/canteen"))

    if heard := _omi_nudge(session, student):
        found.append(heard)

    items = timetable_service.today_schedule(session, student.section)
    lab = next((i for i in items if i.kind == "class" and i.status == "upcoming" and i.subject_kind == "lab"), None)
    if lab and lab.start - now <= LAB_WINDOW and not any(j.status in print_service.ACTIVE for j in jobs):
        name = lab.label if lab.label.lower().endswith("lab") else f"{lab.label} lab"
        found.append(Nudge(f"lab-print-{lab.id}", "print", f"Your {name} is at {_t(lab.start)}. Anything to print?",
                           "Print a file", ask="Print 1 copy of this before my next lab"))

    lunch = next((i for i in items if i.kind == "break" and "lunch" in i.label.lower() and i.status != "past"), None)
    if lunch and lunch.start - now <= LUNCH_WINDOW and not any(o["status"] in canteen_service.ACTIVE for o in orders):
        found.append(Nudge(f"lunch-{clock.today().isoformat()}", "canteen", f"Lunch is at {_t(lunch.start)} and you haven't ordered.",
                           "Order my usual", ask="Get me my usual lunch"))

    below = [r for r in attendance_service.list_for_student(session, student.id) if r.standing.status == "below"]
    if below:
        worst = below[0]
        found.append(Nudge(f"attendance-{worst.subject_id}", "timetable",
                           f"{worst.short_name or worst.name} attendance: {worst.standing.statement}",
                           "See attendance", to="/attendance"))
    return found[:MAX_NUDGES]
