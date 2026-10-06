"""Phase 8: Omi webhooks, wake phrase, duplicates, the Listener and notifications (mock mode, fake Omi)."""

import dataclasses
import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app import seed as seed_module
from app.agents import listener, llm
from app.config import IST, settings
from app.db import engine
from app.events import hub
from app.main import app
from app.models import AgentMessage, MenuItem, OmiLog, OmiProcessed, Order, OrderItem, PrintJob, PrintUpload, Student
from app.routers import agent as agent_router
from app.services import memory_service, omi_client, omi_service, settings_service
from app.services.memory_backends import QdrantBackend
from tests.conftest import login

MONDAY_1220 = datetime(2026, 10, 5, 12, 20, tzinfo=IST)
ANANYA = 1


def as_user(kind: str, username: str) -> TestClient:
    client = TestClient(app)
    assert login(client, kind, username).status_code == 200
    return client


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    with Session(engine) as session:
        for model in (OmiLog, OmiProcessed, AgentMessage, OrderItem, Order, PrintJob, PrintUpload):
            session.exec(delete(model))
        menu_ids = {m.name: m.id for m in session.exec(select(MenuItem)).all()}
        for student in session.exec(select(Student)).all():  # every student back on their demo Omi id
            student.omi_uid = f"demo-omi-{student.roll_no}"
            session.add(student)
        session.commit()
    memory_service.configure(QdrantBackend.local())
    memory_service.backend().ensure()
    seed_module._demo_memories(MONDAY_1220, menu_ids)
    as_user("staff", "admin").put("/api/admin/demo-time", json={"local": "2026-10-05T12:20"})
    omi_service.reset()
    agent_router._recent.clear()
    llm.budget._used = 0
    monkeypatch.setattr(omi_service, "_spawn", lambda fn, *args: fn(*args))  # run replies inline
    yield
    omi_service.reset()
    settings_service.set_value("omi_wake_phrases", settings.omi_wake_phrases)


@pytest.fixture
def ananya():
    return as_user("student", "22CS001")


@pytest.fixture
def events(monkeypatch):
    """Realtime events published during the test: [(type, payload, student_id)]."""
    seen = []
    original = hub.publish

    def record(type_, payload=None, *, student_id=None, roles=None):
        seen.append((type_, payload or {}, student_id))
        original(type_, payload, student_id=student_id, roles=roles)

    monkeypatch.setattr(hub, "publish", record)
    return seen


def omi(client: TestClient, kind: str = "transcript"):
    status = client.get("/api/omi/status").json()
    return status["paths"][kind], status["omi_uid"]


def speak(client: TestClient, *segments: tuple[str, float, float], uid: str | None = None, path: str | None = None):
    """Post one real-time call, shaped like Omi's: {"session_id": uid, "segments": [...]}."""
    default_path, default_uid = omi(client)
    uid = uid or default_uid
    body = {"session_id": uid, "segments": [
        {"text": text, "speaker": "SPEAKER_00", "speakerId": 0, "is_user": True, "start": start, "end": end}
        for text, start, end in segments]}
    return TestClient(app).post(f"{path or default_path}&uid={uid}", json=body).json()["status"]


def pause(fixed_real_time, seconds: float = 5) -> int:
    fixed_real_time["now"] += timedelta(seconds=seconds)
    return omi_service.check_pauses()


def replies(events) -> list[dict]:
    return [p for t, p, _ in events if t == "agent.reply"]


def logs(**where) -> list[OmiLog]:
    with Session(engine) as session:
        rows = session.exec(select(OmiLog).order_by(OmiLog.id)).all()
    return [r for r in rows if all(getattr(r, k) == v for k, v in where.items())]


CONVERSATION = {
    "id": "conv-1", "created_at": "2026-10-05T06:40:00+00:00", "started_at": "2026-10-05T06:30:00+00:00",
    "finished_at": "2026-10-05T06:39:00+00:00", "discarded": False,
    "structured": {"title": "After class", "overview": "Talked about the lab record and lunch.", "emoji": "📚",
                   "category": "education", "action_items": [{"description": "Return the lab manual to Priya", "completed": False}],
                   "events": []},
    "transcript_segments": [
        {"text": "Did you finish the DBMS lab record?", "speaker": "SPEAKER_01", "speakerId": 1, "speaker_name": "Priya",
         "is_user": False, "start": 0.0, "end": 2.0},
        {"text": "Not yet. It is due Wednesday and we need a printed copy.", "speaker": "SPEAKER_00", "speakerId": 0,
         "is_user": True, "start": 2.5, "end": 6.0},
        {"text": "Nice weather today, my cousin's wedding was fun.", "speaker": "SPEAKER_01", "speakerId": 1,
         "is_user": False, "start": 6.5, "end": 9.0},
    ],
    "apps_response": [],
}


# --- connecting ----------------------------------------------------------------------------------

def test_status_gives_webhook_urls_and_the_demo_id(ananya):
    status = ananya.get("/api/omi/status").json()
    assert status["connected"] and status["omi_uid"] == "demo-omi-22CS001" and status["is_demo_uid"]
    assert status["urls"]["transcript"].endswith(status["paths"]["transcript"])
    assert status["paths"]["memory"].startswith("/api/omi/memory?t=1.")
    assert status["notifications_configured"] is False and status["simulator"] is True


def test_connect_rules(ananya):
    assert ananya.put("/api/omi/connect", json={"uid": "no spaces allowed"}).status_code == 422
    assert ananya.put("/api/omi/connect", json={"uid": "demo-omi-22CS002"}).status_code == 422  # someone else's demo id
    assert ananya.put("/api/omi/connect", json={"uid": "omi-real-ananya"}).json()["omi_uid"] == "omi-real-ananya"
    priya = as_user("student", "22CS002")
    assert priya.put("/api/omi/connect", json={"uid": "omi-real-ananya"}).status_code == 409
    ananya.delete("/api/omi/connect")
    path, _ = omi(ananya)
    assert speak(ananya, ("Hey Dayline what's my attendance", 0, 2), uid="omi-real-ananya", path=path) == "ignored"


def test_unknown_uid_or_bad_link_is_ignored(ananya, events, fixed_real_time):
    path, uid = omi(ananya)
    assert speak(ananya, ("Hey Dayline what's my attendance", 0, 2), uid="someone-else") == "ignored"
    assert speak(ananya, ("Hey Dayline what's my attendance", 0, 2), path=path.replace("t=1.", "t=2.")) == "ignored"
    assert speak(ananya, ("Hey Dayline what's my attendance", 0, 2), path="/api/omi/transcript?t=1.forged") == "ignored"
    pause(fixed_real_time)
    assert replies(events) == []
    assert [r.student_id for r in logs(outcome="ignored")] == [None, None, None]


# --- the wake phrase and the request ---------------------------------------------------------------

def test_hey_dayline_runs_the_request_and_replies(ananya, events, fixed_real_time):
    assert speak(ananya, ("Hey Dayline, what's my attendance?", 10.0, 12.5)) == "listening"
    assert pause(fixed_real_time) == 1
    (reply,) = replies(events)
    assert reply["message"] == "what's my attendance" and reply["reply"].startswith("Below 75%")
    assert reply["source"] == "omi" and reply["agents"] == ["timetable"]
    assert reply["notification"] == {"sent": False, "detail": "Simulated device: shown in Dayline instead of sent to a phone"}
    with Session(engine) as session:
        stored = session.exec(select(AgentMessage).where(AgentMessage.conversation_id.startswith("omi-"))).all()
    assert [m.role for m in stored] == ["user", "assistant"] and json.loads(stored[0].trace_json)["source"] == "omi"
    assert [r.outcome for r in logs(kind="reply")] == ["reply_in_app"]


def test_request_spans_segments_and_ends_at_a_gap(ananya, events):
    assert speak(ananya, ("okay so hey day line, get me", 0.0, 2.0), ("my usual lunch", 2.2, 3.0)) == "listening"
    # 3 seconds later, someone else talks: the request ended at the pause.
    assert speak(ananya, ("anyway the weather is nice", 6.0, 8.0)) == "request"
    (reply,) = replies(events)
    assert reply["message"] == "get me my usual lunch"
    assert [p["type"] for p in reply["proposals"]] == ["order"]
    assert counts() == (0,)  # a proposal, not an order


def counts() -> tuple[int]:
    with Session(engine) as session:
        return (len(session.exec(select(Order)).all()),)


def test_speech_without_the_wake_phrase_is_dropped(ananya, events, fixed_real_time):
    before = len(memory_service.list_memories(ANANYA))
    assert speak(ananya, ("I think the DBMS class was boring today", 0, 3)) == "no_wake_phrase"
    pause(fixed_real_time)
    assert replies(events) == []
    assert len(memory_service.list_memories(ANANYA)) == before
    with Session(engine) as session:
        assert session.exec(select(AgentMessage)).all() == []


def test_bare_wake_phrase_waits_for_the_request(ananya, events, fixed_real_time):
    assert speak(ananya, ("Hey Dayline.", 0.0, 1.0)) == "listening"
    assert speak(ananya, ("what's my next class", 3.0, 4.5)) == "listening"  # a pause before the request is fine
    pause(fixed_real_time)
    assert replies(events)[0]["message"] == "what's my next class"


def test_bare_wake_phrase_with_nothing_after_is_dropped(ananya, events, fixed_real_time):
    assert speak(ananya, ("Hey Dayline.", 0.0, 1.0)) == "listening"
    pause(fixed_real_time, 7)
    assert replies(events) == [] and [r.outcome for r in logs(outcome="no_request")] == ["no_request"]


def test_long_requests_stop_at_forty_words(ananya, events):
    words = " ".join(["please"] * 60)
    assert speak(ananya, (f"Hey Dayline {words}", 0, 20)) == "request"
    assert len(replies(events)[0]["message"].split()) == omi_service.MAX_WORDS


def test_wake_phrase_variants_and_custom_phrase():
    assert omi_service.after_wake("Hi day-line, print this") == ["print", "this"]
    assert omi_service.after_wake("A Dayline what's up?") == ["what's", "up?"]
    assert omi_service.after_wake("Hey Daylin get lunch") == ["get", "lunch"]
    assert omi_service.after_wake("hey there, daylight saving") is None
    settings_service.set_value("omi_wake_phrases", ["ok campus"])
    assert omi_service.after_wake("OK campus, show my timetable") == ["show", "my", "timetable"]
    assert omi_service.after_wake("hey dayline show my timetable") is None


# --- duplicates ---------------------------------------------------------------------------------------

def test_retried_and_overlapping_calls_are_answered_once(ananya, events, fixed_real_time):
    first = ("Hey Dayline, what's my attendance?", 10.0, 12.5)
    assert speak(ananya, first) == "listening"
    assert speak(ananya, first) == "duplicate"  # Omi retried the same call
    assert speak(ananya, first, ("thanks", 30.0, 30.5)) == "request"  # overlapping batch: only "thanks" is new
    pause(fixed_real_time)
    assert len(replies(events)) == 1


def test_the_same_request_again_within_a_minute_is_ignored(ananya, events, fixed_real_time):
    speak(ananya, ("Hey Dayline, what's my attendance?", 10.0, 12.5))
    pause(fixed_real_time)
    speak(ananya, ("Hey Dayline, what's my attendance?", 40.0, 42.5))  # different timestamps, same words
    pause(fixed_real_time)
    assert len(replies(events)) == 1 and logs(outcome="duplicate")[-1].detail == "Same request just handled"
    fixed_real_time["now"] += timedelta(seconds=61)
    speak(ananya, ("Hey Dayline, what's my attendance?", 90.0, 92.5))
    pause(fixed_real_time)
    assert len(replies(events)) == 2


def test_transcript_webhook_rate_limit(ananya):
    for i in range(omi_service.transcript_limit.limit):
        speak(ananya, (f"chatting {i}", float(i), i + 0.5))
    assert speak(ananya, ("one more", 500.0, 501.0)) == "rate_limited"


# --- replies through Omi's notification API ---------------------------------------------------------------

def test_real_omi_user_gets_a_notification(ananya, events, fixed_real_time, monkeypatch):
    sent = []
    monkeypatch.setattr(omi_client, "notify", lambda uid, message: sent.append((uid, message)) or omi_client.Notified(True, "Sent to Omi"))
    ananya.put("/api/omi/connect", json={"uid": "omi-real-ananya"})
    speak(ananya, ("Hey Dayline get me my usual lunch", 0, 3), uid="omi-real-ananya")
    pause(fixed_real_time)
    ((uid, message),) = sent
    assert uid == "omi-real-ananya" and message.endswith("Open Dayline to confirm.") and "₹72" in message
    assert [r.outcome for r in logs(kind="reply")] == ["replied"]


def test_notification_request_shape_and_errors(monkeypatch):
    captured = []

    def omi_api(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200 if request.url.params["uid"] == "u-ok" else 403, json={"status": "Ok"})

    monkeypatch.setattr(omi_client, "settings", dataclasses.replace(settings, omi_app_id="app123", omi_app_secret="s3cret"))
    transport = httpx.MockTransport(omi_api)
    assert omi_client.notify("u-ok", "Your lunch is ready.", transport).sent is True
    request = captured[0]
    assert request.method == "POST" and request.url.path == "/v2/integrations/app123/notification"
    assert request.url.host == "api.omi.me" and dict(request.url.params) == {"uid": "u-ok", "message": "Your lunch is ready."}
    assert request.headers["authorization"] == "Bearer s3cret"
    refused = omi_client.notify("u-other", "Hi there!", transport)
    assert refused.sent is False and "isn't installed" in refused.detail
    assert omi_client.notify("demo-omi-22CS001", "Hi there!", transport).sent is False and len(captured) == 2


def test_notifications_off_without_credentials():
    result = omi_client.notify("u-real", "Hello there")
    assert result.sent is False and "OMI_APP_ID" in result.detail


def test_spoken_reply_is_two_sentences_and_points_to_the_app():
    proposal = [{"type": "order"}]
    assert omi_service.spoken("One. Two! Three. Confirm below.", proposal) == "One. Two! Open Dayline to confirm."
    assert omi_service.spoken("OS is at 69.4%. DBMS is at 70%.", []) == "OS is at 69.4%. DBMS is at 70%."


# --- finished conversations (memory webhook) ---------------------------------------------------------------------

def post_conversation(client: TestClient, body: dict) -> str:
    path, uid = omi(client, "memory")
    return TestClient(app).post(f"{path}&uid={uid}", json=body).json()["status"]


def test_conversation_keeps_a_few_facts_never_the_transcript(ananya, events):
    assert post_conversation(ananya, CONVERSATION) == "accepted"
    heard = [m for m in memory_service.list_memories(ANANYA) if m.source_ref == "omi:conv-1"]
    texts = {m.text for m in heard}
    assert {"DBMS lab record is due Wednesday", "Print the DBMS lab record before Wednesday",
            "Return the lab manual to Priya"} <= texts
    assert 1 <= len(heard) <= 5 and all(m.written_by == "omi" for m in heard)
    everything = json.dumps([dataclasses.asdict(m) for m in memory_service.list_memories(ANANYA)])
    assert "weather" not in everything and "wedding" not in everything
    assert "weather" not in json.dumps([r.detail for r in logs()])
    assert [t for t, _, _ in events if t == "omi.memories"]


def test_omi_deadline_becomes_a_nudge_until_printed(ananya):
    post_conversation(ananya, CONVERSATION)
    nudges = ananya.get("/api/today").json()["nudges"]
    omi_nudges = [n for n in nudges if n["id"].startswith("omi-")]
    assert omi_nudges and omi_nudges[0]["agent"] == "omi" and omi_nudges[0]["text"].startswith("Omi heard:")
    up = ananya.post("/api/agent/sample-file").json()
    ananya.post("/api/print/jobs", json={"upload_id": up["upload_id"], "copies": 1})
    assert not [n for n in ananya.get("/api/today").json()["nudges"] if n["id"].startswith("omi-")]


def test_conversation_duplicates_discarded_and_irrelevant(ananya):
    assert post_conversation(ananya, CONVERSATION) == "accepted"
    assert post_conversation(ananya, CONVERSATION) == "duplicate"
    assert post_conversation(ananya, {**CONVERSATION, "id": "conv-2", "discarded": True}) == "skipped"
    before = len(memory_service.list_memories(ANANYA))
    small_talk = {**CONVERSATION, "id": "conv-3", "structured": {"title": "Chat", "overview": "", "action_items": []},
                  "transcript_segments": [{"text": "Nice weather, see you soon", "start": 0, "end": 1}]}
    assert post_conversation(ananya, small_talk) == "accepted"
    assert len(memory_service.list_memories(ANANYA)) == before
    assert logs(outcome="nothing_kept")[-1].detail.startswith("Nothing about classes")


def test_listener_output_is_cleaned(monkeypatch):
    """A Listener (Lyzr) reply is trimmed to five well-formed items in Dayline's categories."""
    def lyzr(request: httpx.Request) -> httpx.Response:
        items = [{"text": f"Quiz {i} on Friday", "kind": "fact", "category": "deadline", "due": "friday"} for i in range(7)]
        items.insert(0, {"text": "Priya's phone number is 12345", "kind": "fact", "category": "gossip", "due": None})
        return httpx.Response(200, json={"response": json.dumps({"items": items})})

    client = llm.LyzrClient("k", {"listener": "ag-listen"}, "https://lyzr.test/v3", 5, transport=httpx.MockTransport(lyzr))
    monkeypatch.setattr(listener, "default_client", lambda: client)
    env = listener.envelope(CONVERSATION, ["DBMS"])
    result = listener.extract(ANANYA, "conv-1", env)
    assert result.by == "lyzr" and len(result.items) == 5
    assert all(i.category == "deadline" and i.due and i.due.weekday() == 4 for i in result.items)


def test_listener_falls_back_when_lyzr_fails(monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = llm.LyzrClient("k", {"listener": "ag-listen"}, "https://lyzr.test/v3", 5, transport=httpx.MockTransport(down))
    monkeypatch.setattr(listener, "default_client", lambda: client)
    result = listener.extract(ANANYA, "conv-1", listener.envelope(CONVERSATION, ["DBMS"]))
    assert result.by == "mock" and result.items and "offline listener" in result.note


# --- the log, the simulator label and health --------------------------------------------------------------------

def test_activity_log_has_no_transcript_text(ananya, fixed_real_time):
    speak(ananya, ("Hey Dayline, what's my attendance?", 0, 2))
    pause(fixed_real_time)
    entries = ananya.get("/api/omi/activity").json()["entries"]
    assert [e["outcome"] for e in entries][:3] == ["reply_in_app", "request", "listening"]
    assert "attendance" not in json.dumps(entries)


def test_simulator_uses_the_same_webhook(ananya):
    path, uid = omi(ananya)
    response = TestClient(app).post(f"{path}&uid={uid}", headers={"X-Dayline-Simulator": "1"},
                                    json={"session_id": uid, "segments": [{"text": "hello", "start": 0, "end": 1}]})
    assert response.json() == {"status": "no_wake_phrase"} and "message" not in response.json()
    assert logs()[-1].source == "simulator"


def test_bare_list_payload_from_the_docs_is_accepted(ananya):
    path, uid = omi(ananya)
    response = TestClient(app).post(f"{path}&uid={uid}", json=[{"text": "hello there", "start": 0, "end": 1}])
    assert response.json()["status"] == "no_wake_phrase"


def test_health_reports_omi(client):
    data = client.get("/api/health").json()["omi"]
    assert data["configured"] is False and data["students_connected"] == 6 and data["simulator"] is True
