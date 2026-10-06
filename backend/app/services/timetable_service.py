"""A section's day: classes, breaks and free time, relative to the clock."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from app import clock
from app.config import IST
from app.models import Room, Subject, TimetableSlot
from app.services import settings_service


@dataclass
class DayItem:
    id: str
    kind: str  # class | break | free
    start: datetime  # aware, college local time
    end: datetime
    status: str  # past | current | upcoming
    label: str  # "DBMS", "Lunch break", "Free"
    subject_id: int | None = None
    subject_code: str | None = None
    subject_name: str | None = None
    subject_kind: str | None = None  # theory | lab
    room_code: str | None = None
    room_name: str | None = None


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _at(day: date, minute_of_day: int) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=IST) + timedelta(minutes=minute_of_day)


def _status(start: datetime, end: datetime, now: datetime) -> str:
    if now >= end:
        return "past"
    if now >= start:
        return "current"
    return "upcoming"


def _class_slots(session: Session, section: str, weekday: int):
    return session.exec(
        select(TimetableSlot, Subject, Room)
        .join(Subject, Subject.id == TimetableSlot.subject_id)
        .join(Room, Room.id == TimetableSlot.room_id)
        .where(TimetableSlot.section == section, TimetableSlot.weekday == weekday)
        .order_by(TimetableSlot.start_time)
    ).all()


def day_schedule(session: Session, section: str, day: date) -> list[DayItem]:
    """All items for `day`: classes, plus breaks and free gaps between them.

    Days with no classes return an empty list.
    """
    slots = _class_slots(session, section, day.weekday())
    if not slots:
        return []
    now = clock.now()
    college = settings_service.get("college_day")
    day_start = min(_parse_hhmm(college["start"]), slots[0][0].start_time)
    day_end = max(_parse_hhmm(college["end"]), max(s[0].end_time for s in slots))
    first, last = _minutes(day_start), _minutes(day_end)

    # Label every minute of the day, then merge runs. Classes win over breaks.
    labels: list[tuple] = [("free",)] * (last - first)
    for brk in settings_service.get("breaks"):
        for m in range(max(_minutes(_parse_hhmm(brk["start"])), first), min(_minutes(_parse_hhmm(brk["end"])), last)):
            labels[m - first] = ("break", brk["name"])
    for index, (slot, _subject, _room) in enumerate(slots):
        for m in range(_minutes(slot.start_time), _minutes(slot.end_time)):
            labels[m - first] = ("class", index)

    items: list[DayItem] = []
    run_start = 0
    for m in range(1, len(labels) + 1):
        if m < len(labels) and labels[m] == labels[run_start]:
            continue
        items.append(_make_item(day, first + run_start, first + m, labels[run_start], slots, now))
        run_start = m
    return items


def _make_item(day: date, start_min: int, end_min: int, label: tuple, slots, now: datetime) -> DayItem:
    start, end = _at(day, start_min), _at(day, end_min)
    status = _status(start, end, now)
    item_id = f"{label[0]}-{day.isoformat()}-{start_min}"
    if label[0] == "free":
        return DayItem(item_id, "free", start, end, status, "Free")
    if label[0] == "break":
        return DayItem(item_id, "break", start, end, status, label[1])
    slot, subject, room = slots[label[1]]
    return DayItem(
        item_id, "class", start, end, status, subject.short_name or subject.name,
        subject.id, subject.code, subject.name, subject.kind, room.code, room.name,
    )


def today_schedule(session: Session, section: str) -> list[DayItem]:
    return day_schedule(session, section, clock.today())


def next_class(session: Session, section: str) -> DayItem | None:
    """The next class today that has not started yet, or None."""
    return next(
        (i for i in today_schedule(session, section) if i.kind == "class" and i.status == "upcoming"),
        None,
    )


def current_item(items: list[DayItem]) -> DayItem | None:
    return next((i for i in items if i.status == "current"), None)


def free_slots(session: Session, section: str) -> list[DayItem]:
    """Today's breaks and free gaps (past ones included, with their status)."""
    return [i for i in today_schedule(session, section) if i.kind != "class"]
