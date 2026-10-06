"""The Listener agent: from one finished Omi conversation, the few facts Dayline should remember.

Only the extracted items are kept, never the transcript. A free keyword check runs first,
so conversations with nothing college-related never reach Lyzr (always-on recording would
otherwise spend credits on every chat about the weather).
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app import clock

from . import mock_router
from .llm import LLMError, MockClient, budget, default_client, pseudonym

log = logging.getLogger("dayline.omi")

MAX_ITEMS = 5
MAX_TRANSCRIPT = 4000
CATEGORIES = ("deadline", "print", "food", "timetable", "commitment")
NUDGE_CATEGORIES = ("deadline", "print")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

RELEVANT = re.compile(
    r"\b(due|deadline|submit|submission|print|printout|copies|exam|test|quiz|viva|lab|record|assignment|"
    r"project|class|lecture|cancel\w*|moved|reschedul\w*|postpon\w*|lunch|food|eat|hungry|like|love|prefer|"
    r"hate|allergic|remember|remind|promise|tomorrow|" + "|".join(WEEKDAYS) + r")\b",
    re.IGNORECASE,
)


@dataclass
class Item:
    text: str
    kind: str  # fact | preference
    category: str
    due: date | None

    @property
    def nudge(self) -> bool:
        """Worth a nudge on Today: something to print or hand in by a day."""
        return self.category in NUDGE_CATEGORIES and self.due is not None


@dataclass
class Extraction:
    items: list[Item]
    by: str  # lyzr | mock | skipped
    note: str | None = None


def resolve_due(value: Any, today: date | None = None) -> date | None:
    """'thursday' (the next one, today included), 'tomorrow', 'today' or YYYY-MM-DD -> a date."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().lower()
    today = today or clock.today()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    for index, name in enumerate(WEEKDAYS):
        if text.startswith(name[:3]):
            return today + timedelta(days=(index - today.weekday()) % 7)
    try:
        found = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return found if today - timedelta(days=1) <= found <= today + timedelta(days=60) else None


def envelope(conversation: dict[str, Any], subjects: list[str]) -> dict[str, Any]:
    """What the Listener sees: Omi's summary, action items and a shortened transcript."""
    structured = conversation.get("structured") or {}
    lines = []
    for segment in conversation.get("transcript_segments") or []:
        if isinstance(segment, dict) and str(segment.get("text", "")).strip():
            who = segment.get("speaker_name") or ("Student" if segment.get("is_user") else segment.get("speaker") or "Speaker")
            lines.append(f"{who}: {str(segment['text']).strip()}")
    transcript = "\n".join(lines)
    if len(transcript) > MAX_TRANSCRIPT:
        transcript = transcript[:MAX_TRANSCRIPT].rsplit("\n", 1)[0]
    now = clock.local_now()
    return {
        "now": f"{now:%A} {now.day} {now:%b}, {now.hour % 12 or 12}:{now.minute:02d} {'am' if now.hour < 12 else 'pm'}",
        "title": str(structured.get("title") or "")[:200],
        "overview": str(structured.get("overview") or "")[:1000],
        "action_items": [str(a.get("description", ""))[:200] for a in structured.get("action_items") or []
                         if isinstance(a, dict) and a.get("description")][:10],
        "transcript": transcript,
        "subjects": subjects,
    }


def relevant(env: dict[str, Any]) -> bool:
    text = " ".join([env["title"], env["overview"], *env["action_items"], env["transcript"]])
    return bool(RELEVANT.search(text))


def _clean(raw: Any) -> list[Item]:
    """Keep well-formed items only: known category, short text, at most five, no repeats."""
    items: list[Item] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        text = re.sub(r"\s+", " ", str(entry.get("text", ""))).strip().rstrip(".")
        category = str(entry.get("category", "")).lower()
        if not (3 <= len(text) <= 200) or category not in CATEGORIES or text.lower() in seen:
            continue
        seen.add(text.lower())
        kind = "preference" if entry.get("kind") == "preference" or category == "food" else "fact"
        items.append(Item(text[0].upper() + text[1:], kind, category, resolve_due(entry.get("due"))))
        if len(items) == MAX_ITEMS:
            break
    return items


def extract(student_id: int, conversation_id: str, env: dict[str, Any]) -> Extraction:
    """Run the Listener (Lyzr, else the keyword router) on one conversation envelope."""
    if not relevant(env):
        return Extraction([], "skipped", "Nothing about classes, deadlines, printing or food")
    client = default_client()
    if client.name != "mock":
        if not budget.take():
            note = "Used the offline listener (today's AI budget is used up)"
        else:
            try:
                reply = client.complete("listener", env, user_id=pseudonym(student_id), session_id=f"omi-{conversation_id}")
                if isinstance(reply.get("items"), list):
                    return Extraction(_clean(reply["items"]), "lyzr")
                note = "The Listener's answer didn't make sense, so the offline listener stepped in"
            except LLMError as exc:
                log.warning("Listener failed: %s", exc)
                note = "The Listener didn't answer, so the offline listener stepped in"
        return Extraction(_clean(MockClient().complete("listener", env, user_id="", session_id="")["items"]), "mock", note)
    return Extraction(_clean(mock_router.respond("listener", env)["items"]), "mock")
