"""Running one student message through the agents and keeping the conversation.

Shared by the chat endpoint (typed or spoken in the app) and by Omi (spoken to the
wearable), so both get the same engine, guards, trace and history.
"""

import json
from typing import Any

from sqlmodel import Session, col, select

from app import clock
from app.db import engine
from app.models import AgentMessage, Student

from . import llm, runs
from .orchestrator import Engine, Outcome
from .runs import Emit

HISTORY_TURNS = 10


def history(session: Session, student_id: int, conversation_id: str, limit: int) -> list[AgentMessage]:
    """This student's messages in one conversation, oldest first (at most `limit`, the newest ones)."""
    rows = session.exec(
        select(AgentMessage)
        .where(AgentMessage.student_id == student_id, AgentMessage.conversation_id == conversation_id)
        .order_by(col(AgentMessage.id).desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def store(session: Session, student_id: int, conversation_id: str, message: str, outcome: Outcome,
          events: list[dict], *, upload_id: str | None = None, source: str | None = None) -> None:
    """Save the student's message and the reply (with its trace) to the conversation."""
    now = clock.local_now()
    meta = {k: v for k, v in (("upload_id", upload_id), ("source", source)) if v}
    session.add(AgentMessage(student_id=student_id, conversation_id=conversation_id, role="user", content=message,
                             trace_json=json.dumps(meta) if meta else None, created_at=now))
    session.add(AgentMessage(
        student_id=student_id, conversation_id=conversation_id, role="assistant", content=outcome.reply,
        trace_json=json.dumps({"events": events, "proposals": outcome.proposals, "agents": outcome.agents,
                               "refused": outcome.refused, **({"source": source} if source else {})},
                              default=str, ensure_ascii=False),
        created_at=now,
    ))
    session.commit()


def run_message(student_id: int, conversation_id: str, message: str, emit: Emit, *, upload_id: str | None = None,
                voice: bool = False, source: str | None = None) -> tuple[Outcome, list[dict[str, Any]]]:
    """Run one message for this student (in the calling thread) and store it. Returns (outcome, trace events)."""
    run = runs.start(student_id, conversation_id, upload_id, emit)
    try:
        emit("run", {"conversation_id": conversation_id, "mode": llm.mode()})
        with Session(engine) as db:
            turns = [{"role": m.role, "content": m.content}
                     for m in history(db, student_id, conversation_id, HISTORY_TURNS)]
            outcome = Engine().handle(db, db.get(Student, student_id), run, message, turns, voice)
            store(db, student_id, conversation_id, message, outcome, run.events, upload_id=upload_id, source=source)
        return outcome, run.events
    finally:
        runs.finish(run)
