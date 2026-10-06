"""Demo mode (addendum F): the app always opens at a known moment, and anyone can reset it.

With DEMO_MODE on, the clock starts at Monday 12:20 (this week's Monday, college time)
and runs forward in real time from the last reset. That moment is mid-morning on a
lab day: TOC is on, lunch is at 12:40 and the DBMS lab at 1:30, so every feature has
something to show. "Reset demo" re-seeds all data and puts the clock back.
"""

import threading
from datetime import datetime, time, timedelta

from app import clock
from app.config import IST, settings
from app.errors import ApiError
from app.events import hub

DEMO_TIME = time(12, 20)
RESET_COOLDOWN = timedelta(seconds=10)

_reset_lock = threading.Lock()
_last_reset: datetime | None = None


def demo_start() -> datetime:
    """This week's Monday at 12:20 college time (today, if today is Monday).

    Based on the wall clock, so the demo week is always the current one and the
    seeded "last 4 Mondays" of canteen history are genuinely in the past.
    """
    today = clock.real_now().astimezone(IST).date()
    monday = today - timedelta(days=today.weekday())
    return datetime.combine(monday, DEMO_TIME, tzinfo=IST)


def ensure_demo_clock() -> None:
    """On boot: in demo mode, start the demo clock if nobody has set one."""
    if settings.demo_mode and clock.override() is None:
        clock.set_demo_time(demo_start())


def reset_demo() -> datetime:
    """Re-seed every table, clear scan history and put the clock back to Monday 12:20.

    Shared by everyone using the demo, so it is rate limited. Returns the new demo time.
    (Phase 6 adds: clear the demo students' memories.)
    """
    global _last_reset
    from app.seed import seed  # imported here: seed imports most of the app
    from app.services import collect_service, omi_service

    if not settings.demo_mode:
        raise ApiError(403, "demo_off", "Resetting is only available in demo mode.")
    with _reset_lock:
        now = clock.real_now()
        if _last_reset and now - _last_reset < RESET_COOLDOWN:
            raise ApiError(429, "reset_too_soon", "The demo was reset a moment ago. Wait a few seconds and try again.")
        seed(demo=True)
        collect_service._recent.clear()
        omi_service.reset()  # requests half-heard before the reset
        _last_reset = now
    hub.publish("demo.reset", {"now": clock.local_now().isoformat()})
    return clock.local_now()
