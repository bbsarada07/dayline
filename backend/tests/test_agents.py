"""Phase 7: the agents (addendum H, spec 5.6), in mock mode and through a fake Lyzr.

No test reaches Lyzr: LyzrClient runs on an httpx MockTransport that answers like the
real agents would (using the keyword router), so the request shape, the fallback and
the guards are tested without spending credits.
"""

import dataclasses
import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app import seed as seed_module
from app.agents import llm, mock_router, runs
from app.agents.llm import LyzrClient
from app.agents.orchestrator import Engine, numbers_check, other_student, plain
from app.config import IST, settings
from app.db import engine
from app.main import app
from app.models import AgentMessage, MenuItem, Order, OrderItem, PrintJob, PrintUpload, Student
from app.routers import agent as agent_router
from app.routers import agent_tools as agent_tools_router
from app.services import attendance_service, memory_service, settings_service
from app.services.memory_backends import QdrantBackend
from tests.conftest import login

MONDAY_1220 = datetime(2026, 10, 5, 12, 20, tzinfo=IST)
ANANYA = 1
AGENT_IDS = {"orchestrator": "ag-orch", "timetable": "ag-tt", "print": "ag-print", "canteen": "ag-food",
             "listener": "ag-listen"}


def as_user(kind: str, username: str) -> TestClient:
    client = TestClient(app)
    assert login(client, kind, username).status_code == 200
    return client


@pytest.fixture(autouse=True)
def fresh_state():
    """Monday 12:20, no orders or print jobs, and Ananya's seeded demo memories only."""
    with Session(engine) as session:
        for model in (OrderItem, Order, PrintJob, PrintUpload, AgentMessage):
            session.exec(delete(model))
        menu_ids = {m.name: m.id for m in session.exec(select(MenuItem)).all()}
        session.commit()
    memory_service.configure(QdrantBackend.local())
    memory_service.backend().ensure()
    seed_module._demo_memories(MONDAY_1220, menu_ids)
    settings_service.set_value("clock_override", None)
    as_user("staff", "admin").put("/api/admin/demo-time", json={"local": "2026-10-05T12:20"})
    agent_router._recent.clear()
    llm.budget._used = 0
    yield
    memory_service.drain()
    memory_service.configure(QdrantBackend.local())
    memory_service.backend().ensure()


@pytest.fixture
def ananya():
    return as_user("student", "22CS001")


def ask(client: TestClient, message: str, **extra) -> tuple[list[tuple[str, dict]], dict]:
    """Send a chat message; return the SSE events and the final payload."""
    response = client.post("/api/agent/chat", json={"message": message, **extra})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in response.text.strip().split("\n\n"):
        kind, data = block.split("\n", 1)
        events.append((kind.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    final = [d for k, d in events if k == "final"]
    assert len(final) == 1, events
    return events, final[0]


def tools_used(events) -> list[tuple[str, str]]:
    return [(d["agent"], d["tool"]) for k, d in events if k == "tool_called"]


def sample(client: TestClient) -> str:
    return client.post("/api/agent/sample-file").json()["upload_id"]


def counts() -> tuple[int, int]:
    with Session(engine) as session:
        return len(session.exec(select(Order)).all()), len(session.exec(select(PrintJob)).all())


# --- spec 5.6 acceptance checks (mock mode) ----------------------------------------------

def test_attendance_uses_only_timetable_and_lists_below_threshold_first(ananya):
    events, final = ask(ananya, "What's my attendance?")
    assert final["agents"] == ["timetable"]
    assert tools_used(events) == [("timetable", "get_attendance_summary")]
    with Session(engine) as session:
        below = [r.short_name for r in attendance_service.list_for_student(session, ANANYA)
                 if r.standing.status == "below"]
    assert below and final["reply"].startswith("Below 75%: " + below[0])
    assert all(name in final["reply"] for name in below)


def test_can_i_skip_takes_numbers_from_the_tool(ananya):
    events, final = ask(ananya, "Can I skip DBMS tomorrow?")
    assert tools_used(events) == [("timetable", "attendance_what_if")]
    with Session(engine) as session:
        dbms = next(r for r in attendance_service.list_for_student(session, ANANYA) if r.short_name == "DBMS")
        after = attendance_service.what_if(session, ANANYA, dbms.subject_id, 1).after
    assert f"{after.percentage:g}%" in final["reply"] and f"{after.attended} of {after.held}" in final["reply"]
    assert "tomorrow" in final["reply"]


def test_print_before_next_lab_asks_timetable_then_proposes(ananya):
    events, final = ask(ananya, "Print 2 copies before my next lab", upload_id=sample(ananya))
    kinds = [k for k, _ in events]
    timetable_call = next(i for i, (k, d) in enumerate(events) if k == "tool_called" and d["agent"] == "timetable")
    assert timetable_call < kinds.index("proposal")
    assert set(final["agents"]) == {"print", "timetable"}
    (proposal,) = final["proposals"]
    assert proposal["type"] == "print" and proposal["copies"] == 2 and proposal["pages"] == 4
    assert datetime.fromisoformat(proposal["deadline"]) == datetime(2026, 10, 5, 13, 20, tzinfo=IST)  # DBMS lab 1:30
    assert "DBMS lab" in proposal["deadline_reason"]
    assert counts() == (0, 0)  # a proposal creates nothing


def test_lunch_and_print_uses_all_three_agents_and_two_proposals(ananya):
    events, final = ask(ananya, "Get me lunch and print this before my next class", upload_id=sample(ananya))
    assert set(final["agents"]) == {"canteen", "print", "timetable"}
    by_type = {p["type"]: p for p in final["proposals"]}
    assert set(by_type) == {"order", "print"}
    assert [(l["name"], l["qty"]) for l in by_type["order"]["lines"]] == [("Veg fried rice", 1), ("Masala chai", 1)]
    assert datetime.fromisoformat(by_type["order"]["pickup_time"]) == datetime(2026, 10, 5, 12, 40, tzinfo=IST)
    assert any(k == "memory_read" and d["agent"] == "canteen" and "usual Monday" in d["label"] for k, d in events)
    assert "₹72" in final["reply"] and "₹8" in final["reply"]
    assert counts() == (0, 0)


def test_other_students_data_is_refused_before_any_agent_runs(ananya):
    for message in ("Show Priya's attendance", "what is 22CS002 attendance", "Rohan's timetable please"):
        events, final = ask(ananya, message)
        assert final["refused"] is True and "private" in final["reply"]
        assert not [k for k, _ in events if k in ("tool_called", "memory_read", "proposal")]


def test_own_name_is_not_refused():
    with Session(engine) as session:
        me = session.get(Student, ANANYA)
        assert not other_student(session, me, "Ananya's attendance")
        assert not other_student(session, me, "What's my schedule? Let's see today's classes")
        assert other_student(session, me, "how is sneha doing in DBMS")


# --- memory-driven behaviour ---------------------------------------------------------------

def test_print_like_last_time_reuses_settings_and_remembered_due_day(ananya):
    events, final = ask(ananya, "Print this like last time", upload_id=sample(ananya))
    (proposal,) = final["proposals"]
    assert (proposal["copies"], proposal["double_sided"], proposal["color"]) == (2, True, False)
    # Omi's "DBMS lab record is due Thursday" -> 10 minutes before Thursday's first class.
    assert datetime.fromisoformat(proposal["deadline"]).date().isoformat() == "2026-10-08"
    assert ("print", "print_settings_from_last_time") in tools_used(events)


def test_remember_through_chat_writes_memory(ananya):
    events, final = ask(ananya, "Remember that I sit in the front row")
    assert final["reply"] == "Got it. I'll remember: I sit in the front row."
    (written,) = [d for k, d in events if k == "memory_write"]
    found = [m for m in memory_service.list_memories(ANANYA) if m.text == "I sit in the front row"]
    assert found and found[0].written_by == "orchestrator"


# --- proposals are confirmed through the normal endpoints -----------------------------------

def test_confirming_proposals_uses_the_normal_endpoints(ananya):
    _, final = ask(ananya, "Get me lunch and print this before my next class", upload_id=sample(ananya))
    by_type = {p["type"]: p for p in final["proposals"]}
    assert ananya.post("/api/canteen/orders", json=by_type["order"]["body"]).status_code == 200
    assert ananya.post("/api/print/jobs", json=by_type["print"]["body"]).status_code == 200
    assert counts() == (1, 1)


# --- the API: validation, history, rate limit -----------------------------------------------

def test_someone_elses_upload_is_rejected(ananya):
    priya = as_user("student", "22CS002")
    upload_id = sample(priya)
    response = ananya.post("/api/agent/chat", json={"message": "print this", "upload_id": upload_id})
    assert response.status_code == 404


def test_chat_needs_a_student(client):
    assert client.post("/api/agent/chat", json={"message": "hi"}).status_code == 401
    assert login(client, "staff", "canteen").status_code == 200
    assert client.post("/api/agent/chat", json={"message": "hi"}).status_code == 403


def test_history_keeps_both_turns_with_the_trace(ananya):
    _, final = ask(ananya, "What's my attendance?", conversation_id="conv-test-1")
    ask(ananya, "Can I skip OS tomorrow?", conversation_id="conv-test-1")
    data = ananya.get("/api/agent/history").json()
    assert data["conversation_id"] == "conv-test-1" and data["mode"] == "mock"
    assert [m["role"] for m in data["messages"]] == ["user", "assistant", "user", "assistant"]
    assert data["messages"][1]["content"] == final["reply"]
    assert data["messages"][1]["trace"]["agents"] == ["timetable"]
    priya = as_user("student", "22CS002")
    assert priya.get("/api/agent/history", params={"conversation_id": "conv-test-1"}).json()["messages"] == []


def test_rate_limit_is_twenty_a_minute(ananya, fixed_real_time):
    for _ in range(agent_router.RATE_LIMIT):
        ask(ananya, "hello")
    response = ananya.post("/api/agent/chat", json={"message": "hello"})
    assert response.status_code == 429
    fixed_real_time["now"] += timedelta(seconds=61)
    ask(ananya, "hello")


def test_sample_file_is_demo_only(ananya, monkeypatch):
    assert ananya.post("/api/agent/sample-file").json()["pages"] == 4
    monkeypatch.setattr(agent_router, "settings", dataclasses.replace(settings, demo_mode=False))
    assert ananya.post("/api/agent/sample-file").status_code == 403


# --- run tokens and the tool endpoint --------------------------------------------------------

@pytest.fixture
def tool_key(monkeypatch):
    monkeypatch.setattr(agent_tools_router, "settings", dataclasses.replace(settings, tool_key="k" * 32))
    return "k" * 32


def test_tool_endpoint_is_off_without_a_tool_key(client):
    assert client.post("/api/agent-tools/get_next_class", json={}).status_code == 404


def test_tool_endpoint_needs_key_and_live_run_token(client, tool_key, fixed_real_time):
    events = []
    run = runs.start(ANANYA, "conv", None, lambda t, p: events.append(t))
    url = "/api/agent-tools/get_attendance_summary"
    assert client.post(url, json={}, headers={"X-Run-Token": run.token}).status_code == 401
    assert client.post(url, json={}, headers={"X-Tool-Key": "wrong", "X-Run-Token": run.token}).status_code == 401
    assert client.post(url, json={}, headers={"X-Tool-Key": tool_key, "X-Run-Token": "made-up"}).status_code == 401
    ok = client.post(url, json={}, headers={"X-Tool-Key": tool_key, "X-Run-Token": run.token})
    assert ok.status_code == 200 and ok.json()["result"]["subjects"] and events == ["tool_called"]
    # A student id can't be smuggled in: arguments are strict.
    sneaky = client.post(url, json={"student_id": 2}, headers={"X-Tool-Key": tool_key, "X-Run-Token": run.token})
    assert sneaky.status_code == 422
    # Agents only get their own tools.
    denied = client.post("/api/agent-tools/propose_order", json={"items": [{"item": "Samosa"}]},
                         headers={"X-Tool-Key": tool_key, "X-Run-Token": run.token, "X-Agent": "timetable"})
    assert denied.status_code == 403
    fixed_real_time["now"] += runs.TOKEN_TTL + timedelta(seconds=1)
    assert client.post(url, json={}, headers={"X-Tool-Key": tool_key, "X-Run-Token": run.token}).status_code == 401


def test_finished_run_token_stops_working(client, tool_key):
    run = runs.start(ANANYA, "conv", None, lambda t, p: None)
    runs.finish(run)
    response = client.post("/api/agent-tools/get_next_class", json={},
                           headers={"X-Tool-Key": tool_key, "X-Run-Token": run.token})
    assert response.status_code == 401


# --- the Lyzr client, on a fake Lyzr --------------------------------------------------------

class FakeLyzr:
    """Answers /inference/chat/ like the real agents, and records every request."""

    def __init__(self, override=None):
        self.requests: list[dict] = []
        self.override = override  # (agent, envelope) -> reply dict, or None to answer normally

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), "headers": dict(request.headers), "body": body})
        agent = {v: k for k, v in AGENT_IDS.items()}[body["agent_id"]]
        envelope = json.loads(body["message"])
        reply = (self.override(agent, envelope) if self.override else None) or mock_router.respond(agent, envelope)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json={"response": "```json\n" + json.dumps(reply) + "\n```", "module_outputs": {}})


def run_engine(fake: FakeLyzr, message: str, upload_id: str | None = None):
    client = LyzrClient("test-key", AGENT_IDS, "https://lyzr.test/v3", 5, transport=httpx.MockTransport(fake))
    events = []
    run = runs.start(ANANYA, "conv-lyzr", upload_id, lambda t, p: events.append((t, p)))
    try:
        with Session(engine) as session:
            outcome = Engine(client).handle(session, session.get(Student, ANANYA), run, message, [])
    finally:
        runs.finish(run)
    return outcome, events


def test_lyzr_requests_carry_no_student_identity(ananya):
    fake = FakeLyzr()
    outcome, _ = run_engine(fake, "Get me lunch and print this before my next class", sample(ananya))
    assert {p["type"] for p in outcome.proposals} == {"order", "print"}
    agents_called = [r["body"]["agent_id"] for r in fake.requests]
    assert agents_called[0] == "ag-orch" and agents_called[-1] == "ag-orch"  # route, then summarize
    assert {"ag-food", "ag-print"} <= set(agents_called)
    for request in fake.requests:
        assert request["url"] == "https://lyzr.test/v3/inference/chat/"
        assert request["headers"]["x-api-key"] == "test-key"
        assert set(request["body"]) == {"user_id", "agent_id", "session_id", "message"}
        assert request["body"]["user_id"] == llm.pseudonym(ANANYA) and request["body"]["user_id"].startswith("dayline-")
        text = json.dumps(request["body"])
        for secret in ("22CS001", "Ananya", "Rao", '"student_id"', '"run_token"'):
            assert secret not in text


def test_lyzr_failure_falls_back_to_the_router_with_a_note(ananya):
    fake = FakeLyzr(lambda agent, env: httpx.ReadTimeout("slow") if agent == "timetable" else None)
    outcome, events = run_engine(fake, "What's my attendance?")
    assert outcome.reply.startswith("Below 75%")
    notes = [p["text"] for t, p in events if t == "note"]
    assert notes == ["The Timetable agent didn't answer in time, so the offline router stepped in."]


def test_daily_budget_switches_to_the_router(ananya, monkeypatch):
    monkeypatch.setattr(llm, "budget", llm.Budget(0))
    from app.agents import orchestrator
    monkeypatch.setattr(orchestrator, "budget", llm.budget)
    fake = FakeLyzr()
    outcome, events = run_engine(fake, "What's my attendance?")
    assert fake.requests == [] and outcome.reply.startswith("Below 75%")
    assert [p["text"] for t, p in events if t == "note"] == ["Using the offline router (today's AI budget is used up)."]


def test_made_up_numbers_are_replaced(ananya):
    def lie(agent, env):
        if agent == "timetable" and env.get("results"):
            return {"answer": "You're at 99% everywhere, skip whatever you like."}
    outcome, events = run_engine(FakeLyzr(lie), "What's my attendance?")
    assert "99" not in outcome.reply and outcome.reply.startswith("Below 75%")
    assert any(t == "note" and "numbers" in p["text"] for t, p in events)


def test_agent_cannot_use_another_agents_tools(ananya):
    def overreach(agent, env):
        if agent == "timetable" and not env.get("results"):
            return {"tool_calls": [{"name": "propose_order", "args": {"items": [{"item": "Samosa", "qty": 5}]}}]}
    outcome, events = run_engine(FakeLyzr(overreach), "What's my attendance?")
    assert outcome.proposals == []
    (call,) = [p for t, p in events if t == "tool_called"]
    assert call["ok"] is False and "can't use" in call["label"]


def test_copied_default_time_keeps_the_timetable_reason(ananya):
    """A model that copies 13:20 back as the deadline still gets "your DBMS lab" as the reason, shown as Timetable's."""
    def copy_time(agent, env):
        if agent == "print":
            if not env["results"]:
                return {"tool_calls": [{"name": "propose_print_job", "args": {"copies": 2, "deadline": "13:20"}}]}
            return {"answer": "Ready to confirm below."}
    outcome, events = run_engine(FakeLyzr(copy_time), "Print 2 copies before my next lab", sample(ananya))
    (proposal,) = outcome.proposals
    assert "DBMS lab" in proposal["deadline_reason"] and proposal["body"]["deadline"] is None
    assert "timetable" in outcome.agents
    assert any(t == "tool_called" and p["agent"] == "timetable" and p["for"] == "print" for t, p in events)


def test_repeated_proposals_are_blocked(ananya):
    def again(agent, env):
        if agent == "canteen" and len(env["results"]) < 3:
            return {"tool_calls": [{"name": "propose_order", "args": {"items": [{"item": "Samosa", "qty": len(env["results"]) + 1}]}}]}
        if agent == "canteen":
            return {"answer": "Samosa ready below."}
    outcome, _ = run_engine(FakeLyzr(again), "Get me a samosa")
    (proposal,) = outcome.proposals
    assert proposal["lines"][0]["qty"] == 1  # the first one stands; later ones were refused


def test_sub_agents_get_no_memories_in_their_envelope(ananya):
    fake = FakeLyzr()
    run_engine(fake, "Get me lunch")
    envelopes = {r["body"]["agent_id"]: json.loads(r["body"]["message"]) for r in fake.requests}
    assert envelopes["ag-orch"]["memories"]  # the orchestrator sees related memories for routing
    assert "memories" not in envelopes["ag-food"]


def test_bad_json_from_lyzr_falls_back(ananya):
    def garbage(agent, env):
        return {"something": "else"} if agent == "orchestrator" else None
    outcome, events = run_engine(FakeLyzr(garbage), "What's my attendance?")
    assert outcome.reply.startswith("Below 75%")
    assert any(t == "note" and "didn't make sense" in p["text"] for t, p in events)


def test_parse_json_tolerates_fences_and_text():
    assert llm.parse_json('Sure! ```json\n{"answer": "ok"}\n``` hope that helps') == {"answer": "ok"}
    with pytest.raises(llm.LLMError):
        llm.parse_json("no json here")


def test_replies_are_plain_text():
    reply = "Your attendance:\n\n- **Operating Systems**: 69.4%, below.\n- **DBMS**: 70%.\n\nOthers are fine."
    assert plain(reply) == "Your attendance: Operating Systems: 69.4%, below. DBMS: 70%. Others are fine."
    assert plain("Ready by 1:20 pm. ₹72.") == "Ready by 1:20 pm. ₹72."


def test_numbers_check():
    assert numbers_check("DBMS 70% at 1:30 pm", {"p": "70%", "t": "1:30 pm"})
    assert not numbers_check("DBMS 71%", {"p": "70%"})


# --- nudges ---------------------------------------------------------------------------------

def test_today_has_at_most_two_rule_based_nudges(ananya):
    nudges = ananya.get("/api/today").json()["nudges"]
    assert len(nudges) == 2
    # Omi heard the lab record is due Thursday (seeded), and lunch is at 12:40 with nothing ordered.
    assert nudges[0]["id"].startswith("omi-") and nudges[0]["ask"] == "Print this before Thursday"
    assert nudges[1]["id"].startswith("lunch-") and nudges[1]["ask"]
    _, final = ask(ananya, "Get me lunch")
    ananya.post("/api/canteen/orders", json=final["proposals"][0]["body"])
    assert not any(n["id"].startswith("lunch-") for n in ananya.get("/api/today").json()["nudges"])


def test_health_reports_agent_mode(client):
    lyzr = client.get("/api/health").json()["lyzr"]
    assert lyzr["mode"] == "mock" and lyzr["daily_call_limit"] == settings.lyzr_daily_call_limit
