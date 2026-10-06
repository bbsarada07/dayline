"""Print jobs: upload, quote, pay, queue, status, file privacy (spec 5.3).

REST routes and (later) agent tools both call these functions; there is no
print logic anywhere else.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader
from sqlalchemy import update
from sqlmodel import Session, col, select

from app import clock
from app.config import IST, settings
from app.errors import ApiError
from app.events import hub
from app.models import PrintJob, PrintUpload, Student
from app.services import memory_service, payments, settings_service, timetable_service

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_COPIES = 20
PDF_SIGNATURE = b"%PDF-"
ACTIVE = ("queued", "printing", "ready")
IN_QUEUE = ("queued", "printing")
EXPIRE_AFTER = timedelta(hours=24)
URGENT_WITHIN = timedelta(minutes=15)
DEFAULT_LEAD = timedelta(minutes=10)  # ready this long before the next class
NO_CLASS_DEFAULT = timedelta(hours=1)
MAX_DEADLINE_AHEAD = timedelta(days=7)

ALLOWED_STAFF_MOVES = {"queued": "printing", "printing": "ready", "ready": "collected"}


# --- helpers ------------------------------------------------------------------

def _store(value: datetime) -> datetime:
    return clock.to_utc(value)


def _load(value: datetime) -> datetime:
    """Stored (aware UTC) -> college time for the API."""
    return value.astimezone(IST)


def short_time(value: datetime) -> str:
    """"2:00" in college time, the way the spec's copy writes times."""
    local = value.astimezone(IST)
    return f"{local.hour % 12 or 12}:{local.minute:02d}"


def _when(value: datetime) -> str:
    """"1:50" today, "Tue 1:50" on another day."""
    local = value.astimezone(IST)
    if local.date() == clock.today():
        return short_time(local)
    return f"{local.strftime('%a')} {short_time(local)}"


def _upload_dir() -> Path:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir.resolve()


def delete_file(stored_path: str | None) -> None:
    """Remove a stored upload. Refuses paths outside the upload folder."""
    if not stored_path:
        return
    path = Path(stored_path).resolve()
    if path.is_relative_to(_upload_dir()):
        path.unlink(missing_ok=True)


def _clean_filename(name: str | None) -> str:
    base = (name or "document.pdf").replace("\\", "/").split("/")[-1].strip() or "document.pdf"
    return base[:120]


# --- upload -------------------------------------------------------------------

def save_upload(session: Session, student_id: int, filename: str | None, stream: BinaryIO) -> PrintUpload:
    """Validate and store an uploaded PDF. Checks the file signature, not the extension."""
    head = stream.read(len(PDF_SIGNATURE))
    if head != PDF_SIGNATURE:
        raise ApiError(415, "not_a_pdf", "That file isn't a PDF. Save or export it as PDF, then upload it again.")

    upload_id = secrets.token_urlsafe(16)
    path = _upload_dir() / f"{secrets.token_hex(16)}.pdf"
    size = len(head)
    try:
        with path.open("wb") as out:
            out.write(head)
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ApiError(413, "file_too_large", "That PDF is bigger than 20 MB. Compress it or split it, then try again.")
                out.write(chunk)
        pages = _count_pages(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    upload = PrintUpload(
        id=upload_id, student_id=student_id, original_filename=_clean_filename(filename),
        stored_path=str(path), pages=pages, size_bytes=size, created_at=_store(clock.now()),
    )
    session.add(upload)
    session.commit()
    session.refresh(upload)
    return upload


def _count_pages(path: Path) -> int:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ApiError(422, "pdf_locked", "This PDF is password-protected. Remove the password and upload it again.")
        pages = len(reader.pages)
    except ApiError:
        raise
    except Exception:
        raise ApiError(422, "pdf_unreadable", "This PDF couldn't be read. It may be damaged. Export it again and retry.")
    if pages < 1:
        raise ApiError(422, "pdf_empty", "This PDF has no pages.")
    return pages


def get_upload(session: Session, student_id: int, upload_id: str) -> PrintUpload:
    upload = session.get(PrintUpload, upload_id)
    if upload is None or upload.student_id != student_id:
        raise ApiError(404, "upload_not_found", "That upload has expired or doesn't exist. Upload the PDF again.")
    return upload


# --- quote --------------------------------------------------------------------

def rate_for(color: bool, double_sided: bool) -> int:
    """Paise per page for the chosen options (from settings)."""
    rates = settings_service.get("print_rates")
    key = f"{'colour' if color else 'bw'}_{'double' if double_sided else 'single'}"
    return int(rates[key])


@dataclass
class DefaultDeadline:
    deadline: datetime
    reason: str  # plain sentence shown under the deadline
    target: str | None  # "your 2:00 lab", used in the late warning


def default_deadline(session: Session, student: Student) -> DefaultDeadline:
    """Start of the next class today minus 10 minutes, else one hour from now."""
    now = clock.local_now()
    upcoming = timetable_service.next_class(session, student.section)
    if upcoming is None:
        return DefaultDeadline(now + NO_CLASS_DEFAULT, "No more classes today, so it's set to an hour from now.", None)
    kind = "lab" if upcoming.subject_kind == "lab" else "class"
    deadline = max(upcoming.start - DEFAULT_LEAD, now)
    name = upcoming.label if upcoming.label.lower().endswith(kind) else f"{upcoming.label} {kind}"  # no "DBMS lab lab"
    reason = f"Your {name} starts at {short_time(upcoming.start)}, so it's set 10 minutes before."
    return DefaultDeadline(deadline, reason, f"your {short_time(upcoming.start)} {kind}")


def _queue_rows(session: Session) -> list[PrintJob]:
    """Jobs waiting for the printer, in the order the shop prints them:
    whatever is printing first, then queued jobs by deadline, then by time created."""
    rows = session.exec(select(PrintJob).where(col(PrintJob.status).in_(IN_QUEUE))).all()
    return sorted(rows, key=lambda j: (j.status != "printing", j.deadline, j.created_at, j.id))


def estimate_ready(session: Session, deadline: datetime, printed_pages: int, exclude_id: int | None = None) -> datetime:
    """now + (pages ahead with an earlier-or-equal deadline + these pages) x seconds-per-page + 60 s per job.

    A job already printing counts as ahead whatever its deadline.
    """
    seconds_per_page = int(settings_service.get("print_seconds_per_page"))
    limit = _store(deadline)
    ahead = [j for j in _queue_rows(session)
             if j.id != exclude_id and (j.status == "printing" or j.deadline <= limit)]
    pages_ahead = sum(j.pages * j.copies for j in ahead)
    jobs = len(ahead) + 1
    return clock.local_now() + timedelta(seconds=(pages_ahead + printed_pages) * seconds_per_page + 60 * jobs)


@dataclass
class Quote:
    upload_id: str
    original_filename: str
    pages: int
    copies: int
    color: bool
    double_sided: bool
    rate: int  # paise per page
    cost: int  # paise
    deadline: datetime
    deadline_is_default: bool
    deadline_reason: str | None
    est_ready_at: datetime
    jobs_ahead: int
    warning: str | None


def _validate_options(copies: int) -> None:
    if not 1 <= copies <= MAX_COPIES:
        raise ApiError(422, "bad_copies", f"Choose between 1 and {MAX_COPIES} copies.")


def _validate_deadline(deadline: datetime) -> datetime:
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=IST)
    now = clock.local_now()
    if deadline <= now:
        raise ApiError(422, "deadline_past", "That deadline has already passed. Pick a later time.")
    if deadline > now + MAX_DEADLINE_AHEAD:
        raise ApiError(422, "deadline_too_far", "Pick a deadline within the next 7 days.")
    return deadline.astimezone(IST)


def quote(
    session: Session, student: Student, upload_id: str, copies: int, color: bool, double_sided: bool,
    deadline: datetime | None = None,
) -> Quote:
    """Cost, deadline and estimated ready time for a job, without creating it."""
    _validate_options(copies)
    upload = get_upload(session, student.id, upload_id)
    default = default_deadline(session, student)
    chosen = _validate_deadline(deadline) if deadline is not None else default.deadline
    is_default = deadline is None
    printed = upload.pages * copies
    est = estimate_ready(session, chosen, printed)
    ahead = len([j for j in _queue_rows(session) if j.status == "printing" or j.deadline <= _store(chosen)])

    warning = None
    if est > chosen:
        target = default.target if is_default and default.target else None
        warning = (f"This may not be ready before {target}." if target
                   else f"This may not be ready by {_when(chosen)}.")
    rate = rate_for(color, double_sided)
    return Quote(
        upload.id, upload.original_filename, upload.pages, copies, color, double_sided, rate,
        upload.pages * copies * rate, chosen, is_default, default.reason if is_default else None,
        est, ahead, warning,
    )


# --- jobs -----------------------------------------------------------------------

def job_view(job: PrintJob, student: Student | None = None) -> dict:
    """API shape of a job. The stored file path never leaves the server."""
    view = {
        "id": job.id,
        "code": job.code,
        "original_filename": job.original_filename,
        "pages": job.pages,
        "copies": job.copies,
        "color": job.color,
        "double_sided": job.double_sided,
        "cost": job.cost,
        "deadline": _load(job.deadline),
        "est_ready_at": _load(job.est_ready_at),
        "status": job.status,
        "payment_status": job.payment_status,
        "created_at": _load(job.created_at),
        "ready_at": _load(job.ready_at) if job.ready_at else None,
        "collected_at": _load(job.collected_at) if job.collected_at else None,
        "has_file": job.stored_path is not None,
    }
    if student is not None:
        view |= {"student_name": student.name, "roll_no": student.roll_no}
    return view


def _publish(session: Session, job: PrintJob, event: str) -> None:
    student = session.get(Student, job.student_id)
    hub.publish(event, job_view(job, student), student_id=job.student_id, roles=("print",))


def recompute_estimates(session: Session) -> None:
    """Re-estimate ready times for queued jobs after the queue changed."""
    seconds_per_page = int(settings_service.get("print_seconds_per_page"))
    now = clock.local_now()
    pages = 0
    changed = []
    for position, job in enumerate(_queue_rows(session), start=1):
        pages += job.pages * job.copies
        if job.status != "queued":
            continue
        est = _store(now + timedelta(seconds=pages * seconds_per_page + 60 * position))
        if abs((est - job.est_ready_at).total_seconds()) >= 30:
            job.est_ready_at = est
            session.add(job)
            changed.append(job)
    session.commit()
    for job in changed:
        hub.publish("print.updated", job_view(job), student_id=job.student_id)


def create_job(
    session: Session, student: Student, upload_id: str, copies: int, color: bool, double_sided: bool,
    deadline: datetime | None = None,
) -> PrintJob:
    """Charge through the payment provider, then queue the job. Called only when the student confirms."""
    q = quote(session, student, upload_id, copies, color, double_sided, deadline)
    upload = get_upload(session, student.id, upload_id)
    payment = payments.provider().charge(q.cost, f"print:{upload.id}")

    job = PrintJob(
        student_id=student.id, code=f"tmp-{secrets.token_hex(6)}", original_filename=upload.original_filename,
        stored_path=upload.stored_path, pages=upload.pages, copies=copies, color=color,
        double_sided=double_sided, cost=q.cost, deadline=_store(q.deadline), est_ready_at=_store(q.est_ready_at),
        status="queued", payment_status=payment.status, created_at=_store(clock.now()),
    )
    session.add(job)
    session.delete(upload)  # the job owns the file now
    session.flush()
    job.code = f"P-{job.id:04d}"
    session.commit()
    session.refresh(job)
    _publish(session, job, "print.created")
    recompute_estimates(session)
    _remember_job(student, job)
    return job


def _remember_job(student: Student, job: PrintJob) -> None:
    """Shared memory: how this student prints, so "print it like last time" works."""
    copies = f"{job.copies} {'copy' if job.copies == 1 else 'copies'}"
    colour = "colour" if job.color else "black and white"
    sides = "double sided" if job.double_sided else "single sided"
    memory_service.remember_later(
        student.id, f"Printed {job.original_filename}: {copies}, {colour}, {sides}",
        kind="action", written_by="print", source_ref=f"print:{job.code}",
        data={"job_id": job.id, "copies": job.copies, "color": job.color,
              "double_sided": job.double_sided, "pages": job.pages},
    )


def _get_job(session: Session, job_id: int) -> PrintJob:
    job = session.get(PrintJob, job_id)
    if job is None:
        raise ApiError(404, "job_not_found", "That print job doesn't exist.")
    return job


def get_own_job(session: Session, student_id: int, job_id: int) -> PrintJob:
    job = session.get(PrintJob, job_id)
    if job is None or job.student_id != student_id:
        raise ApiError(404, "job_not_found", "That print job doesn't exist.")
    return job


def list_mine(session: Session, student_id: int) -> list[PrintJob]:
    """The student's jobs: active ones by deadline, then the 20 most recent others."""
    jobs = session.exec(select(PrintJob).where(PrintJob.student_id == student_id)).all()
    active = sorted((j for j in jobs if j.status in ACTIVE), key=lambda j: (j.deadline, j.id))
    done = sorted((j for j in jobs if j.status not in ACTIVE), key=lambda j: j.created_at, reverse=True)[:20]
    return active + done


def jobs_for_today(session: Session, student_id: int) -> list[PrintJob]:
    """Jobs to pin on the Today line: active ones, and ones collected today."""
    today = clock.today()
    return [
        j for j in list_mine(session, student_id)
        if j.status in ACTIVE or (j.status == "collected" and j.collected_at and _load(j.collected_at).date() == today)
    ]


FINAL = ("collected", "cancelled", "expired")


def _transition(session: Session, job: PrintJob, expected: str, new: str, conflict: str) -> str | None:
    """Move a job from `expected` to `new` only if nobody changed it in between.

    The UPDATE is conditional on the current status, so a student's cancel and a shop
    step that race can't both win (409 with `conflict`). Final states drop the file
    reference; the caller deletes the file after commit. Returns that file's path.
    """
    values: dict = {"status": new}
    stale_file = job.stored_path if new in FINAL else None
    if new in FINAL:
        values["stored_path"] = None
    if new == "ready":
        values["ready_at"] = _store(clock.now())
    if new == "collected":
        values["collected_at"] = _store(clock.now())
    result = session.execute(update(PrintJob).where(PrintJob.id == job.id, PrintJob.status == expected).values(**values))
    if result.rowcount != 1:
        session.rollback()
        raise ApiError(409, "status_changed", conflict)
    return stale_file


def cancel(session: Session, student_id: int, job_id: int) -> PrintJob:
    """Student cancels their own job. Only while it's still queued. The file is deleted."""
    job = get_own_job(session, student_id, job_id)
    if job.status != "queued":
        raise ApiError(409, "cannot_cancel", "This job can't be cancelled: the shop has already started it.")
    stale_file = _transition(session, job, "queued", "cancelled",
                             "This job can't be cancelled: the shop has already started it.")
    payments.provider().refund(f"print:{job.code}", job.cost)
    session.commit()
    delete_file(stale_file)
    session.refresh(job)
    _publish(session, job, "print.updated")
    recompute_estimates(session)
    return job


def set_status(session: Session, job_id: int, status: str) -> PrintJob:
    """Shop moves a job one step: queued -> printing -> ready -> collected (file deleted)."""
    job = _get_job(session, job_id)
    if ALLOWED_STAFF_MOVES.get(job.status) != status:
        raise ApiError(409, "bad_transition", f"{job.code} is {job.status}, so it can't be marked {status}. Refresh the queue.")
    stale_file = _transition(session, job, job.status, status,
                             f"{job.code} just changed (it may have been cancelled). Refresh the queue.")
    session.commit()
    delete_file(stale_file)
    session.refresh(job)
    _publish(session, job, "print.updated")
    recompute_estimates(session)
    return job


def shop_queue(session: Session) -> dict:
    """Staff view: jobs to print (printing first, then by deadline) and jobs waiting for pickup."""
    students = {s.id: s for s in session.exec(select(Student)).all()}
    to_print = [job_view(j, students.get(j.student_id)) for j in _queue_rows(session)]
    ready = session.exec(select(PrintJob).where(PrintJob.status == "ready")).all()
    ready_rows = [job_view(j, students.get(j.student_id))
                  for j in sorted(ready, key=lambda j: (j.deadline, j.created_at, j.id))]
    return {"to_print": to_print, "ready": ready_rows, "urgent_minutes": int(URGENT_WITHIN.total_seconds() // 60)}


def file_path_for(session: Session, job_id: int, *, student_id: int | None) -> tuple[Path, str]:
    """Path of a job's PDF. Students may only fetch their own; print staff any."""
    job = get_own_job(session, student_id, job_id) if student_id is not None else _get_job(session, job_id)
    if not job.stored_path or not Path(job.stored_path).is_file():
        raise ApiError(410, "file_gone", "This file has been deleted because the job is finished.")
    return Path(job.stored_path), job.original_filename


# --- maintenance (runs every minute) -----------------------------------------

def expire_old_jobs(session: Session) -> int:
    """Jobs not collected within 24 hours become `expired` and lose their file."""
    cutoff = _store(clock.now() - EXPIRE_AFTER)
    stale = session.exec(
        select(PrintJob).where(col(PrintJob.status).in_(ACTIVE), PrintJob.created_at < cutoff)
    ).all()
    expired: list[tuple[int, str | None]] = []
    for job in stale:
        stale_file = job.stored_path  # read first: the ORM update clears it on the object
        result = session.execute(
            update(PrintJob).where(PrintJob.id == job.id, PrintJob.status == job.status)
            .values(status="expired", stored_path=None)
        )
        if result.rowcount == 1:
            expired.append((job.id, stale_file))
    session.commit()
    for job_id, stale_file in expired:
        delete_file(stale_file)
        _publish(session, session.get(PrintJob, job_id), "print.updated")
    return len(expired)


def remove_stale_uploads(session: Session) -> int:
    """Uploads never turned into a job are deleted after 24 hours."""
    cutoff = _store(clock.now() - EXPIRE_AFTER)
    stale = session.exec(select(PrintUpload).where(PrintUpload.created_at < cutoff)).all()
    for upload in stale:
        delete_file(upload.stored_path)
        session.delete(upload)
    session.commit()
    return len(stale)
