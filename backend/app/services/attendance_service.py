"""Attendance maths and per-student attendance queries.

All maths is done in integers so results are exact. With threshold t (as a
fraction):
  can miss  M = floor(attended / t - held)
  must attend N = ceil((t * held - attended) / (1 - t))
"""

from dataclasses import dataclass

from sqlmodel import Session, select

from app.errors import ApiError
from app.models import Attendance, Subject
from app.services import settings_service


@dataclass
class Standing:
    held: int
    attended: int
    percentage: float | None  # rounded down to 1 decimal; None when nothing held
    threshold: int
    status: str  # ok | below | no_classes
    can_miss: int  # M; 0 when below
    must_attend: int | None  # N; 0 when ok; None when the threshold can't be reached
    statement: str


def _classes(n: int) -> str:
    return "class" if n == 1 else "classes"


def standing(held: int, attended: int, threshold: int) -> Standing:
    """Compute percentage and the plain-language statement for one subject."""
    if held < 0 or attended < 0 or attended > held:
        raise ValueError("attended must be between 0 and held")
    if not 1 <= threshold <= 100:
        raise ValueError("threshold must be between 1 and 100")

    if held == 0:
        return Standing(0, 0, None, threshold, "no_classes", 0, 0, "No classes held yet.")

    percentage = (attended * 1000 // held) / 10
    if attended * 100 >= threshold * held:
        can_miss = (attended * 100 - threshold * held) // threshold
        statement = f"You can miss {can_miss} more {_classes(can_miss)} and stay at {threshold}%"
        return Standing(held, attended, percentage, threshold, "ok", can_miss, 0, statement)

    if threshold == 100:
        statement = "You can no longer reach 100% in this subject"
        return Standing(held, attended, percentage, threshold, "below", 0, None, statement)

    numerator = threshold * held - 100 * attended
    must_attend = -(-numerator // (100 - threshold))
    if must_attend == 1:
        statement = f"Attend the next class to reach {threshold}%"
    else:
        statement = f"Attend the next {must_attend} classes to reach {threshold}%"
    return Standing(held, attended, percentage, threshold, "below", 0, must_attend, statement)


def threshold() -> int:
    return int(settings_service.get("attendance_threshold"))


@dataclass
class SubjectAttendance:
    subject_id: int
    code: str
    name: str
    short_name: str | None
    kind: str
    standing: Standing


def _sort_key(item: SubjectAttendance) -> tuple:
    s = item.standing
    order = {"below": 0, "ok": 1, "no_classes": 2}[s.status]
    return (order, s.percentage if s.percentage is not None else 101.0, item.name)


def list_for_student(session: Session, student_id: int) -> list[SubjectAttendance]:
    """Every subject's attendance for one student, below-threshold first."""
    limit = threshold()
    rows = session.exec(
        select(Attendance, Subject)
        .join(Subject, Subject.id == Attendance.subject_id)
        .where(Attendance.student_id == student_id)
    ).all()
    items = [
        SubjectAttendance(
            subject.id, subject.code, subject.name, subject.short_name, subject.kind,
            standing(att.classes_held, att.classes_attended, limit),
        )
        for att, subject in rows
    ]
    return sorted(items, key=_sort_key)


@dataclass
class WhatIf:
    subject_id: int
    subject_name: str
    miss: int
    current: Standing
    after: Standing


def what_if(session: Session, student_id: int, subject_id: int, miss: int) -> WhatIf:
    """Attendance after missing the next `miss` classes of one subject."""
    row = session.exec(
        select(Attendance, Subject)
        .join(Subject, Subject.id == Attendance.subject_id)
        .where(Attendance.student_id == student_id, Attendance.subject_id == subject_id)
    ).first()
    if row is None:
        raise ApiError(404, "subject_not_found", "You don't have attendance for that subject.")
    att, subject = row
    limit = threshold()
    return WhatIf(
        subject.id,
        subject.short_name or subject.name,
        miss,
        standing(att.classes_held, att.classes_attended, limit),
        standing(att.classes_held + miss, att.classes_attended, limit),
    )
