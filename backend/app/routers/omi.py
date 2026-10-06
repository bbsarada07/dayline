"""Omi: the two webhooks Omi calls, and connecting a student's Omi account (addendum I).

The webhooks need no login: the token in the URL and the uid Omi adds identify the student.
They always answer quickly with {"status": ...}, never with a "message" key (Omi would turn that
into a notification, limited to one every 30 seconds); replies go through the notification API.
"""

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth import require_student
from app.config import settings
from app.db import engine, get_session
from app.models import Student
from app.services import omi_service

router = APIRouter(prefix="/omi", tags=["omi"])


async def _body(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return None


def _source(simulator: str | None) -> str:
    return "simulator" if simulator else "omi"


@router.post("/transcript")
async def transcript_webhook(
    request: Request,
    t: str | None = Query(default=None, description="The student's webhook token (part of the URL)"),
    uid: str | None = Query(default=None, description="Added by Omi: the speaker's Omi user id"),
    x_dayline_simulator: str | None = Header(default=None),
) -> dict:
    """Omi's real-time transcript webhook: listens for "Hey Dayline" and runs the request after it."""
    body = await _body(request)

    def handle() -> dict:
        with Session(engine) as session:
            return omi_service.receive_transcript(session, t, uid, body, _source(x_dayline_simulator))

    return await run_in_threadpool(handle)


@router.post("/memory")
async def memory_webhook(
    request: Request,
    t: str | None = Query(default=None, description="The student's webhook token (part of the URL)"),
    uid: str | None = Query(default=None, description="Added by Omi: the speaker's Omi user id"),
    x_dayline_simulator: str | None = Header(default=None),
) -> dict:
    """Omi's memory-creation webhook: keeps up to five facts from a finished conversation."""
    body = await _body(request)

    def handle() -> dict:
        with Session(engine) as session:
            return omi_service.receive_memory(session, t, uid, body, _source(x_dayline_simulator))

    return await run_in_threadpool(handle)


def _base_url(request: Request) -> str:
    return settings.public_base_url or str(request.base_url).rstrip("/")


@router.get("/status")
def omi_status(request: Request, student: Student = Depends(require_student),
               session: Session = Depends(get_session)) -> dict:
    """The student's Omi connection: their id, the two webhook URLs to paste into Omi, and setup state."""
    return omi_service.status(session, student, _base_url(request))


class ConnectIn(BaseModel):
    uid: str = Field(min_length=1, max_length=128, description="The Omi user id from Omi's Developer Settings")


@router.put("/connect")
def connect(body: ConnectIn, request: Request, student: Student = Depends(require_student),
            session: Session = Depends(get_session)) -> dict:
    """Connect (or change) the student's Omi account."""
    return omi_service.status(session, omi_service.connect(session, student, body.uid), _base_url(request))


@router.delete("/connect")
def disconnect(request: Request, student: Student = Depends(require_student),
               session: Session = Depends(get_session)) -> dict:
    """Disconnect Omi: its webhooks stop working for this student."""
    return omi_service.status(session, omi_service.disconnect(session, student), _base_url(request))


@router.get("/activity")
def activity(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """The student's recent Omi webhook calls and replies (what happened, never what was said)."""
    return {"entries": [
        {"id": e.id, "kind": e.kind, "source": e.source, "outcome": e.outcome, "detail": e.detail,
         "segments": e.segments, "words": e.words, "ms": e.ms, "created_at": e.created_at}
        for e in omi_service.activity(session, student.id)
    ]}
