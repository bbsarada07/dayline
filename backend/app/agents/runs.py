"""Agent runs and run tokens (addendum H).

Each chat message starts a run with a random, short-lived run token. The server maps
the token to the student and the conversation; the model never sees the student id,
roll number, name or the token. Tool calls are always executed for the run's student.
"""

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from app import clock

TOKEN_TTL = timedelta(minutes=5)

Emit = Callable[[str, dict[str, Any]], None]


@dataclass
class Run:
    id: str
    token: str
    student_id: int
    conversation_id: str
    upload_id: str | None
    expires_at: datetime
    emit: Emit
    events: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    agents_used: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def send(self, type_: str, payload: dict[str, Any]) -> None:
        """Record a trace event (saved with the message) and stream it to the browser."""
        event = {"type": type_, **payload}
        self.events.append(event)
        self.emit(type_, payload)

    def note(self, text: str) -> None:
        """A quiet note in the trace (e.g. the offline router answered instead of Lyzr)."""
        if text not in self.notes:
            self.notes.append(text)
            self.send("note", {"text": text})


_runs: dict[str, Run] = {}
_lock = threading.Lock()


def start(student_id: int, conversation_id: str, upload_id: str | None, emit: Emit) -> Run:
    """Create a run and its token. Expired runs are dropped."""
    now = clock.real_now()
    run = Run(
        id=secrets.token_hex(8), token=secrets.token_urlsafe(24), student_id=student_id,
        conversation_id=conversation_id, upload_id=upload_id, expires_at=now + TOKEN_TTL, emit=emit,
    )
    with _lock:
        for token in [t for t, r in _runs.items() if r.expires_at <= now]:
            del _runs[token]
        _runs[run.token] = run
    return run


def by_token(token: str | None) -> Run | None:
    """The live run for a token, or None if unknown or expired."""
    if not token:
        return None
    with _lock:
        run = _runs.get(token)
    if run is None or run.expires_at <= clock.real_now():
        return None
    return run


def finish(run: Run) -> None:
    """End a run: its token stops working."""
    with _lock:
        _runs.pop(run.token, None)
