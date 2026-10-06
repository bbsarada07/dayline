"""The logged-in student's attendance and what-if."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth import require_student
from app.db import get_session
from app.models import Student
from app.services import attendance_service

router = APIRouter(prefix="/attendance", tags=["attendance"])


class WhatIfIn(BaseModel):
    subject_id: int
    miss: int = Field(ge=0, le=60, description="How many upcoming classes the student would miss")


@router.get("")
def attendance(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Per-subject attendance with the threshold statement, below-threshold first."""
    return {
        "threshold": attendance_service.threshold(),
        "subjects": attendance_service.list_for_student(session, student.id),
    }


@router.post("/what-if")
def what_if(
    body: WhatIfIn,
    student: Student = Depends(require_student),
    session: Session = Depends(get_session),
) -> attendance_service.WhatIf:
    """Attendance after missing the next `miss` classes of one subject."""
    return attendance_service.what_if(session, student.id, body.subject_id, body.miss)
