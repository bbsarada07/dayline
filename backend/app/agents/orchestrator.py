"""The agent engine (addendum H, fallback design): our backend orchestrates.

One student message is one run:
  1. guard: questions about another student are refused before any model sees them;
  2. the top 5 memories for the message are read from shared memory;
  3. the Orchestrator agent answers with a plan (delegate / reply / refuse / remember);
  4. each chosen sub-agent loops: it asks for tools, we run them for the run's student, it answers;
  5. if more than one agent worked, the Orchestrator turns their answers into one reply.

Agents only ever see JSON envelopes: the message, the time, subject and menu names,
memories, and tool results. Never the student's id, name, roll number or the run token.
Every agent call falls back to the keyword router (mock_router) on any failure, and a
reply whose numbers aren't in the tool results is replaced by the router's answer.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from app import clock
from app.models import Student, Subject
from app.services import canteen_service, memory_service, print_service

from . import mock_router
from .llm import LLMClient, LLMError, MockClient, budget, default_client, pseudonym
from .runs import Run
from .tools import ACCESS, REGISTRY, RunContext, ToolError, run_tool

log = logging.getLogger("dayline.agents")

SUB_AGENTS = ("timetable", "print", "canteen")
NAMES = {"orchestrator": "Dayline", "timetable": "Timetable", "print": "Print", "canteen": "Canteen"}
MAX_TOOL_ROUNDS = 3
MAX_CALLS_PER_ROUND = 4
HISTORY_TURNS = 10
ACTIONS = ("delegate", "reply", "refuse", "remember")
STARTED = {
    "orchestrator": "Reading your request",
    "timetable": "Checking your timetable",
    "print": "Working on your printout",
    "canteen": "Working on your food",
}
REFUSAL = ("I can only help with your own classes, attendance, orders and printouts. "
           "Other students' details stay private.")


@dataclass
class Outcome:
    reply: str
    proposals: list[dict[str, Any]] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    refused: bool = False


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.:]\d+)?", text or "")


def numbers_check(text: str, *sources: Any) -> bool:
    """Every number in `text` appears somewhere in the sources (tool results, the message...)."""
    haystack = " ".join(s if isinstance(s, str) else json.dumps(s, ensure_ascii=False, default=str) for s in sources)
    return all(n in haystack for n in _numbers(text))


class Engine:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or default_client()
        self.mock = MockClient()

    # --- one agent call, with the fallback ---------------------------------------------------

    def _call(self, run: Run, agent: str, envelope: dict[str, Any], valid) -> tuple[dict[str, Any], bool]:
        """(reply, from_mock). Falls back to the keyword router on any failure or a bad shape."""
        if self.client.name != "mock":
            if not budget.take():
                run.note("Using the offline router (today's AI budget is used up).")
            else:
                try:
                    reply = self.client.complete(agent, envelope, user_id=pseudonym(run.student_id),
                                                 session_id=f"{run.conversation_id}-{agent}")
                    if valid(reply):
                        return reply, False
                    log.warning("%s agent replied in the wrong shape: %.300s", agent, reply)
                    run.note(f"The {NAMES[agent]} agent's answer didn't make sense, so the offline router stepped in.")
                except LLMError as exc:
                    log.warning("%s agent failed: %s", agent, exc)
                    run.note(f"The {NAMES[agent]} agent didn't answer ({exc}), so the offline router stepped in.")
        return self.mock.complete(agent, envelope, user_id="", session_id=""), True

    # --- the run ---------------------------------------------------------------------------------

    def handle(self, session: Session, student: Student, run: Run, message: str,
               history: list[dict[str, str]] | None = None, voice: bool = False) -> Outcome:
        run.send("agent_started", {"agent": "orchestrator", "label": STARTED["orchestrator"]})

        if other_student(session, student, message):
            run.send("agent_finished", {"agent": "orchestrator", "label": "Refused: that's another student's data"})
            return self._final(run, Outcome(REFUSAL, refused=True))

        context = self._context(session, student, run)
        memories = memory_service.recall(student.id, message, limit=5)
        if memories:
            run.send("memory_read", {"agent": "orchestrator", "count": len(memories),
                                     "label": f"Read {len(memories)} related memor{'y' if len(memories) == 1 else 'ies'}",
                                     "items": [m.text for m in memories]})
        base = {
            "message": message, "now": context.pop("now"), "attachment": context.pop("attachment"),
            "voice": voice, "memories": [m.text for m in memories], "context": context,
        }
        plan, _ = self._call(run, "orchestrator", {**base, "history": (history or [])[-HISTORY_TURNS:]}, _valid_plan)
        action = plan.get("action")

        if action == "remember":
            ctx = RunContext(session, student, run, "orchestrator")
            try:
                run_tool(ctx, "remember", {"text": plan["remember"], "kind": plan.get("kind") or "fact"})
            except ToolError as exc:
                plan = {"reply": str(exc)}
            run.send("agent_finished", {"agent": "orchestrator", "label": "Saved to memory"})
            return self._final(run, Outcome(plan.get("reply") or "Saved.", agents=["orchestrator"]))
        if action in ("reply", "refuse"):
            run.send("agent_finished", {"agent": "orchestrator", "label": "Answered"})
            reply = plan.get("reply") or mock_router.CAPABILITIES
            if not numbers_check(reply, message, base):
                reply = mock_router.CAPABILITIES
            return self._final(run, Outcome(reply, refused=action == "refuse", agents=["orchestrator"]))

        steps, seen = [], set()
        for step in plan.get("steps", []):
            if step.get("agent") in SUB_AGENTS and step["agent"] not in seen:
                seen.add(step["agent"])
                steps.append(step)
        run.send("agent_finished", {"agent": "orchestrator",
                                    "label": "Asked " + " and ".join(NAMES[s["agent"]] for s in steps)})

        answers, all_results = [], []
        for step in steps:
            answer, results = self._sub_agent(session, student, run, step["agent"], step.get("task") or message, base)
            answers.append({"agent": step["agent"], "answer": answer})
            all_results.extend(results)

        if len(answers) == 1:
            reply = answers[0]["answer"]
        else:
            summary_env = {"task": "summarize", "message": message, "voice": voice, "answers": answers}
            run.send("agent_started", {"agent": "orchestrator", "label": "Putting it together"})
            summary, _ = self._call(run, "orchestrator", summary_env, lambda r: isinstance(r.get("reply"), str) and r["reply"].strip())
            reply = summary["reply"]
            if not numbers_check(reply, answers, all_results, message):
                reply = " ".join(a["answer"] for a in answers)
            run.send("agent_finished", {"agent": "orchestrator", "label": "Done"})
        return self._final(run, Outcome(reply, run.proposals, run.agents_used))

    def _final(self, run: Run, outcome: Outcome) -> Outcome:
        latest = {p["type"]: p for p in run.proposals}  # an agent that proposed twice: its last proposal counts
        run.proposals[:] = list(latest.values())
        outcome.proposals = run.proposals
        outcome.agents = run.agents_used or outcome.agents
        run.send("final", {"reply": outcome.reply, "proposals": outcome.proposals, "agents": outcome.agents,
                           "refused": outcome.refused})
        return outcome

    def _context(self, session: Session, student: Student, run: Run) -> dict[str, Any]:
        """What every agent may know: the time, subject and menu names, and the attached file."""
        attachment = None
        if run.upload_id:
            upload = print_service.get_upload(session, student.id, run.upload_id)
            attachment = {"file": upload.original_filename, "pages": upload.pages}
        subjects = session.exec(select(Subject)).all()
        now = clock.local_now()
        return {
            "now": f"{now:%A} {now.day} {now:%b}, {now.hour % 12 or 12}:{now.minute:02d} {'am' if now.hour < 12 else 'pm'}",
            "attachment": attachment,
            "subjects": sorted({s.short_name or s.name for s in subjects}),
            "menu": [i.name for i in canteen_service.menu(session)],
        }

    def _use(self, run: Run, agent: str) -> None:
        if agent not in run.agents_used:
            run.agents_used.append(agent)

    def _sub_agent(self, session: Session, student: Student, run: Run, agent: str, task: str,
                   base: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        """Loop: the agent asks for tools (at most 3 rounds), we run them, it answers."""
        self._use(run, agent)
        run.send("agent_started", {"agent": agent, "label": STARTED[agent]})
        ctx = RunContext(session, student, run, agent)
        results: list[dict[str, Any]] = []
        envelope = {**base, "agent": agent, "task": task, "results": results}
        answer = None
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            envelope["must_answer"] = round_no == MAX_TOOL_ROUNDS
            reply, from_mock = self._call(run, agent, envelope, _valid_agent_reply)
            if "answer" in reply or round_no == MAX_TOOL_ROUNDS:
                answer = reply.get("answer")
                if answer and not from_mock and not numbers_check(answer, results, base["message"], base["context"]):
                    log.warning("%s answer had numbers not in its tool results: %.200s", agent, answer)
                    run.note(f"Checked the {NAMES[agent]} agent's numbers against your data and corrected them.")
                    answer = None
                if not answer:
                    fallback = self.mock.complete(agent, envelope, user_id="", session_id="")
                    answer = fallback.get("answer") or _plain_fallback(run, agent)
                break
            for call in reply["tool_calls"][:MAX_CALLS_PER_ROUND]:
                results.append(self._tool(ctx, agent, call))
        run.send("agent_finished", {"agent": agent, "label": answer})
        return answer, results

    def _tool(self, ctx: RunContext, agent: str, call: dict[str, Any]) -> dict[str, Any]:
        name, args = str(call.get("name", "")), call.get("args") or {}
        entry: dict[str, Any] = {"tool": name, "args": args}
        tool = REGISTRY.get(name)
        if tool is None or name not in ACCESS[agent]:
            entry["error"] = f"{NAMES[agent]} can't use a tool called {name}."
            ctx.run.send("tool_called", {"agent": agent, "tool": name, "label": entry["error"], "ok": False})
            return entry
        # Print and Canteen ask Timetable for the student's schedule: shown as Timetable's work.
        owner = tool.owner if tool.owner in SUB_AGENTS else agent
        if owner != agent:
            self._use(ctx.run, owner)
        try:
            label = tool.label(tool.args.model_validate(args))
        except Exception:
            label = name
        try:
            _, entry["result"] = run_tool(RunContext(ctx.session, ctx.student, ctx.run, agent), name, args)
            ok = True
        except ToolError as exc:
            entry["error"] = str(exc)
            ok = False
        except Exception:
            log.exception("Tool %s failed", name)
            entry["error"] = "That didn't work because of a problem on our side."
            ok = False
        ctx.run.send("tool_called", {"agent": owner, "for": agent if owner != agent else None, "tool": name,
                                     "label": label if ok else entry["error"], "ok": ok})
        return entry


def _plain_fallback(run: Run, agent: str) -> str:
    if any(p["agent"] == agent for p in run.proposals):
        return "It's ready below. Check the details and confirm."
    return "I couldn't work that out. Try asking a different way, or use the screens directly."


def _valid_plan(reply: dict[str, Any]) -> bool:
    action = reply.get("action")
    if action == "delegate":
        steps = reply.get("steps")
        return isinstance(steps, list) and any(isinstance(s, dict) and s.get("agent") in SUB_AGENTS for s in steps)
    if action == "remember":
        return isinstance(reply.get("remember"), str) and bool(reply["remember"].strip())
    return action in ("reply", "refuse") and isinstance(reply.get("reply"), str) and bool(reply["reply"].strip())


def _valid_agent_reply(reply: dict[str, Any]) -> bool:
    if isinstance(reply.get("answer"), str) and reply["answer"].strip():
        return True
    calls = reply.get("tool_calls")
    return isinstance(calls, list) and bool(calls) and all(
        isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("args", {}), dict) for c in calls)


_POSSESSIVE = re.compile(
    r"\b([A-Za-z]+)['’]s\s+(?:attendance|timetable|schedule|classes|orders?|lunch|food|prints?|printouts?|"
    r"memor(?:y|ies)|marks|token|card|roll|details|data|account)\b", re.IGNORECASE)
_NOT_PEOPLE = {"today", "tomorrow", "yesterday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
               "sunday", "week", "dayline", "it", "that", "what", "where", "who", "my"}


def other_student(session: Session, student: Student, message: str) -> bool:
    """Does the message ask about another student (by name, roll number or "X's")?"""
    own = {part.lower() for part in student.name.split()} | {student.roll_no.lower()}
    text = message.lower()
    for other in session.exec(select(Student).where(Student.id != student.id)).all():
        first = other.name.split()[0].lower()
        if other.roll_no.lower() in text or (first not in own and re.search(rf"\b{re.escape(first)}\b", text)):
            return True
    for name in _POSSESSIVE.findall(message):
        if name.lower() not in own and name.lower() not in _NOT_PEOPLE:
            return True
    return False
