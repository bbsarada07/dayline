"""Collect by barcode (addendum E; the collection rules of spec 5.5).

A staff dashboard's scan field is the reader: a USB barcode scanner types the code
from the student's ID card and presses Enter. The scan, the demo "Simulate scan"
and any future reader all go through `collect()`, so they share one code path:
same statuses, same 3-second repeat guard, same TapLog, same realtime events.
"""

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from app import clock
from app.config import IST
from app.errors import ApiError
from app.events import hub
from app.models import Order, PrintJob, Student, TapLog
from app.services import canteen_service, print_service, settings_service

STATIONS = ("canteen", "print")
REPEAT_WINDOW = timedelta(seconds=3)
MAX_CODE_LENGTH = 64

# Last accepted scan per (reader, code), in wall-clock time: the repeat guard must
# not move when an admin changes demo time.
_recent: dict[tuple[str, str], datetime] = {}
_recent_lock = threading.Lock()


@dataclass
class CollectResult:
    id: str  # lets screens ignore the realtime copy of a result they already showed
    status: str  # collected | not_ready | nothing_to_collect | unknown_card | ignored
    station: str
    reader_id: str
    code: str
    name: str | None = None
    roll_no: str | None = None
    summary: str | None = None
    lines: list[str] = field(default_factory=list)
    at: datetime | None = None


def normalise(code: str) -> str:
    """What a scanner typed, as stored: no surrounding space or control characters, upper case."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", code).strip().upper()
    if not cleaned:
        raise ApiError(422, "empty_code", "Nothing was scanned. Scan the barcode on the student's ID card.")
    if len(cleaned) > MAX_CODE_LENGTH:
        raise ApiError(422, "bad_code", "That doesn't look like an ID card barcode. Scan the card again.")
    return cleaned


def reader_for(station: str) -> str:
    """The reader id for a station's desk, from the `readers` setting."""
    for reader in settings_service.get("readers"):
        if reader.get("station") == station:
            return reader["id"]
    return f"{station}-desk"


def _is_repeat(reader_id: str, code: str) -> bool:
    """True if this card was scanned on this reader within the last 3 seconds."""
    now = clock.real_now()
    with _recent_lock:
        for key, seen in list(_recent.items()):
            if now - seen > REPEAT_WINDOW:
                del _recent[key]
        if (reader_id, code) in _recent:
            return True
        _recent[(reader_id, code)] = now
        return False


def _canteen(session: Session, student: Student, result: CollectResult) -> None:
    """All of the student's ready orders for today become collected."""
    start = datetime.combine(clock.today(), datetime.min.time(), tzinfo=IST)
    orders = session.exec(
        select(Order).where(
            Order.student_id == student.id,
            col(Order.status).in_(canteen_service.ACTIVE),
            Order.pickup_time >= start,
            Order.pickup_time < start + timedelta(days=1),
        ).order_by(Order.token_no)
    ).all()
    for order in [o for o in orders if o.status == "ready"]:
        try:
            canteen_service.set_status(session, order.id, "collected")
        except ApiError:
            continue  # someone else changed it a moment ago (e.g. "Mark collected")
        items = ", ".join(f"{i['name']} × {i['qty']}" for i in canteen_service.order_view(session, order)["items"])
        result.lines.append(f"Token {order.token_no}: {items}")
    if result.lines:
        result.status = "collected"
        return
    waiting = [o for o in orders if o.status in canteen_service.TO_COOK]
    if waiting:
        result.status = "not_ready"
        result.lines = [
            f"Token {o.token_no} is {'being prepared' if o.status == 'preparing' else 'in the kitchen queue'}"
            for o in waiting
        ]
        return
    result.status = "nothing_to_collect"


def _print(session: Session, student: Student, result: CollectResult) -> None:
    """All of the student's ready print jobs become collected, and their files are deleted."""
    jobs = session.exec(
        select(PrintJob).where(PrintJob.student_id == student.id, col(PrintJob.status).in_(print_service.ACTIVE))
        .order_by(PrintJob.id)
    ).all()
    for job in [j for j in jobs if j.status == "ready"]:
        try:
            print_service.set_status(session, job.id, "collected")
        except ApiError:
            continue
        result.lines.append(f"{job.code}: {job.original_filename} ({job.pages} pages × {job.copies})")
    if result.lines:
        result.status = "collected"
        return
    waiting = [j for j in jobs if j.status in print_service.IN_QUEUE]
    if waiting:
        result.status = "not_ready"
        result.lines = [
            f"{j.code} is {'printing' if j.status == 'printing' else 'in the print queue'}" for j in waiting
        ]
        return
    result.status = "nothing_to_collect"


def collect(session: Session, station: str, code: str) -> CollectResult:
    """Handle one scan at a station's desk and hand over whatever is ready for that student."""
    if station not in STATIONS:
        raise ApiError(400, "bad_station", "Scanning only works at the canteen and the print shop.")
    code = normalise(code)
    reader_id = reader_for(station)
    result = CollectResult(id=uuid.uuid4().hex, status="unknown_card", station=station, reader_id=reader_id,
                           code=code, at=clock.local_now())

    if _is_repeat(reader_id, code):
        # Same card again within 3 seconds: a double scan, not a new request. Logged, not acted on.
        result.status = "ignored"
        session.add(TapLog(reader_id=reader_id, card_uid=code, result="ignored", created_at=clock.to_utc(clock.now())))
        session.commit()
        return result

    student = session.exec(select(Student).where(Student.card_uid == code)).first()
    if student is not None:
        result.name, result.roll_no = student.name, student.roll_no
        (_canteen if station == "canteen" else _print)(session, student, result)
    result.summary = "; ".join(result.lines) or None

    session.add(TapLog(
        reader_id=reader_id, card_uid=code, student_id=student.id if student else None,
        result=result.status, created_at=clock.to_utc(clock.now()),
    ))
    session.commit()
    # Every staff screen at this station shows the result; the student's own screens
    # update through the order/print events sent when items were collected.
    hub.publish("tap.result", result_view(result), roles=(station,))
    return result


def result_view(result: CollectResult) -> dict:
    return {
        "id": result.id,
        "status": result.status,
        "station": result.station,
        "reader_id": result.reader_id,
        "name": result.name,
        "roll_no": result.roll_no,
        "summary": result.summary,
        "lines": result.lines,
        "at": result.at,
    }


def candidates(session: Session, station: str) -> list[dict]:
    """For the demo "Simulate scan" picker: every student and what's waiting for them at this station."""
    students = session.exec(select(Student).order_by(Student.roll_no)).all()
    start = datetime.combine(clock.today(), datetime.min.time(), tzinfo=IST)
    if station == "canteen":
        rows = session.exec(
            select(Order.student_id, Order.status).where(
                col(Order.status).in_(canteen_service.ACTIVE),
                Order.pickup_time >= start, Order.pickup_time < start + timedelta(days=1),
            )
        ).all()
    else:
        rows = session.exec(
            select(PrintJob.student_id, PrintJob.status).where(col(PrintJob.status).in_(print_service.ACTIVE))
        ).all()
    ready: dict[int, int] = {}
    waiting: dict[int, int] = {}
    for student_id, status in rows:
        bucket = ready if status == "ready" else waiting
        bucket[student_id] = bucket.get(student_id, 0) + 1
    out = [
        {"id": s.id, "name": s.name, "roll_no": s.roll_no, "has_card": s.card_uid is not None,
         "ready": ready.get(s.id, 0), "waiting": waiting.get(s.id, 0)}
        for s in students
    ]
    return sorted(out, key=lambda c: (-c["ready"], -c["waiting"], c["roll_no"]))


def simulate(session: Session, station: str, student_id: int) -> CollectResult:
    """Demo only: scan the chosen student's card, through exactly the same path as a real scan."""
    if not settings_service.get("demo_mode"):
        raise ApiError(403, "demo_off", "Simulated scans are only available in demo mode.")
    student = session.get(Student, student_id)
    if student is None:
        raise ApiError(404, "student_not_found", "That student doesn't exist.")
    if student.card_uid is None:
        raise ApiError(409, "no_card", f"{student.name} has no ID card linked yet.")
    return collect(session, station, student.card_uid)
