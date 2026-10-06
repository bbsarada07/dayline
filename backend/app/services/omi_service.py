"""Omi (addendum I): requests spoken to the wearable, and facts from finished conversations.

Two webhooks, called by Omi's servers (or by the simulator, with the same payloads):

- Real-time transcript: POST /api/omi/transcript?t=<token>&uid=<omi uid>, body
  {"session_id": <uid>, "segments": [{"text", "speaker", "speakerId", "is_user", "start", "end"}]}
  (Omi's docs show a bare list of segments; both shapes are accepted). Speech is checked for the
  wake phrase; the words after it, up to a pause, run through the agents in voice mode and the
  reply goes back through Omi's notification API. Other speech is dropped and never stored.
- Memory creation: POST /api/omi/memory?t=<token>&uid=<omi uid>, body = Omi's conversation
  ({"id", "transcript_segments", "structured": {"title", "overview", "action_items"}, "discarded"...}).
  The Listener keeps at most five facts; only those are stored, never the transcript.

Omi doesn't sign webhooks, so each student's URLs carry a token derived from SECRET_KEY, and the
uid Omi adds must match the Omi id the student connected. Anything else is ignored.
"""

import hashlib
import hmac
import logging
import re
import threading
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app import clock
from app.config import settings
from app.db import engine
from app.errors import ApiError
from app.events import hub
from app.models import OmiLog, OmiProcessed, Student, Subject
from app.services import memory_service, omi_client, settings_service

log = logging.getLogger("dayline.omi")

SEGMENT_GAP = 1.5  # seconds between segments (Omi's own timestamps) that end a request
QUIET = timedelta(seconds=4)  # no new segments for this long (real time) also ends it
WAKE_ONLY_WAIT = timedelta(seconds=6)  # after a bare "Hey Dayline", how long to wait for the request
MAX_WORDS = 40
SAME_REQUEST_WINDOW = timedelta(seconds=60)
IDLE_RESET = timedelta(minutes=10)
SEEN_LIMIT = 400
UID_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{4,128}$")

GREETINGS = ("hey", "hi", "hay", "ok", "okay", "a")
NAME_FORMS = ("dayline", "day line", "daylin", "deyline", "day lane", "daylines")


# --- rate limits ------------------------------------------------------------------------

class _Limiter:
    def __init__(self, limit: int, window: timedelta = timedelta(minutes=1)):
        self.limit, self.window = limit, window
        self._hits: dict[int, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: int) -> bool:
        now = clock.real_now()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


transcript_limit = _Limiter(120)  # Omi sends a call every few seconds while you talk
memory_limit = _Limiter(10)
request_limit = _Limiter(6)  # voice requests that reach the agents


# --- connecting a student's Omi account ---------------------------------------------------------

def webhook_token(student_id: int) -> str:
    digest = hmac.new(settings.secret_key.encode(), f"omi-webhook:{student_id}".encode(), hashlib.sha256).hexdigest()
    return f"{student_id}.{digest[:32]}"


def demo_uid(student: Student) -> str:
    return f"{omi_client.DEMO_UID_PREFIX}{student.roll_no}"


def student_for(session: Session, token: str | None, uid: str | None) -> Student | None:
    """The student a webhook call belongs to, or None (bad token, or uid isn't the connected one)."""
    if not token or not uid or "." not in token:
        return None
    sid = token.split(".", 1)[0]
    if not sid.isdigit() or not hmac.compare_digest(token, webhook_token(int(sid))):
        return None
    student = session.get(Student, int(sid))
    if student is None or not student.omi_uid or not hmac.compare_digest(student.omi_uid, uid):
        return None
    return student


def webhook_urls(student: Student, base_url: str) -> dict[str, str]:
    token = webhook_token(student.id)
    return {kind: f"{base_url.rstrip('/')}/api/omi/{kind}?t={token}" for kind in ("transcript", "memory")}


def connect(session: Session, student: Student, uid: str) -> Student:
    """Save the student's Omi user id. One Omi account belongs to one student."""
    uid = uid.strip()
    if not UID_PATTERN.match(uid):
        raise ApiError(422, "bad_omi_uid", "That doesn't look like an Omi user id. Copy it from Omi's Developer Settings.")
    if omi_client.is_demo_uid(uid) and (uid != demo_uid(student) or not settings.demo_mode):
        raise ApiError(422, "bad_omi_uid", "Demo Omi ids only work in the demo, for your own account.")
    taken = session.exec(select(Student).where(Student.omi_uid == uid, Student.id != student.id)).first()
    if taken:
        raise ApiError(409, "omi_uid_taken", "That Omi account is already connected to another student.")
    student.omi_uid = uid
    session.add(student)
    session.commit()
    session.refresh(student)
    _forget_session(student.id)
    return student


def disconnect(session: Session, student: Student) -> Student:
    student.omi_uid = None
    session.add(student)
    session.commit()
    session.refresh(student)
    _forget_session(student.id)
    return student


# --- the activity log (no transcript text) -------------------------------------------------------

def _log(student_id: int | None, kind: str, source: str, uid: str | None, outcome: str, detail: str | None = None,
         *, segments: int = 0, words: int = 0, started: float | None = None) -> None:
    with Session(engine) as session:
        session.add(OmiLog(
            student_id=student_id, kind=kind, source=source, uid_tail=(uid or "")[-4:] or None, segments=segments,
            words=words, outcome=outcome, detail=detail, created_at=clock.local_now(),
            ms=int((time.perf_counter() - started) * 1000) if started else 0,
        ))
        session.commit()
    if student_id is not None:
        hub.publish("omi.activity", {"kind": kind, "outcome": outcome}, student_id=student_id)
    log.info("omi %s %s student=%s outcome=%s %s", kind, source, student_id, outcome, detail or "")


def activity(session: Session, student_id: int, limit: int = 30) -> list[OmiLog]:
    return list(session.exec(select(OmiLog).where(OmiLog.student_id == student_id)
                             .order_by(col(OmiLog.id).desc()).limit(limit)).all())


# --- wake phrase ----------------------------------------------------------------------------------

def _norm_token(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower().replace("’", "'"))


def normalize(text: str) -> str:
    return " ".join(t for t in (_norm_token(t) for t in text.split()) if t)


_wake_cache: tuple[tuple[str, ...], re.Pattern] | None = None


def wake_pattern() -> re.Pattern:
    """The configured wake phrases, plus the ways speech-to-text tends to mishear "dayline"."""
    global _wake_cache
    phrases = tuple(normalize(p) for p in settings_service.get("omi_wake_phrases") or ["hey dayline"] if normalize(p))
    if _wake_cache and _wake_cache[0] == phrases:
        return _wake_cache[1]
    names = "(?:" + "|".join(re.escape(n) for n in NAME_FORMS) + ")"
    greetings = "(?:" + "|".join(GREETINGS) + ")"
    parts = []
    for phrase in phrases:
        words = phrase.split()
        if "dayline" in words:
            parts.append(" ".join(
                names if w == "dayline" else greetings if i == 0 and w in GREETINGS else re.escape(w)
                for i, w in enumerate(words)))
        else:
            parts.append(re.escape(phrase))
    pattern = re.compile(r"\b(?:" + "|".join(parts) + r")\b")
    _wake_cache = (phrases, pattern)
    return pattern


def after_wake(text: str) -> list[str] | None:
    """The words after the wake phrase in this text (maybe none), or None if it isn't there."""
    tokens = text.split()
    kept = [(i, n) for i, n in ((i, _norm_token(t)) for i, t in enumerate(tokens)) if n]
    joined = " ".join(n for _, n in kept)
    match = wake_pattern().search(joined)
    if not match:
        return None
    used = len(joined[: match.end()].split())
    start = kept[used][0] if used < len(kept) else len(tokens)
    return tokens[start:]


# --- listening for requests --------------------------------------------------------------------------

@dataclass
class _Listening:
    """What we've heard from one student's Omi recently (in memory; one server)."""

    uid: str
    source: str
    seen: OrderedDict = field(default_factory=OrderedDict)  # segment keys already handled
    active: bool = False
    words: list[str] = field(default_factory=list)
    wake_start: float = 0.0  # Omi timestamp of the segment with the wake phrase
    last_start: float = 0.0
    last_end: float = 0.0
    heard_at: datetime | None = None  # real time the wake phrase arrived
    last_segment_at: datetime | None = None


@dataclass
class _Request:
    student_id: int
    uid: str
    source: str
    text: str
    wake_start: float
    heard_at: datetime


_sessions: dict[int, _Listening] = {}
_lock = threading.Lock()


def _forget_session(student_id: int) -> None:
    with _lock:
        _sessions.pop(student_id, None)


def reset() -> None:
    """Tests and demo reset: forget everything in flight."""
    with _lock:
        _sessions.clear()
    for limiter in (transcript_limit, memory_limit, request_limit):
        limiter.clear()


def _segments(body: Any) -> list[dict[str, Any]]:
    raw = body.get("segments") if isinstance(body, dict) else body
    out = []
    for seg in raw if isinstance(raw, list) else []:
        if isinstance(seg, dict) and isinstance(seg.get("text"), str) and seg["text"].strip():
            try:
                start, end = float(seg.get("start") or 0), float(seg.get("end") or seg.get("start") or 0)
            except (TypeError, ValueError):
                continue
            out.append({"text": seg["text"].strip()[:1000], "start": start, "end": max(start, end)})
    return out[:50]


def _finish(student_id: int, state: _Listening) -> _Request | None:
    text = " ".join(state.words).strip(" ,.;:-!?")
    request = (_Request(student_id, state.uid, state.source, text, state.wake_start, state.heard_at or clock.real_now())
               if text else None)
    state.active, state.words, state.heard_at = False, [], None
    return request


def _feed(student_id: int, state: _Listening, seg: dict[str, Any], finished: list[_Request]) -> None:
    """One new segment: start, continue or end a request."""
    if state.active:
        restarted = seg["start"] < state.last_start - 1  # Omi started a new conversation (timestamps reset)
        paused = state.words and seg["start"] - state.last_end >= SEGMENT_GAP
        rest = after_wake(seg["text"])
        if restarted or paused or (rest is not None and state.words):
            if request := _finish(student_id, state):
                finished.append(request)
        else:
            state.words += rest if rest is not None else seg["text"].split()
            state.last_end = seg["end"]
    if not state.active and (rest := after_wake(seg["text"])) is not None:
        state.active, state.words = True, list(rest)
        state.wake_start, state.last_end, state.heard_at = seg["start"], seg["end"], clock.real_now()
    state.last_start = seg["start"]
    if state.active and len(state.words) >= MAX_WORDS:
        state.words = state.words[:MAX_WORDS]
        if request := _finish(student_id, state):
            finished.append(request)


def receive_transcript(session: Session, token: str | None, uid: str | None, body: Any, source: str) -> dict[str, Any]:
    """Real-time transcript webhook. Answers at once; a finished request runs in the background."""
    started = time.perf_counter()
    student = student_for(session, token, uid)
    if student is None:
        _log(None, "transcript", source, uid, "ignored", "Unknown link or Omi id", started=started)
        return {"status": "ignored"}
    if not transcript_limit.allow(student.id):
        _log(student.id, "transcript", source, uid, "rate_limited", "Too many calls this minute", started=started)
        return {"status": "rate_limited"}
    segments = _segments(body)
    finished: list[_Request] = []
    fresh = 0
    with _lock:
        state = _sessions.get(student.id)
        if state is None or state.uid != uid:
            state = _sessions[student.id] = _Listening(uid=uid, source=source)
        state.source = source
        for seg in sorted(segments, key=lambda s: s["start"]):
            key = (round(seg["start"], 1), hashlib.sha1(normalize(seg["text"]).encode()).hexdigest()[:12])
            if key in state.seen:
                continue  # Omi retried, or sent an overlapping batch
            state.seen[key] = None
            while len(state.seen) > SEEN_LIMIT:
                state.seen.popitem(last=False)
            fresh += 1
            state.last_segment_at = clock.real_now()
            _feed(student.id, state, seg, finished)
        listening = state.active
    words = sum(len(s["text"].split()) for s in segments)
    if segments and not fresh:
        outcome, detail = "duplicate", "Segments already received"
    elif finished:
        outcome, detail = "request", f"Request heard ({len(finished[-1].text.split())} words)"
    elif listening:
        outcome, detail = "listening", "Wake phrase heard; waiting for the pause"
    elif segments:
        outcome, detail = "no_wake_phrase", "Speech without the wake phrase: dropped"
    else:
        outcome, detail = "empty", "No speech in this call"
    _log(student.id, "transcript", source, uid, outcome, detail, segments=len(segments), words=words, started=started)
    for request in finished:
        _dispatch(request)
    return {"status": outcome}


def check_pauses() -> int:
    """End requests the speaker has paused after (no new segments). Runs every second; returns how many ended."""
    now = clock.real_now()
    finished: list[_Request] = []
    dropped: list[tuple[int, _Listening]] = []
    with _lock:
        for student_id, state in list(_sessions.items()):
            if state.active and state.words and state.last_segment_at and now - state.last_segment_at >= QUIET:
                if request := _finish(student_id, state):
                    finished.append(request)
            elif state.active and not state.words and state.heard_at and now - state.heard_at >= WAKE_ONLY_WAIT:
                _finish(student_id, state)
                dropped.append((student_id, state))
            elif not state.active and state.last_segment_at and now - state.last_segment_at >= IDLE_RESET:
                del _sessions[student_id]
    for student_id, state in dropped:
        _log(student_id, "transcript", state.source, state.uid, "no_request", "Heard the wake phrase but no request after it")
    for request in finished:
        _log(request.student_id, "transcript", request.source, request.uid, "request",
             f"Request ended at a pause ({len(request.text.split())} words)")
        _dispatch(request)
    return len(finished)


async def pause_loop() -> None:
    """Background task (app lifespan): end requests at the pause, about once a second."""
    import asyncio

    while True:
        try:
            await asyncio.to_thread(check_pauses)
        except Exception as exc:
            log.warning("Omi pause check failed: %r", exc)
        await asyncio.sleep(1)


# --- running a request ------------------------------------------------------------------------------------

def _spawn(fn: Callable, *args: Any) -> None:
    """Run in the background (tests replace this to run inline)."""
    threading.Thread(target=fn, args=args, name="omi", daemon=True).start()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _dispatch(request: _Request) -> None:
    """Run a heard request once: the same request is never answered twice."""
    norm = normalize(request.text)
    key = "req:" + _hash(f"{request.student_id}|{request.wake_start:.1f}|{norm}|{request.heard_at:%Y%m%d%H}")
    now = clock.real_now()
    with Session(engine) as session:
        recent = session.exec(select(OmiProcessed).where(
            OmiProcessed.student_id == request.student_id, OmiProcessed.text_hash == _hash(norm),
            OmiProcessed.created_at >= now - SAME_REQUEST_WINDOW)).first()
        if recent:
            _log(request.student_id, "transcript", request.source, request.uid, "duplicate", "Same request just handled")
            return
        if not request_limit.allow(request.student_id):
            _log(request.student_id, "transcript", request.source, request.uid, "rate_limited", "Too many requests this minute")
            return
        session.add(OmiProcessed(student_id=request.student_id, key=key, text_hash=_hash(norm), created_at=now))
        try:
            session.commit()
        except IntegrityError:
            _log(request.student_id, "transcript", request.source, request.uid, "duplicate", "Request already handled")
            return
    _spawn(_answer, request)


def spoken(reply: str, proposals: list[dict]) -> str:
    """What Omi shows: at most two sentences, and a pointer to the app when there's something to confirm."""
    sentences = re.findall(r".+?[.!?]+(?=\s|$)", reply.strip()) or [reply]  # "69.4%" isn't a sentence end
    short = " ".join(s.strip() for s in sentences[:2]).strip()
    short = re.sub(r"\s*Confirm below\.?$", "", short).strip()
    return f"{short} Open Dayline to confirm." if proposals else short


def _answer(request: _Request) -> None:
    """Run the request through the agents (voice mode), store it, and reply through Omi."""
    from app.agents import conversations  # import late: agents import services

    started = time.perf_counter()
    conversation_id = f"omi-{clock.today():%Y%m%d}-{request.student_id}"
    try:
        outcome, events = conversations.run_message(
            request.student_id, conversation_id, request.text, lambda _t, _p: None, voice=True, source="omi")
    except Exception:
        log.exception("Omi request failed")
        _log(request.student_id, "reply", request.source, request.uid, "failed", "The agents failed on this request")
        return
    text = spoken(outcome.reply, outcome.proposals)
    notified = omi_client.notify(request.uid, text)
    _log(request.student_id, "reply", request.source, request.uid, "replied" if notified.sent else "reply_in_app",
         notified.detail, started=started)
    hub.publish("agent.reply", {
        "source": "omi", "conversation_id": conversation_id, "message": request.text, "reply": outcome.reply,
        "spoken": text, "proposals": outcome.proposals, "agents": outcome.agents, "events": events,
        "refused": outcome.refused, "notification": {"sent": notified.sent, "detail": notified.detail},
    }, student_id=request.student_id)


# --- finished conversations ------------------------------------------------------------------------------------

def receive_memory(session: Session, token: str | None, uid: str | None, body: Any, source: str) -> dict[str, Any]:
    """Memory-creation webhook. Answers at once; the Listener runs in the background."""
    started = time.perf_counter()
    student = student_for(session, token, uid)
    if student is None:
        _log(None, "memory", source, uid, "ignored", "Unknown link or Omi id", started=started)
        return {"status": "ignored"}
    if not isinstance(body, dict) or not str(body.get("id") or "").strip():
        _log(student.id, "memory", source, uid, "ignored", "Not an Omi conversation", started=started)
        return {"status": "ignored"}
    segments = len(body.get("transcript_segments") or [])
    if body.get("discarded"):
        _log(student.id, "memory", source, uid, "skipped", "Omi discarded this conversation", segments=segments, started=started)
        return {"status": "skipped"}
    if not memory_limit.allow(student.id):
        _log(student.id, "memory", source, uid, "rate_limited", "Too many conversations this minute", started=started)
        return {"status": "rate_limited"}
    conversation_id = str(body["id"]).strip()[:100]
    session.add(OmiProcessed(student_id=student.id, key=f"conv:{student.id}:{conversation_id}", created_at=clock.real_now()))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        _log(student.id, "memory", source, uid, "duplicate", "Conversation already handled", segments=segments, started=started)
        return {"status": "duplicate"}
    _log(student.id, "memory", source, uid, "accepted", "Reading the conversation", segments=segments, started=started)
    _spawn(_remember_conversation, student.id, uid, source, conversation_id, body)
    return {"status": "accepted"}


def _remember_conversation(student_id: int, uid: str, source: str, conversation_id: str, body: dict) -> None:
    from app.agents import listener

    started = time.perf_counter()
    with Session(engine) as session:
        subjects = sorted({s.short_name or s.name for s in session.exec(select(Subject)).all()})
    try:
        extraction = listener.extract(student_id, conversation_id, listener.envelope(body, subjects))
        for item in extraction.items:
            memory_service.remember(
                student_id, item.text, kind=item.kind, written_by="omi", source_ref=f"omi:{conversation_id}",
                data={"category": item.category, "due": item.due.isoformat() if item.due else None,
                      "nudge": item.nudge, "conversation": conversation_id})
    except Exception:
        log.exception("Omi conversation failed")
        _log(student_id, "memory", source, uid, "failed", "Couldn't read or save this conversation", started=started)
        return
    if extraction.by == "skipped":
        _log(student_id, "memory", source, uid, "nothing_kept", extraction.note, started=started)
        return
    kinds = ", ".join(sorted({i.category for i in extraction.items})) or "nothing that matters to Dayline"
    detail = f"Kept {len(extraction.items)} item{'s' if len(extraction.items) != 1 else ''}: {kinds}"
    _log(student_id, "memory", source, uid, "stored" if extraction.items else "nothing_kept",
         detail + (f". {extraction.note}" if extraction.note else ""), started=started)
    hub.publish("omi.memories", {"conversation": conversation_id, "items": [i.text for i in extraction.items],
                                 "by": extraction.by}, student_id=student_id)


# --- status for the Profile screen and the simulator ----------------------------------------------------------

def status(session: Session, student: Student, base_url: str) -> dict[str, Any]:
    last = session.exec(select(OmiLog).where(OmiLog.student_id == student.id, OmiLog.kind != "reply")
                        .order_by(col(OmiLog.id).desc()).limit(1)).first()
    token = webhook_token(student.id)
    return {
        "connected": bool(student.omi_uid),
        "omi_uid": student.omi_uid,
        "demo_uid": demo_uid(student) if settings.demo_mode else None,
        "is_demo_uid": omi_client.is_demo_uid(student.omi_uid),
        "urls": webhook_urls(student, base_url),
        "paths": {kind: f"/api/omi/{kind}?t={token}" for kind in ("transcript", "memory")},
        "notifications_configured": omi_client.configured(),
        "wake_phrases": settings_service.get("omi_wake_phrases"),
        "last_webhook_at": last.created_at if last else None,
        "simulator": settings.demo_mode,
    }
