"""Ask Dayline: one message in, a live trace and a reply out (Server-Sent Events).

The student comes from the session cookie. Each message starts a run with a short-lived
run token; the agents never see the student's id. Proposals come back as cards; nothing
is ordered or printed until the student confirms through the normal endpoints.
"""

import asyncio
import json
import logging
import re
import threading
import uuid
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app import clock
from app.auth import require_student
from app.config import settings
from app.db import engine, get_session
from app.errors import ApiError
from app.models import AgentMessage, Student
from app.services import print_service
from app.agents import llm, runs
from app.agents.orchestrator import Engine, Outcome

log = logging.getLogger("dayline.agents")

router = APIRouter(prefix="/agent", tags=["agent"])

RATE_LIMIT = 20  # messages per student per minute
RATE_WINDOW = timedelta(minutes=1)
HISTORY_LIMIT = 50
SAMPLE_PDF = Path(__file__).resolve().parent.parent / "assets" / "DBMS_lab_record.pdf"

_recent: dict[int, deque] = defaultdict(deque)
_rate_lock = threading.Lock()


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    upload_id: str | None = Field(default=None, max_length=64, description="A PDF uploaded with POST /api/print/uploads")
    voice: bool = Field(default=False, description="The message was spoken: keep the reply to two sentences")


def _rate_limit(student_id: int) -> None:
    now = clock.real_now()
    with _rate_lock:
        recent = _recent[student_id]
        while recent and now - recent[0] > RATE_WINDOW:
            recent.popleft()
        if len(recent) >= RATE_LIMIT:
            raise ApiError(429, "too_many_messages", "That's a lot of messages. Wait a minute and try again.")
        recent.append(now)


def _history(session: Session, student_id: int, conversation_id: str, limit: int) -> list[AgentMessage]:
    rows = session.exec(
        select(AgentMessage)
        .where(AgentMessage.student_id == student_id, AgentMessage.conversation_id == conversation_id)
        .order_by(col(AgentMessage.created_at).desc(), col(AgentMessage.id).desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def _store(session: Session, student_id: int, conversation_id: str, message: str, upload_id: str | None,
           outcome: Outcome, events: list[dict]) -> None:
    now = clock.local_now()
    session.add(AgentMessage(student_id=student_id, conversation_id=conversation_id, role="user", content=message,
                             trace_json=json.dumps({"upload_id": upload_id}) if upload_id else None, created_at=now))
    session.add(AgentMessage(
        student_id=student_id, conversation_id=conversation_id, role="assistant", content=outcome.reply,
        trace_json=json.dumps({"events": events, "proposals": outcome.proposals, "agents": outcome.agents,
                               "refused": outcome.refused}, default=str, ensure_ascii=False),
        created_at=now + timedelta(microseconds=1),
    ))
    session.commit()


def _sse(type_: str, payload: dict) -> str:
    return f"event: {type_}\ndata: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(body: ChatIn, student: Student = Depends(require_student),
               session: Session = Depends(get_session)) -> StreamingResponse:
    """Stream a run as Server-Sent Events: run, agent_started, tool_called, memory_read, memory_write,
    agent_finished, proposal, note, final (or error)."""
    _rate_limit(student.id)
    message = re.sub(r"\s+", " ", body.message).strip()
    if not message:
        raise ApiError(422, "empty_message", "Type what you'd like Dayline to do.")
    if body.upload_id:
        print_service.get_upload(session, student.id, body.upload_id)  # 404 unless it's this student's file
    conversation_id = body.conversation_id or uuid.uuid4().hex
    history = [{"role": m.role, "content": m.content} for m in _history(session, student.id, conversation_id, 10)]

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    student_id = student.id

    def emit(type_: str, payload: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (type_, payload))

    def work() -> None:
        run = runs.start(student_id, conversation_id, body.upload_id, emit)
        try:
            emit("run", {"conversation_id": conversation_id, "mode": llm.mode()})
            with Session(engine) as db:
                me = db.get(Student, student_id)
                outcome = Engine().handle(db, me, run, message, history, body.voice)
                _store(db, student_id, conversation_id, message, body.upload_id, outcome, run.events)
        except Exception:
            log.exception("Agent run failed")
            emit("error", {"message": "Something went wrong on our side. Try again, or use the screens directly."})
        finally:
            runs.finish(run)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=work, name="agent-run", daemon=True).start()

    async def stream():
        while (item := await queue.get()) is not None:
            yield _sse(*item)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/history")
def history(
    conversation_id: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$"),
    student: Student = Depends(require_student),
    session: Session = Depends(get_session),
) -> dict:
    """This student's messages in a conversation (default: their latest), oldest first."""
    if conversation_id is None:
        latest = session.exec(
            select(AgentMessage).where(AgentMessage.student_id == student.id)
            .order_by(col(AgentMessage.created_at).desc(), col(AgentMessage.id).desc()).limit(1)
        ).first()
        conversation_id = latest.conversation_id if latest else None
    rows = _history(session, student.id, conversation_id, HISTORY_LIMIT) if conversation_id else []
    return {
        "conversation_id": conversation_id,
        "mode": llm.mode(),
        "messages": [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at,
                      "trace": json.loads(m.trace_json) if m.trace_json else None} for m in rows],
    }


@router.post("/sample-file")
def sample_file(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Demo mode only: attach a sample 4-page PDF, so judges can try printing without a file of their own."""
    if not settings.demo_mode:
        raise ApiError(403, "demo_only", "The sample file is only available in the demo.")
    with SAMPLE_PDF.open("rb") as stream:
        upload = print_service.save_upload(session, student.id, SAMPLE_PDF.name, stream)
    return {"upload_id": upload.id, "original_filename": upload.original_filename, "pages": upload.pages}
