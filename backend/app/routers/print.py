"""Print: student upload/quote/pay/cancel, and the shop queue."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth import Principal, current_principal, require_roles, require_student
from app.db import get_session
from app.errors import ApiError
from app.models import Staff, Student
from app.services import print_service

router = APIRouter(prefix="/print", tags=["print"])


class JobOptions(BaseModel):
    upload_id: str = Field(min_length=1, max_length=64)
    copies: int = Field(ge=1, le=print_service.MAX_COPIES)
    color: bool = False
    double_sided: bool = False
    deadline: datetime | None = Field(default=None, description="College local time; default comes from the timetable")


class StatusIn(BaseModel):
    status: Literal["printing", "ready", "collected"]


@router.post("/uploads")
def upload(
    request: Request,
    file: UploadFile = File(...),
    student: Student = Depends(require_student),
    session: Session = Depends(get_session),
) -> dict:
    """Upload a PDF (max 20 MB). Returns an upload id and the page count."""
    length = int(request.headers.get("content-length") or 0)
    if length > print_service.MAX_UPLOAD_BYTES + 64 * 1024:
        raise ApiError(413, "file_too_large", "That PDF is bigger than 20 MB. Compress it or split it, then try again.")
    saved = print_service.save_upload(session, student.id, file.filename, file.file)
    return {"upload_id": saved.id, "original_filename": saved.original_filename, "pages": saved.pages}


@router.post("/quote")
def quote(
    body: JobOptions, student: Student = Depends(require_student), session: Session = Depends(get_session)
) -> print_service.Quote:
    """Cost, deadline and estimated ready time for the chosen options. Creates nothing."""
    return print_service.quote(session, student, body.upload_id, body.copies, body.color, body.double_sided, body.deadline)


@router.post("/jobs")
def create_job(body: JobOptions, student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Pay (demo payment) and queue the job. Only called when the student presses "Confirm and pay"."""
    job = print_service.create_job(
        session, student, body.upload_id, body.copies, body.color, body.double_sided, body.deadline
    )
    return print_service.job_view(job)


@router.get("/jobs/mine")
def my_jobs(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """The student's print jobs: active first (by deadline), then recent finished ones."""
    return {"jobs": [print_service.job_view(j) for j in print_service.list_mine(session, student.id)]}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Cancel the student's own job while it's still queued. The file is deleted."""
    return print_service.job_view(print_service.cancel(session, student.id, job_id))


@router.get("/queue")
def queue(_staff: Staff = Depends(require_roles("print")), session: Session = Depends(get_session)) -> dict:
    """Shop queue: jobs to print sorted by deadline, and jobs waiting for pickup."""
    return print_service.shop_queue(session)


@router.post("/jobs/{job_id}/status")
def set_status(
    job_id: int, body: StatusIn, _staff: Staff = Depends(require_roles("print")), session: Session = Depends(get_session)
) -> dict:
    """Shop moves a job one step forward: printing, ready, or collected (manual fallback)."""
    job = print_service.set_status(session, job_id, body.status)
    return print_service.job_view(job)


@router.get("/jobs/{job_id}/file")
def job_file(
    job_id: int, principal: Principal = Depends(current_principal), session: Session = Depends(get_session)
) -> FileResponse:
    """The job's PDF, shown inline. Only the owning student and print staff can fetch it."""
    if principal.role == "student":
        student_id = principal.id
    elif principal.role == "print":
        student_id = None
    else:
        raise ApiError(403, "forbidden", "Only the student who uploaded this file and the print shop can open it.")
    path, filename = print_service.file_path_for(session, job_id, student_id=student_id)
    return FileResponse(
        path, media_type="application/pdf", filename=filename, content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
