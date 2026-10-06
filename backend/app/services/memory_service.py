"""Shared agent memory (addendum G): one memory every agent reads and writes.

Every function takes the student id from the caller's session (never from a request
body or model output) and the backend filters every read, update and delete by it.
Memories hold short extracted facts and actions, never full transcripts.
"""

import logging
import re
import threading
import uuid
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from app import clock
from app.config import settings
from app.errors import ApiError
from app.events import hub
from app.services.memory_backends import Backend, QdrantBackend, Stored, TemporaryBackend

log = logging.getLogger("dayline.memory")

KINDS = ("preference", "action", "fact", "conversation", "instruction")
WRITERS = ("timetable", "print", "canteen", "orchestrator", "omi", "student")
MAX_TEXT = 500
LIST_LIMIT = 200
RECONNECT_EVERY = timedelta(minutes=2)

_lock = threading.Lock()
_backend: Backend | None = None
_reason: str | None = None  # why we're on the temporary store, if we are
_last_attempt: datetime | None = None
_writer = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory-write")
_pending: list[Future] = []
_last_ts = 0  # created_ts is strictly increasing, so "newest first" is exact even within a millisecond


@dataclass
class Memory:
    id: str
    kind: str
    text: str
    written_by: str
    source_ref: str | None
    created_at: str
    last_used_at: str | None
    data: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


# --- backend selection ---------------------------------------------------------------

def _qdrant_configured() -> bool:
    return bool(settings.qdrant_url and settings.qdrant_api_key)


def _connect() -> Backend:
    backend = QdrantBackend.cloud(settings.qdrant_url, settings.qdrant_api_key, settings.qdrant_collection, settings.memory_model)
    backend.ensure()
    return backend


def configure(backend: Backend | None, reason: str | None = None) -> None:
    """Use this backend from now on (tests pass an in-memory Qdrant). None = choose again."""
    global _backend, _reason, _last_attempt
    with _lock:
        _backend, _reason, _last_attempt = backend, reason, None


def backend() -> Backend:
    """The current backend, connecting to Qdrant on first use."""
    global _backend, _reason, _last_attempt
    with _lock:
        if _backend is None:
            _last_attempt = clock.real_now()
            if not _qdrant_configured():
                _backend, _reason = TemporaryBackend(), "Qdrant isn't configured (QDRANT_URL and QDRANT_API_KEY)."
            else:
                try:
                    _backend, _reason = _connect(), None
                except Exception as exc:  # unreachable, bad key, inference off...
                    log.warning("Qdrant unavailable, using the temporary store: %r", exc)
                    _backend, _reason = TemporaryBackend(), "Qdrant can't be reached right now."
        return _backend


def _fall_back(exc: Exception) -> Backend:
    """A Qdrant call failed mid-run: switch to the temporary store and say so."""
    global _backend, _reason, _last_attempt
    log.warning("Qdrant call failed, switching to the temporary store: %r", exc)
    with _lock:
        if _backend is None or _backend.name == "qdrant":
            _backend, _reason, _last_attempt = TemporaryBackend(), "Qdrant can't be reached right now.", clock.real_now()
        return _backend


def _run(operation: Callable[[Backend], Any]) -> Any:
    current = backend()
    try:
        return operation(current)
    except ApiError:
        raise
    except Exception as exc:
        if current.name != "qdrant":
            raise
        return operation(_fall_back(exc))


def reconnect_if_due() -> None:
    """Called every minute: if we fell back but Qdrant is configured, try it again."""
    global _backend, _reason, _last_attempt
    if not _qdrant_configured() or (_backend is not None and _backend.name == "qdrant"):
        return
    if _last_attempt and clock.real_now() - _last_attempt < RECONNECT_EVERY:
        return
    _last_attempt = clock.real_now()
    try:
        connected = _connect()
    except Exception:
        return
    with _lock:
        _backend, _reason = connected, None
    log.info("Reconnected to Qdrant.")


def status() -> dict[str, Any]:
    """Which store is in use, and why, for the Memory screen and /api/health."""
    current = backend()
    ok = True
    if current.name == "qdrant":
        try:
            current.ping()
        except Exception as exc:
            _fall_back(exc)
            ok = False
    current = backend()
    return {
        "backend": current.name,
        "ok": current.name == "qdrant" and ok,
        "configured": _qdrant_configured() or current.name == "qdrant",
        "collection": settings.qdrant_collection if current.name == "qdrant" else None,
        "notice": None if current.name == "qdrant" else (
            f"{_reason or 'Qdrant is unavailable.'} Memories are kept only until the server restarts."
        ),
    }


# --- views and helpers ------------------------------------------------------------------

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:MAX_TEXT]


def _view(row: Stored) -> Memory:
    p = row.payload
    return Memory(
        id=row.id, kind=p.get("kind", "fact"), text=p.get("text", ""), written_by=p.get("written_by", "student"),
        source_ref=p.get("source_ref"), created_at=p.get("created_at", ""), last_used_at=p.get("last_used_at"),
        data=p.get("data") or {}, score=row.score,
    )


def _changed(student_id: int, reason: str) -> None:
    hub.publish("memory.updated", {"reason": reason}, student_id=student_id)


def _mark_used(student_id: int, rows: list[Stored]) -> None:
    now = clock.local_now()
    payload = {"last_used_at": now.isoformat(), "last_used_ts": int(now.timestamp() * 1000)}
    _run(lambda b: b.mark_used(student_id, [r.id for r in rows], payload))


# --- the public operations -----------------------------------------------------------

def _next_ts(now: datetime) -> int:
    global _last_ts
    with _lock:
        _last_ts = max(int(now.timestamp() * 1000), _last_ts + 1)
        return _last_ts


def remember(
    student_id: int, text: str, *, kind: str, written_by: str,
    source_ref: str | None = None, data: dict[str, Any] | None = None, at: datetime | None = None,
) -> Memory:
    """Write one memory for this student. `at` backdates it (demo history only)."""
    if kind not in KINDS:
        raise ApiError(422, "bad_kind", f"Memory kind must be one of {', '.join(KINDS)}.")
    if written_by not in WRITERS:
        raise ApiError(422, "bad_writer", f"written_by must be one of {', '.join(WRITERS)}.")
    text = _clean(text)
    if not text:
        raise ApiError(422, "empty_memory", "There's nothing to remember. Say what Dayline should remember.")
    now = at or clock.local_now()
    payload = {
        "student_id": str(student_id), "kind": kind, "text": text, "written_by": written_by,
        "source_ref": source_ref, "created_at": now.isoformat(),
        "created_ts": int(at.timestamp() * 1000) if at else _next_ts(now),
        "last_used_at": None, "data": data or {},
    }
    point_id = str(uuid.uuid4())
    _run(lambda b: b.upsert(point_id, text, payload))
    _changed(student_id, "written")
    return _view(Stored(point_id, payload))


def remember_later(student_id: int, text: str, **kwargs: Any) -> None:
    """Write a memory in the background (after an order or print job): never slows or fails the action."""

    def write() -> None:
        try:
            remember(student_id, text, **kwargs)
        except Exception as exc:
            log.warning("Background memory write failed: %r", exc)

    future = _writer.submit(write)
    _pending.append(future)
    _pending[:] = [f for f in _pending if not f.done()]


def drain(timeout: float = 10) -> None:
    """Wait for background writes to finish (tests, reset)."""
    for future in list(_pending):
        future.result(timeout=timeout)
    _pending.clear()


def recall(student_id: int, query: str, limit: int = 5, *, mark: str = "all") -> list[Memory]:
    """The memories most relevant to `query`, best first.

    `mark` says which count as used: "all" (an agent used them as context) or "top"
    (the student searched the Memory screen; only the best match was really "used").
    """
    query = _clean(query)
    if not query:
        return []
    rows = _run(lambda b: b.search(student_id, query, limit))
    used = rows if mark == "all" else rows[:1]
    if used:
        _mark_used(student_id, used)
        _changed(student_id, "used")
    return [_view(r) for r in rows]


def list_memories(student_id: int, limit: int = LIST_LIMIT) -> list[Memory]:
    """This student's memories, newest first."""
    return [_view(r) for r in _run(lambda b: b.scroll(student_id, limit))]


def forget(student_id: int, memory_id: str) -> None:
    """Delete one of this student's memories. 404 if it isn't theirs or doesn't exist."""
    try:
        uuid.UUID(memory_id)
    except ValueError:
        raise ApiError(404, "memory_not_found", "That memory doesn't exist.")
    if not _run(lambda b: b.delete(student_id, memory_id)):
        raise ApiError(404, "memory_not_found", "That memory doesn't exist.")
    _changed(student_id, "deleted")


def forget_all(student_id: int) -> int:
    """Delete all of this student's memories. Returns how many were deleted."""
    count = _run(lambda b: b.delete_all(student_id))
    _changed(student_id, "deleted")
    return count


def forget_students(student_ids: list[int]) -> None:
    """Reset/seed: clear these students' memories (stale ones would point at orders that no longer exist)."""
    drain()
    for student_id in student_ids:
        try:
            _run(lambda b: b.delete_all(student_id))
        except Exception as exc:
            log.warning("Couldn't clear memories for student %s: %r", student_id, exc)


# --- memory-driven behaviour (used by the agents in Phase 7) -------------------------------

def usual_order(student_id: int, weekday: int) -> dict[str, Any] | None:
    """"My usual" for a weekday: the item set this student ordered most often on that day.

    Read from the canteen's memories, so it changes as soon as memory changes.
    Ties go to the most recent. Marks the memories it used.
    """
    rows = [r for r in _run(lambda b: b.scroll(student_id, LIST_LIMIT, written_by="canteen", kind="action"))
            if (r.payload.get("data") or {}).get("weekday") == weekday and r.payload["data"].get("items")]
    if not rows:
        return None
    key = lambda r: tuple(sorted((i["menu_item_id"], i["qty"]) for i in r.payload["data"]["items"]))  # noqa: E731
    counts = Counter(key(r) for r in rows)
    best = max(counts.values())
    chosen_key = next(key(r) for r in rows if counts[key(r)] == best)  # rows are newest first
    chosen = [r for r in rows if key(r) == chosen_key]
    pickups = Counter(r.payload["data"].get("pickup") for r in chosen if r.payload["data"].get("pickup"))
    _mark_used(student_id, chosen)
    _changed(student_id, "used")
    return {
        "items": chosen[0].payload["data"]["items"],
        "pickup": pickups.most_common(1)[0][0] if pickups else None,
        "times": len(chosen),
        "memory_ids": [r.id for r in chosen],
    }


def last_print_settings(student_id: int) -> dict[str, Any] | None:
    """"Print it like last time": the settings of the newest print memory. Marks it used."""
    rows = _run(lambda b: b.scroll(student_id, 1, written_by="print", kind="action"))
    if not rows:
        return None
    data = rows[0].payload.get("data") or {}
    _mark_used(student_id, rows)
    _changed(student_id, "used")
    return {
        "copies": data.get("copies", 1), "color": data.get("color", False),
        "double_sided": data.get("double_sided", False), "memory_id": rows[0].id,
    }
