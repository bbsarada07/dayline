"""Keyword router used when AGENT_MODE=mock, and per-call when a real agent fails.

It answers as each agent in exactly the JSON shape the Lyzr agents use (see
prompts/*.md), deciding only from the message and the tool results so far. That makes it
stateless, so it can take over halfway through a run if Lyzr times out.
"""

import re
from dataclasses import dataclass, field
from typing import Any

_REMEMBER = re.compile(
    r"^\s*(?:hey\s+dayline[,\s]+)?(?:please\s+)?(?:remember|note(?:\s+down)?|don'?t\s+forget|keep\s+in\s+mind)"
    r"(?:\s+that)?[\s,:]+(?P<fact>.+?)\s*[.!]*\s*$",
    re.IGNORECASE | re.DOTALL,
)
_PREFERENCE = re.compile(
    r"\b(prefer|like|love|hate|dislike|don'?t\s+like|favou?rite|allergic|vegetarian|vegan|no\s+onion|spicy|usual)\b",
    re.IGNORECASE,
)

CAPABILITIES = ("I can help with your classes and attendance, canteen orders, printouts, and what Dayline "
                "remembers for you. Try “What's my attendance?”")

_ATTENDANCE = re.compile(r"\b(attendance|attend|percent|percentage|skip|bunk|miss|absent|75)\b", re.I)
_TIMETABLE = re.compile(r"\b(timetable|schedule|next class|classes today|free (?:time|slot|period)|room)\b", re.I)
_PRINT = re.compile(r"\b(print|printout|print-?out|pdf|copies|copy|xerox|attached)\b", re.I)
_CANTEEN = re.compile(r"\b(lunch|breakfast|dinner|food|eat|hungry|order|usual|canteen|menu|snack|chai|coffee|tea|token)\b", re.I)
_STATUS = re.compile(r"\b(status|where is|ready yet|is my)\b", re.I)
_CANCEL = re.compile(r"\bcancel\b", re.I)
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass
class Intent:
    name: str
    slots: dict[str, str] = field(default_factory=dict)


def route(text: str) -> Intent | None:
    """'Remember that ...' (and close variants) -> the fact to store. Used by the Memory screen too."""
    match = _REMEMBER.match(text or "")
    if match and match.group("fact").strip():
        fact = match.group("fact").strip()
        kind = "preference" if _PREFERENCE.search(fact) else "fact"
        return Intent("remember", {"fact": fact[0].upper() + fact[1:], "kind": kind})
    return None


def respond(agent: str, env: dict[str, Any]) -> dict[str, Any]:
    """Answer one agent call, in that agent's JSON format."""
    return {"orchestrator": _orchestrator, "timetable": _timetable, "print": _print, "canteen": _canteen}[agent](env)


# --- helpers -------------------------------------------------------------------------------

def _day(text: str) -> str | None:
    text = text.lower()
    if "tomorrow" in text:
        return "tomorrow"
    if re.search(r"\btoday\b", text):
        return "today"
    return next((d for d in _DAYS if d in text), None)


def _time(text: str) -> str | None:
    match = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", text.lower())
    return f"{match[1]}:{match[2]}{(' ' + match[3]) if match[3] else ''}" if match else None


def _count(text: str, word: str) -> int | None:
    numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    match = re.search(rf"\b(\d+|{'|'.join(numbers)})\s+{word}", text.lower())
    if not match:
        return None
    return int(match[1]) if match[1].isdigit() else numbers[match[1]]


def _results(env: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    return [r for r in env.get("results", []) if r.get("tool") == tool]


def _result(env: dict[str, Any], tool: str) -> dict[str, Any] | None:
    found = _results(env, tool)
    return found[-1].get("result") if found else None


def _errors(env: dict[str, Any]) -> list[str]:
    return [r["error"] for r in env.get("results", []) if r.get("error")]


def _call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args}


# --- orchestrator ----------------------------------------------------------------------------

def _orchestrator(env: dict[str, Any]) -> dict[str, Any]:
    if env.get("task") == "summarize":
        parts = [a["answer"].removesuffix(" Confirm below.") for a in env.get("answers", []) if a.get("answer")]
        confirm = any(a.get("answer", "").endswith("Confirm below.") for a in env.get("answers", []))
        return {"reply": " ".join(parts) + (" Confirm below." if confirm else "")}
    message = env.get("message", "")
    remember = route(message)
    if remember:
        fact = remember.slots["fact"]
        return {"action": "remember", "remember": fact, "kind": remember.slots["kind"],
                "reply": f"Got it. I'll remember: {fact.rstrip('.')}."}
    has_file = bool(env.get("attachment"))
    wants_print = bool(_PRINT.search(message)) or (has_file and re.search(r"\bthis\b", message, re.I))
    wants_food = bool(_CANTEEN.search(message)) or any(n.lower() in message.lower() for n in env.get("context", {}).get("menu", []))
    wants_timetable = bool(_ATTENDANCE.search(message)) or (
        bool(_TIMETABLE.search(message)) and not (wants_print or wants_food))
    steps = []
    if wants_timetable:
        steps.append({"agent": "timetable", "task": message})
    if wants_food:
        steps.append({"agent": "canteen", "task": message})
    if wants_print:
        steps.append({"agent": "print", "task": message})
    if not steps:
        return {"action": "reply", "reply": CAPABILITIES}
    return {"action": "delegate", "steps": steps}


# --- timetable -------------------------------------------------------------------------------

def _subject(text: str, subjects: list[str]) -> str | None:
    lowered = text.lower()
    # Longest first, so "DBMS lab" wins over "DBMS".
    for name in sorted(subjects, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(name.lower())}(?![a-z])", lowered):
            return name
    return None


def _timetable(env: dict[str, Any]) -> dict[str, Any]:
    message = env.get("message", "")
    if not env.get("results"):
        subject = _subject(message, env.get("context", {}).get("subjects", []))
        if subject and re.search(r"\b(skip|miss|bunk|leave|absent)\b", message, re.I):
            day = _day(message)
            args = {"subject": subject, "day": day} if day else {"subject": subject, "miss": _count(message, "class") or 1}
            return {"tool_calls": [_call("attendance_what_if", **args)]}
        if _ATTENDANCE.search(message):
            return {"tool_calls": [_call("get_attendance_summary")]}
        if re.search(r"\b(free|break)\b", message, re.I):
            return {"tool_calls": [_call("get_free_slots")]}
        if re.search(r"\bnext (class|lab|period|lecture)\b", message, re.I):
            return {"tool_calls": [_call("get_next_class")]}
        return {"tool_calls": [_call("get_today_schedule", day=_day(message) or "today")]}
    return {"answer": _timetable_answer(env)}


def _timetable_answer(env: dict[str, Any]) -> str:
    if errors := _errors(env):
        return errors[-1]
    if what := _result(env, "attendance_what_if"):
        if "result" in what:
            return what["result"]
        when = f" {what['day']}" if what.get("day") else ""
        missed = what["classes_missed"]
        after = what["after_missing"]
        return (f"Skipping {what['subject']}{when} ({missed} class{'es' if missed != 1 else ''}) takes you from "
                f"{what['now']['percentage']} to {after['percentage']} ({after['attended']} of {after['held']}). "
                f"{after['statement']}.")
    if summary := _result(env, "get_attendance_summary"):
        below = [s for s in summary["subjects"] if s["status"] == "below"]
        if not below:
            return f"Every subject is at {summary['threshold']} or above."
        parts = [f"{s['subject']} {s['percentage']} ({s['statement'].lower()})" for s in below]
        return f"Below {summary['threshold']}: " + "; ".join(parts) + ". Everything else is fine."
    if nxt := _result(env, "get_next_class"):
        c = nxt.get("next_class")
        return f"Next: {c['label']} at {c['start']} in {c['room']}." if c else "No more classes today."
    if free := _result(env, "get_free_slots"):
        upcoming = [f"{s['label']} {s['start']}–{s['end']}" for s in free["free"] if s["status"] != "past"]
        return ("Still free today: " + ", ".join(upcoming) + ".") if upcoming else "No free time left today."
    if schedule := _result(env, "get_today_schedule"):
        items = schedule["items"]
        if isinstance(items, str):
            return f"{items} ({schedule['day']})"
        classes = [f"{c['label']} {c['start']} ({c['room']})" for c in items if c["kind"] == "class"]
        return f"Your classes {schedule['day']}: " + ", ".join(classes) + "."
    return "I couldn't find that in your timetable."


# --- print ------------------------------------------------------------------------------------

def _doc_words(env: dict[str, Any]) -> str:
    attachment = env.get("attachment") or {}
    name = re.sub(r"\.pdf$", "", attachment.get("file", ""), flags=re.I)
    return re.sub(r"[_\-]+", " ", name).strip() or "document"


def _print(env: dict[str, Any]) -> dict[str, Any]:
    message = env.get("message", "")
    results = env.get("results", [])
    if _CANCEL.search(message) and (code := re.search(r"\bP-?\d{1,5}\b", message, re.I)):
        if not results:
            return {"tool_calls": [_call("cancel_print_job", code=code[0].upper().replace("P", "P-", 1).replace("--", "-"))]}
        return {"answer": _errors(env)[-1] if _errors(env) else f"Cancelled {_result(env, 'cancel_print_job')['cancelled']}."}
    if _STATUS.search(message) and not env.get("attachment"):
        if not results:
            return {"tool_calls": [_call("get_print_status")]}
        jobs = _result(env, "get_print_status")["jobs"]
        return {"answer": jobs if isinstance(jobs, str) else "; ".join(f"{j['code']}: {j['status']}" for j in jobs) + "."}
    if not env.get("attachment"):
        return {"answer": "Attach the PDF you want printed (the paperclip in the ask bar), then ask again."}

    like_last_time = bool(re.search(r"like last time|same as (?:last time|before)|as before", message, re.I))
    if not results:
        calls = [_call("recall", query=f"when is my {_doc_words(env)} due")]
        if like_last_time:
            calls.insert(0, _call("print_settings_from_last_time"))
        if re.search(r"\bnext (lab|class)\b|before (my )?(lab|class)", message, re.I) or not _time(message):
            calls.append(_call("get_next_class"))
        return {"tool_calls": calls}

    if not _result(env, "propose_print_job"):
        if _results(env, "propose_print_job"):  # it failed: say why
            return {"answer": _errors(env)[-1]}
        last = (_result(env, "print_settings_from_last_time") or {}).get("last_time")
        last = last if isinstance(last, dict) else {}
        copies = _count(message, "cop") or last.get("copies") or 1
        color = bool(re.search(r"\bcolou?r\b", message, re.I)) or bool(last.get("color"))
        double = bool(re.search(r"double|both sides|duplex", message, re.I)) or bool(last.get("double_sided"))
        return {"tool_calls": [_call("propose_print_job", copies=copies, color=color, double_sided=double,
                                     deadline=_print_deadline(env, message))]}
    q = _result(env, "propose_print_job")
    copies = f"{q['copies']} cop{'y' if q['copies'] == 1 else 'ies'}"
    answer = f"{q['file']}, {copies}, {q['cost']}, needed by {q['deadline']} {q['deadline_day'].split(' (')[0]}."
    return {"answer": answer + (f" {q['warning']}" if q.get("warning") else "") + " Confirm below."}


def _print_deadline(env: dict[str, Any], message: str) -> str:
    """Explicit time > a day in the message > "next lab/class" > a due day from memory > next class."""
    if explicit := _time(message):
        return explicit
    if day := _day(message):
        return day
    if re.search(r"\bnext lab\b|before (?:my |the )?lab\b", message, re.I):
        return "next_lab"
    if re.search(r"\bnext class\b|before (?:my |the )?class\b", message, re.I):
        return "next_class"
    doc = _doc_words(env).lower().split()
    for memory in ((_result(env, "recall") or {}).get("memories") or []):
        text = memory["text"].lower() if isinstance(memory, dict) else ""
        if doc and any(word in text for word in doc if len(word) > 3) and (day := _day(text)):
            return day
    return "next_class"


# --- canteen ------------------------------------------------------------------------------------

def _canteen(env: dict[str, Any]) -> dict[str, Any]:
    message = env.get("message", "")
    results = env.get("results", [])
    if _CANCEL.search(message) and (token := re.search(r"\btoken\s*(\d+)", message, re.I)):
        if not results:
            return {"tool_calls": [_call("cancel_order", token=int(token[1]))]}
        return {"answer": _errors(env)[-1] if _errors(env) else f"Cancelled token {token[1]}."}
    if _STATUS.search(message) and re.search(r"\b(order|food|token)\b", message, re.I) and not re.search(r"\bget me\b", message, re.I):
        if not results:
            return {"tool_calls": [_call("get_order_status")]}
        orders = _result(env, "get_order_status")["orders"]
        return {"answer": orders if isinstance(orders, str) else "; ".join(f"Token {o['token']}: {o['status']}" for o in orders) + "."}

    menu = env.get("context", {}).get("menu", [])
    named = [name for name in sorted(menu, key=len, reverse=True) if name.lower() in message.lower()]
    pickup = _time(message) or "suggested"
    if not results:
        if named:
            return {"tool_calls": [_call("propose_order", items=[{"item": n, "qty": _count(message, n.split()[0].lower()) or 1} for n in named], pickup=pickup)]}
        return {"tool_calls": [_call("usual_order", day="today"), _call("recall", query="food I like to order")]}
    if not _result(env, "propose_order"):
        tried = _results(env, "propose_order")
        if tried and (len(tried) > 1 or tried[-1]["args"].get("pickup") == "suggested"):
            return {"answer": _errors(env)[-1]}
        if tried:  # the usual pickup time didn't work today (passed, or outside hours): use the suggestion
            return {"tool_calls": [_call("propose_order", items=tried[-1]["args"]["items"], pickup="suggested")]}
        usual = _result(env, "usual_order") or {}
        if usual.get("items"):
            when = pickup if pickup != "suggested" else (usual.get("usual_pickup") or "suggested")
            return {"tool_calls": [_call("propose_order", items=usual["items"], pickup=when)]}
        for memory in ((_result(env, "recall") or {}).get("memories") or []):
            text = memory["text"].lower() if isinstance(memory, dict) else ""
            liked = [n for n in menu if n.lower() in text]
            if liked:
                return {"tool_calls": [_call("propose_order", items=[{"item": liked[0], "qty": 1}], pickup=pickup)]}
        some = ", ".join(menu[:4])
        return {"answer": f"What would you like? Today there's {some} and more on the Canteen screen."}
    q = _result(env, "propose_order")
    usual = "Your usual: " if (_result(env, "usual_order") or {}).get("items") else ""
    return {"answer": f"{usual}{', '.join(q['items'])}, pickup {q['pickup']}, {q['total']}. Confirm below."}
