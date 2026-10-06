"""Nudges on the Today screen (spec 5.6): at most two, from plain rules, never from a model.

Each nudge says one thing and offers one action: open a screen, or ask Dayline something.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session

from app import clock
from app.models import Student
from app.services import attendance_service, canteen_service, print_service, timetable_service

MAX_NUDGES = 2
LAB_WINDOW = timedelta(minutes=60)
LUNCH_WINDOW = timedelta(minutes=30)


@dataclass
class Nudge:
    id: str
    agent: str  # timetable | print | canteen: the colour it's shown in
    text: str
    action: str  # button label
    to: str | None = None  # a screen to open
    ask: str | None = None  # or a question for Dayline


def _t(value) -> str:
    return print_service.short_time(value)


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
