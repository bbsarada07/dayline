"""Collect by barcode at the canteen counter and the print shop desk (addendum E)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth import require_roles
from app.db import get_session
from app.models import Staff
from app.services import collect_service, settings_service

router = APIRouter(prefix="/collect", tags=["collect"])

# The station is the staff member's role: canteen staff collect food, print staff printouts.
desk_staff = require_roles(*collect_service.STATIONS)


class ScanIn(BaseModel):
    code: str = Field(min_length=1, max_length=200, description="What the barcode scanner typed")


class SimulateIn(BaseModel):
    student_id: int


@router.post("/scan")
def scan(body: ScanIn, staff: Staff = Depends(desk_staff), session: Session = Depends(get_session)) -> dict:
    """A barcode scan at this desk: hand over everything ready for that student here."""
    return collect_service.result_view(collect_service.collect(session, staff.role, body.code))


@router.post("/simulate")
def simulate(body: SimulateIn, staff: Staff = Depends(desk_staff), session: Session = Depends(get_session)) -> dict:
    """Demo mode only: scan a chosen student's card without a scanner. Same path as a real scan."""
    return collect_service.result_view(collect_service.simulate(session, staff.role, body.student_id))


@router.get("/candidates")
def candidates(staff: Staff = Depends(desk_staff), session: Session = Depends(get_session)) -> dict:
    """Demo mode: students to pick for "Simulate scan", with what's waiting for each here."""
    demo = bool(settings_service.get("demo_mode"))
    return {"demo_mode": demo, "students": collect_service.candidates(session, staff.role) if demo else []}
