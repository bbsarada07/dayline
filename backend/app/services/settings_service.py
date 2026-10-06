"""Runtime settings stored in the Setting table, cached in memory.

Values are JSON. Missing keys fall back to DEFAULTS, so a fresh database
still works before the seed script has run.
"""

import json
import threading
from typing import Any

from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import Setting

DEFAULTS: dict[str, Any] = {
    # {"set_to": ISO UTC, "set_at": ISO UTC} or None. See app.clock.
    "clock_override": None,
    "attendance_threshold": 75,
    # Paise per page. Placeholders: replace with the real shop rates.
    "print_rates": {"bw_single": 200, "bw_double": 150, "colour_single": 1000, "colour_double": 800},
    # False until an admin saves real rates; the admin screen flags placeholders.
    "print_rates_confirmed": False,
    "print_seconds_per_page": 4,
    "canteen_hours": {"open": "08:30", "close": "16:30"},
    "no_show_minutes": 30,
    # Seeded from the DEMO_MODE environment variable (addendum D).
    "demo_mode": settings.demo_mode,
    "readers": [
        {"id": "canteen-1", "station": "canteen"},
        {"id": "print-1", "station": "print"},
    ],
    # College day bounds and breaks, local time. Placeholders.
    "college_day": {"start": "09:00", "end": "16:00"},
    "breaks": [
        {"name": "Short break", "start": "10:40", "end": "11:00"},
        {"name": "Lunch break", "start": "12:40", "end": "13:30"},
    ],
    # Shown in the login "Demo accounts" drawer only while demo_mode is on.
    "demo_pin": None,
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            values = dict(DEFAULTS)
            with Session(engine) as session:
                for row in session.exec(select(Setting)).all():
                    values[row.key] = json.loads(row.value)
            _cache = values
        return _cache


def get(key: str) -> Any:
    """Return one setting value (or its default)."""
    return _load().get(key, DEFAULTS.get(key))


def get_all() -> dict[str, Any]:
    """Return a copy of every setting."""
    return dict(_load())


def set_value(key: str, value: Any) -> None:
    """Persist one setting and refresh the cache."""
    if key not in DEFAULTS:
        raise KeyError(key)
    with Session(engine) as session:
        row = session.get(Setting, key)
        encoded = json.dumps(value)
        if row is None:
            session.add(Setting(key=key, value=encoded))
        else:
            row.value = encoded
            session.add(row)
        session.commit()
    invalidate()


def invalidate() -> None:
    """Drop the cache so the next read comes from the database."""
    global _cache
    with _lock:
        _cache = None
