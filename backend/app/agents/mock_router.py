"""Keyword router used when AGENT_MODE=mock, and as the fallback when the real agents fail.

Phase 6 recognises one intent: "remember that ..." (and close variants). Phase 7 adds
the timetable, print and canteen intents.
"""

import re
from dataclasses import dataclass, field

_REMEMBER = re.compile(
    r"^\s*(?:hey\s+dayline[,\s]+)?(?:please\s+)?(?:remember|note(?:\s+down)?|don'?t\s+forget|keep\s+in\s+mind)"
    r"(?:\s+that)?[\s,:]+(?P<fact>.+?)\s*[.!]*\s*$",
    re.IGNORECASE | re.DOTALL,
)
_PREFERENCE = re.compile(
    r"\b(prefer|like|love|hate|dislike|don'?t\s+like|favou?rite|allergic|vegetarian|vegan|no\s+onion|spicy|usual)\b",
    re.IGNORECASE,
)


@dataclass
class Intent:
    name: str
    slots: dict[str, str] = field(default_factory=dict)


def route(text: str) -> Intent | None:
    """The intent behind a message, or None if the mock router doesn't recognise it."""
    match = _REMEMBER.match(text or "")
    if match and match.group("fact").strip():
        fact = match.group("fact").strip()
        kind = "preference" if _PREFERENCE.search(fact) else "fact"
        return Intent("remember", {"fact": fact[0].upper() + fact[1:], "kind": kind})
    return None
