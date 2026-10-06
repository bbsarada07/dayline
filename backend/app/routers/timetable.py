"""The logged-in student's timetable for today."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app import clock
from app.auth import require_student
from app.db import get_session
from app.models import Student
from app.services import timetable_service

router = APIRouter(prefix="/timetable", tags=["timetable"])


@router.get("/today")
def today(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Today's classes, breaks and free time for the student's section."""
    return {
        "date": clock.today().isoformat(),
        "now": clock.local_now().isoformat(),
        "items": timetable_service.today_schedule(session, student.section),
    }


@router.get("/next")
def next_class(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """The next class today that hasn't started yet (null if none)."""
    return {"next": timetable_service.next_class(session, student.section)}


@router.get("/free-slots")
def free_slots(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Today's breaks and free gaps between classes."""
    return {"items": timetable_service.free_slots(session, student.section)}
