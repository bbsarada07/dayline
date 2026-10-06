"""Agent tools (spec 5.6): thin wrappers over the same service functions the REST API uses.

No tool takes a student id: every tool runs for the run's student, which the server
knows from the run token. Argument models forbid unknown fields, so a model can't sneak
one in. Tools that would spend money only return proposals; the student confirms in the UI.
Numbers the agents quote come from these results, not from the model's own arithmetic.
"""

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import Session

from app import clock
from app.config import IST
from app.errors import ApiError
from app.models import Student
from app.services import (
    attendance_service, canteen_service, memory_service, print_service, timetable_service,
)

from .runs import Run

AGENTS = ("timetable", "print", "canteen")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class ToolError(Exception):
    """A plain-language problem the agent should hear about (bad arguments, nothing attached...)."""


@dataclass
class RunContext:
    session: Session
    student: Student
    run: Run
    agent: str = "orchestrator"  # the agent calling the tool (memory written_by)


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Tool:
    name: str
    owner: str  # timetable | print | canteen | memory | instructions
    description: str
    args: type[Args]
    run: Callable[[RunContext, Any], dict[str, Any]]
    label: Callable[[Any], str]


REGISTRY: dict[str, Tool] = {}


def tool(name: str, owner: str, description: str, args: type[Args], label: Callable[[Any], str]):
    def register(fn):
        REGISTRY[name] = Tool(name, owner, description, args, fn, label)
        return fn
    return register


# --- formatting --------------------------------------------------------------------

def _t(value: datetime) -> str:
    """'1:30 pm' in college time."""
    local = value.astimezone(IST)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"


def _money(paise: int) -> str:
    rupees = paise / 100
    return f"₹{rupees:g}" if rupees != int(rupees) else f"₹{int(rupees)}"


def _day_label(day: date) -> str:
    today = clock.today()
    if day == today:
        return f"today ({day:%A} {day.day} {day:%b})"
    if day == today + timedelta(days=1):
        return f"tomorrow ({day:%A} {day.day} {day:%b})"
    return f"{day:%A} {day.day} {day:%b}"


def resolve_day(value: str | None) -> date:
    """'today', 'tomorrow' or a weekday name (the next one, today included) -> a date."""
    text = (value or "today").strip().lower()
    today = clock.today()
    if text in ("", "today", "now"):
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    for index, name in enumerate(WEEKDAYS):
        if text.startswith(name[:3]):
            return today + timedelta(days=(index - today.weekday()) % 7)
    raise ToolError(f"I don't understand the day '{value}'. Use today, tomorrow or a weekday name.")


def _class_view(item: timetable_service.DayItem) -> dict[str, Any]:
    return {
        "kind": item.kind, "label": item.label, "subject": item.subject_name, "lab": item.subject_kind == "lab",
        "start": _t(item.start), "end": _t(item.end), "room": item.room_code, "status": item.status,
    }


# --- timetable -----------------------------------------------------------------------

class DayArgs(Args):
    day: str = Field(default="today", description="today, tomorrow, or a weekday name")


@tool("get_today_schedule", "timetable", "Classes, breaks and free time for a day (default today).",
      DayArgs, lambda a: "Checking your timetable" if a.day == "today" else f"Checking your timetable for {a.day}")
def get_today_schedule(ctx: RunContext, a: DayArgs) -> dict[str, Any]:
    day = resolve_day(a.day)
    items = timetable_service.day_schedule(ctx.session, ctx.student.section, day)
    return {"day": _day_label(day), "items": [_class_view(i) for i in items] or "No classes that day."}


class NoArgs(Args):
    pass


@tool("get_next_class", "timetable", "The next class today that hasn't started (null if none).",
      NoArgs, lambda a: "Checking your next class")
def get_next_class(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    nxt = timetable_service.next_class(ctx.session, ctx.student.section)
    return {"now": _t(clock.local_now()), "next_class": _class_view(nxt) if nxt else None}


@tool("get_free_slots", "timetable", "Breaks and free time today, with whether each is past, current or upcoming.",
      NoArgs, lambda a: "Finding your free time")
def get_free_slots(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    return {"now": _t(clock.local_now()),
            "free": [_class_view(i) for i in timetable_service.free_slots(ctx.session, ctx.student.section)]}


def _standing_view(s: attendance_service.Standing) -> dict[str, Any]:
    pct = s.percentage
    return {
        "percentage": None if pct is None else f"{pct:g}%", "held": s.held, "attended": s.attended,
        "status": s.status, "statement": s.statement,
    }


@tool("get_attendance_summary", "timetable", "Attendance per subject, below-threshold subjects first, with the plain statement.",
      NoArgs, lambda a: "Reading your attendance")
def get_attendance_summary(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    rows = attendance_service.list_for_student(ctx.session, ctx.student.id)
    return {
        "threshold": f"{attendance_service.threshold()}%",
        "subjects": [{"subject": r.short_name or r.name, "name": r.name, **_standing_view(r.standing)} for r in rows],
    }


def _find_subject(ctx: RunContext, text: str) -> attendance_service.SubjectAttendance:
    wanted = re.sub(r"[^a-z0-9& ]", "", text.lower()).strip()
    rows = attendance_service.list_for_student(ctx.session, ctx.student.id)
    exact = [r for r in rows if wanted in {(r.short_name or "").lower(), r.code.lower(), r.name.lower()}]
    if exact:
        return exact[0]
    loose = [r for r in rows if wanted and (wanted in (r.short_name or "").lower() or wanted in r.name.lower())]
    loose.sort(key=lambda r: ("lab" in (r.short_name or "").lower()) != ("lab" in wanted))
    if loose:
        return loose[0]
    raise ToolError(f"No subject called '{text}'. Subjects: {', '.join(r.short_name or r.name for r in rows)}.")


class WhatIfArgs(Args):
    subject: str = Field(description="Subject short name, code or name, e.g. DBMS")
    day: str | None = Field(default=None, description="Miss every class of this subject on this day (today, tomorrow, weekday)")
    miss: int | None = Field(default=None, ge=1, le=30, description="Or: miss this many upcoming classes")


@tool("attendance_what_if", "timetable",
      "Attendance after missing classes of one subject: either all its classes on a day, or a number of classes.",
      WhatIfArgs, lambda a: f"Working out what skipping {a.subject} does")
def attendance_what_if(ctx: RunContext, a: WhatIfArgs) -> dict[str, Any]:
    subject = _find_subject(ctx, a.subject)
    miss = a.miss
    day_text = None
    if a.day is not None:
        day = resolve_day(a.day)
        day_text = _day_label(day)
        items = timetable_service.day_schedule(ctx.session, ctx.student.section, day)
        miss = sum(1 for i in items if i.kind == "class" and i.subject_id == subject.subject_id)
        if miss == 0:
            return {"subject": subject.short_name, "day": day_text, "classes_that_day": 0,
                    "result": f"There's no {subject.short_name} class {day_text}, so nothing changes.",
                    "now": _standing_view(subject.standing)}
    result = attendance_service.what_if(ctx.session, ctx.student.id, subject.subject_id, miss or 1)
    return {
        "subject": subject.short_name, "day": day_text, "classes_missed": miss or 1,
        "now": _standing_view(result.current), "after_missing": _standing_view(result.after),
    }


# --- print -------------------------------------------------------------------------------

class PrintArgs(Args):
    copies: int = Field(default=1, ge=1, le=20)
    color: bool = False
    double_sided: bool = False
    deadline: str = Field(
        default="next_class",
        description="next_class (10 minutes before it), next_lab, a time today like 13:20, or a day "
                    "(tomorrow, thursday) meaning 10 minutes before that day's first class",
    )


def _first_class_deadline(ctx: RunContext, day: date) -> datetime:
    items = [i for i in timetable_service.day_schedule(ctx.session, ctx.student.section, day) if i.kind == "class"]
    start = items[0].start if items else datetime.combine(day, time(9, 0), tzinfo=IST)
    return start - timedelta(minutes=10)


def _next_lab_deadline(ctx: RunContext) -> tuple[datetime, str]:
    """10 minutes before the next lab that hasn't started (today or within the week)."""
    now = clock.local_now()
    for offset in range(7):
        day = clock.today() + timedelta(days=offset)
        for item in timetable_service.day_schedule(ctx.session, ctx.student.section, day):
            if item.kind == "class" and item.subject_kind == "lab" and item.start - timedelta(minutes=10) > now:
                name = item.label if item.label.lower().endswith("lab") else f"{item.label} lab"
                when = _t(item.start) if offset == 0 else f"{_t(item.start)} {_day_label(day)}"
                return item.start - timedelta(minutes=10), f"Your {name} starts at {when}, so it's set 10 minutes before."
    raise ToolError("You have no lab in the next week. Give a time or a day instead.")


def resolve_deadline(ctx: RunContext, spec: str) -> tuple[datetime | None, str | None]:
    """A deadline phrase -> (datetime or None for the default, reason). The model never does date maths."""
    text = (spec or "next_class").strip().lower()
    if text in ("", "next_class", "next class", "default", "suggested"):
        return None, None
    if text in ("next_lab", "next lab"):
        return _next_lab_deadline(ctx)
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})\s*(am|pm)?", text)
    if match:
        hour, minute, half = int(match[1]), int(match[2]), match[3]
        if half == "pm" and hour < 12:
            hour += 12
        if half is None and 1 <= hour <= 7:
            hour += 12  # "1:30" in a college day means afternoon
        return datetime.combine(clock.today(), time(hour % 24, minute), tzinfo=IST), f"needed by {text}"
    try:
        exact = datetime.fromisoformat(spec)
        return (exact if exact.tzinfo else exact.replace(tzinfo=IST)), "the time you asked for"
    except ValueError:
        pass
    day = resolve_day(text)
    if day == clock.today() and text not in ("today",):
        day = day + timedelta(days=7) if _first_class_deadline(ctx, day) <= clock.local_now() else day
    deadline = _first_class_deadline(ctx, day)
    return deadline, f"10 minutes before your first class {_day_label(day)}"


def _attachment(ctx: RunContext):
    if not ctx.run.upload_id:
        raise ToolError("No PDF is attached. Ask the student to attach the PDF they want printed.")
    return print_service.get_upload(ctx.session, ctx.student.id, ctx.run.upload_id)


def _is_clock_time(spec: str) -> bool:
    text = (spec or "").strip().lower()
    if re.fullmatch(r"(\d{1,2})[:.](\d{2})\s*(am|pm)?", text):
        return True
    try:
        datetime.fromisoformat(spec)
        return True
    except ValueError:
        return False


def _print_quote(ctx: RunContext, a: PrintArgs) -> tuple[print_service.Quote, str | None, bool]:
    """(quote, deadline reason, whether the timetable decided the deadline)."""
    upload = _attachment(ctx)
    deadline, reason = resolve_deadline(ctx, a.deadline)
    if deadline is not None and deadline == print_service.default_deadline(ctx.session, ctx.student).deadline:
        deadline, reason = None, None  # the model copied the default time back: keep the timetable's reason
    try:
        q = print_service.quote(ctx.session, ctx.student, upload.id, a.copies, a.color, a.double_sided, deadline)
    except ApiError as exc:
        raise ToolError(exc.message) from exc
    from_timetable = deadline is None or not _is_clock_time(a.deadline)
    return q, reason or q.deadline_reason, from_timetable


def _consulted_timetable(ctx: RunContext, label: str) -> None:
    """The timetable decided something for another agent (a deadline): show it as Timetable's work."""
    if ctx.agent == "timetable":
        return
    if "timetable" not in ctx.run.agents_used:
        ctx.run.agents_used.append("timetable")
    ctx.run.send("tool_called", {"agent": "timetable", "for": ctx.agent, "tool": "timetable", "label": label, "ok": True})


def _quote_view(q: print_service.Quote, reason: str | None) -> dict[str, Any]:
    return {
        "file": q.original_filename, "pages": q.pages, "copies": q.copies,
        "colour": "colour" if q.color else "black and white", "sides": "double sided" if q.double_sided else "single sided",
        "rate_per_page": _money(q.rate), "cost": _money(q.cost), "deadline": _t(q.deadline),
        "deadline_day": _day_label(q.deadline.astimezone(IST).date()), "deadline_reason": reason,
        "estimated_ready": _t(q.est_ready_at), "warning": q.warning,
    }


@tool("quote_print_job", "print", "Price and timing for printing the attached PDF. Creates nothing.",
      PrintArgs, lambda a: "Pricing the attached file")
def quote_print_job(ctx: RunContext, a: PrintArgs) -> dict[str, Any]:
    q, reason, _ = _print_quote(ctx, a)
    return _quote_view(q, reason)


@tool("propose_print_job", "print",
      "Prepare a print job for the attached PDF as a proposal the student confirms and pays for. Spends nothing.",
      PrintArgs, lambda a: "Preparing a print job for you to confirm")
def propose_print_job(ctx: RunContext, a: PrintArgs) -> dict[str, Any]:
    q, reason, from_timetable = _print_quote(ctx, a)
    if from_timetable:
        _consulted_timetable(ctx, f"Set the deadline: {reason}" if reason else "Set the deadline from your timetable")
    view = _quote_view(q, reason)
    proposal = {
        "id": secrets.token_hex(6), "type": "print", "agent": "print",
        "title": q.original_filename, "pages": q.pages, "copies": q.copies, "color": q.color,
        "double_sided": q.double_sided, "cost": q.cost, "deadline": q.deadline.isoformat(),
        "deadline_reason": reason, "est_ready_at": q.est_ready_at.isoformat(), "warning": q.warning,
        "body": {"upload_id": q.upload_id, "copies": q.copies, "color": q.color, "double_sided": q.double_sided,
                 "deadline": None if q.deadline_is_default else q.deadline.isoformat()},
    }
    ctx.run.proposals.append(proposal)
    ctx.run.send("proposal", {"proposal": proposal})
    return {"proposal_ready": True, **view}


@tool("get_print_status", "print", "The student's active print jobs and their status.",
      NoArgs, lambda a: "Checking your print jobs")
def get_print_status(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    jobs = [j for j in print_service.list_mine(ctx.session, ctx.student.id) if j.status in print_service.ACTIVE]
    return {"jobs": [{"code": j.code, "file": j.original_filename, "status": j.status,
                      "needed_by": _t(j.deadline),
                      "estimated_ready": _t(j.est_ready_at)} for j in jobs] or "No active print jobs."}


class CodeArgs(Args):
    code: str = Field(description="Print job code, e.g. P-0042")


@tool("cancel_print_job", "print", "Cancel one of the student's own print jobs while it is still queued.",
      CodeArgs, lambda a: f"Cancelling {a.code}")
def cancel_print_job(ctx: RunContext, a: CodeArgs) -> dict[str, Any]:
    wanted = a.code.strip().upper()
    for job in print_service.list_mine(ctx.session, ctx.student.id):
        if job.code == wanted:
            try:
                print_service.cancel(ctx.session, ctx.student.id, job.id)
            except ApiError as exc:
                raise ToolError(exc.message) from exc
            return {"cancelled": wanted}
    raise ToolError(f"You have no print job {wanted}.")


@tool("print_settings_from_last_time", "print", "The settings of the student's last print job, from shared memory.",
      NoArgs, lambda a: "Reading how you printed last time")
def print_settings_from_last_time(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    found = memory_service.last_print_settings(ctx.student.id)
    if found:
        ctx.run.send("memory_read", {"agent": ctx.agent, "label": "Read how you printed last time", "count": 1})
    return {"last_time": found or "No print jobs remembered yet."}


# --- canteen ---------------------------------------------------------------------------

@tool("get_menu", "canteen", "Today's menu: what can be ordered now, with prices.",
      NoArgs, lambda a: "Looking at today's menu")
def get_menu(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    items = canteen_service.menu(ctx.session)
    return {"items": [{"name": i.name, "price": _money(i.price), "veg": i.is_veg, "category": i.category,
                       "ready_in": f"{i.prep_minutes} min", "available": i.is_available and i.stock_today > 0}
                      for i in items]}


class OrderLineArgs(Args):
    item: str = Field(description="Menu item name, e.g. Veg fried rice")
    qty: int = Field(default=1, ge=1, le=10)


class OrderArgs(Args):
    items: list[OrderLineArgs] = Field(min_length=1, max_length=10,
                                       description='e.g. [{"item": "Veg fried rice", "qty": 1}]')
    pickup: str = Field(default="suggested", description="suggested (next break or lunch), or a time like 12:40")


def _menu_item(ctx: RunContext, name: str):
    wanted = name.strip().lower()
    items = canteen_service.menu(ctx.session)
    match = next((i for i in items if i.name.lower() == wanted), None) or \
        next((i for i in items if wanted in i.name.lower() or i.name.lower() in wanted), None)
    if match is None:
        raise ToolError(f"'{name}' isn't on the menu. Use get_menu to see what's there.")
    return match


@tool("propose_order", "canteen",
      "Prepare a canteen order as a proposal the student confirms and pays for. Spends nothing.",
      OrderArgs, lambda a: "Putting your order together")
def propose_order(ctx: RunContext, a: OrderArgs) -> dict[str, Any]:
    lines = [canteen_service.CartLine(_menu_item(ctx, l.item).id, l.qty) for l in a.items]
    pickup = None
    if a.pickup.strip().lower() not in ("", "suggested", "default", "lunch", "next break"):
        pickup, _ = resolve_deadline(ctx, a.pickup)
    try:
        q = canteen_service.quote(ctx.session, ctx.student, lines, pickup)
    except ApiError as exc:
        raise ToolError(exc.message) from exc
    proposal = {
        "id": secrets.token_hex(6), "type": "order", "agent": "canteen",
        "lines": [{"menu_item_id": l.menu_item_id, "name": l.name, "qty": l.qty, "line_total": l.line_total,
                   "is_veg": l.is_veg} for l in q.lines],
        "total": q.total, "pickup_time": q.pickup_time.isoformat(), "pickup_reason": q.pickup_reason,
        "body": {"items": [{"menu_item_id": l.menu_item_id, "qty": l.qty} for l in q.lines],
                 "pickup_time": q.pickup_time.isoformat(), "expected_total": q.total},
    }
    ctx.run.proposals.append(proposal)
    ctx.run.send("proposal", {"proposal": proposal})
    return {"proposal_ready": True, "items": [f"{l.name} × {l.qty}" for l in q.lines],
            "total": _money(q.total), "pickup": _t(q.pickup_time), "pickup_reason": q.pickup_reason}


class UsualArgs(Args):
    day: str = Field(default="today", description="Whose usual: today, or a weekday name")


@tool("usual_order", "canteen", "The student's usual canteen order for a weekday, from shared memory.",
      UsualArgs, lambda a: "Reading your usual order")
def usual_order(ctx: RunContext, a: UsualArgs) -> dict[str, Any]:
    day = resolve_day(a.day)
    found = memory_service.usual_order(ctx.student.id, day.weekday())
    if found:
        ctx.run.send("memory_read", {"agent": ctx.agent, "count": found["times"],
                                     "label": f"Read your usual {day:%A} order ({found['times']} times before)"})
        return {"weekday": f"{day:%A}", "items": [{"item": i["name"], "qty": i["qty"]} for i in found["items"]],
                "usual_pickup": found["pickup"], "times_ordered": found["times"]}
    return {"weekday": f"{day:%A}", "usual": f"No usual {day:%A} order remembered yet."}


@tool("get_order_status", "canteen", "The student's canteen orders today and their status.",
      NoArgs, lambda a: "Checking your orders")
def get_order_status(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    orders = canteen_service.orders_for_today(ctx.session, ctx.student.id)
    return {"orders": [{"token": o["token_no"], "status": o["status"], "pickup": _t(o["pickup_time"]),
                        "items": [f"{i['name']} × {i['qty']}" for i in o["items"]]} for o in orders] or "No orders today."}


class TokenArgs(Args):
    token: int = Field(ge=1, description="Order token number")


@tool("cancel_order", "canteen", "Cancel one of the student's own orders while it is still placed.",
      TokenArgs, lambda a: f"Cancelling token {a.token}")
def cancel_order(ctx: RunContext, a: TokenArgs) -> dict[str, Any]:
    for order in canteen_service.orders_for_today(ctx.session, ctx.student.id):
        if order["token_no"] == a.token:
            try:
                canteen_service.cancel(ctx.session, ctx.student.id, order["id"])
            except ApiError as exc:
                raise ToolError(exc.message) from exc
            return {"cancelled_token": a.token}
    raise ToolError(f"You have no order with token {a.token} today.")


# --- shared memory and instructions (any agent) ---------------------------------------------

class RecallArgs(Args):
    query: str = Field(min_length=1, max_length=200, description="What to look for, in plain words")


@tool("recall", "memory", "Search the student's shared memory by meaning.",
      RecallArgs, lambda a: f"Reading memory: {a.query}")
def recall(ctx: RunContext, a: RecallArgs) -> dict[str, Any]:
    found = memory_service.recall(ctx.student.id, a.query, limit=5)
    ctx.run.send("memory_read", {"agent": ctx.agent, "label": f"Read memory about “{a.query}”", "count": len(found),
                                 "items": [m.text for m in found]})
    return {"memories": [{"text": m.text, "written_by": m.written_by, "kind": m.kind} for m in found] or "Nothing relevant remembered."}


class RememberArgs(Args):
    text: str = Field(min_length=1, max_length=500)
    kind: Literal["preference", "fact", "instruction"] = "fact"


@tool("remember", "memory", "Save a short fact or preference about the student to shared memory.",
      RememberArgs, lambda a: "Saving to memory")
def remember(ctx: RunContext, a: RememberArgs) -> dict[str, Any]:
    writer = ctx.agent if ctx.agent in memory_service.WRITERS else "orchestrator"
    memory = memory_service.remember(ctx.student.id, a.text, kind=a.kind, written_by=writer)
    ctx.run.send("memory_write", {"agent": ctx.agent, "label": f"Remembered: {memory.text}", "text": memory.text})
    return {"saved": memory.text}


@tool("list_standing_instructions", "instructions", "The student's standing instructions (autonomous actions they set up).",
      NoArgs, lambda a: "Checking your standing instructions")
def list_standing_instructions(ctx: RunContext, a: NoArgs) -> dict[str, Any]:
    return {"instructions": [], "note": "Standing instructions arrive in a later phase."}


# --- which agent may use which tools ---------------------------------------------------------

ACCESS: dict[str, list[str]] = {
    "timetable": ["get_today_schedule", "get_next_class", "get_free_slots", "get_attendance_summary",
                  "attendance_what_if", "recall", "remember"],
    "print": ["propose_print_job", "get_print_status", "cancel_print_job",
              "print_settings_from_last_time", "get_next_class", "get_today_schedule", "recall", "remember"],
    "canteen": ["get_menu", "propose_order", "usual_order", "get_order_status", "cancel_order",
                "get_free_slots", "get_next_class", "recall", "remember", "list_standing_instructions"],
}


def describe(agent: str) -> list[dict[str, Any]]:
    """Tool list for an agent's prompt: name, what it does, and its arguments."""
    out = []
    for name in ACCESS[agent]:
        t = REGISTRY[name]
        schema = t.args.model_json_schema()
        out.append({"name": name, "description": t.description,
                    "args": {k: {kk: vv for kk, vv in v.items() if kk in ("type", "description", "default", "enum", "anyOf")}
                             for k, v in schema.get("properties", {}).items()}})
    return out


def run_tool(ctx: RunContext, name: str, raw_args: dict[str, Any] | None) -> tuple[Tool, dict[str, Any]]:
    """Validate and run one tool for the run's student. Raises ToolError with a plain message."""
    t = REGISTRY.get(name)
    if t is None:
        raise ToolError(f"There is no tool called {name}.")
    try:
        args = t.args.model_validate(raw_args or {})
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'args'}: {e['msg']}" for e in exc.errors())
        raise ToolError(f"Bad arguments for {name}: {problems}") from exc
    return t, t.run(ctx, args)
