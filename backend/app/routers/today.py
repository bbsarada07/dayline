"""The Today screen in one call, plus the public clock."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app import clock
from app.config import settings
from app.auth import require_student
from app.db import get_session
from app.models import Student
from app.services import canteen_service, print_service, timetable_service

router = APIRouter(tags=["today"])


@router.get("/today")
def today(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Today's schedule with the current and next class, plus print jobs and canteen orders to pin on the line.

    Nudges are added to this payload in a later phase.
    """
    items = timetable_service.today_schedule(session, student.section)
    return {
        "date": clock.today().isoformat(),
        "now": clock.local_now().isoformat(),
        "items": items,
        "current": timetable_service.current_item(items),
        "next_class": next((i for i in items if i.kind == "class" and i.status == "upcoming"), None),
        "print_jobs": [print_service.job_view(j) for j in print_service.jobs_for_today(session, student.id)],
        "orders": canteen_service.orders_for_today(session, student.id),
    }


@router.get("/clock")
def get_clock() -> dict:
    """Current app time, whether demo time is active, and whether this is a demo deployment. No login needed."""
    return {"now": clock.local_now().isoformat(), "demo": clock.is_overridden(), "demo_mode": settings.demo_mode}
