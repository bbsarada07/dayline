"""The one clock service. Feature code must read time only through here.

Demo time is stored as the moment it was set (`set_at`, real time) and the
time it was set to (`set_to`). From then on the demo clock keeps ticking:
now = set_to + (real now - set_at). That keeps queues, ready times and
no-show checks moving during a demo.
"""

from datetime import date, datetime, timezone

from app.config import IST
from app.services import settings_service


def _real_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def real_now() -> datetime:
    """Wall-clock UTC time, ignoring demo time.

    Only for security timing (session expiry, rate limits), which must not
    move when an admin changes demo time.
    """
    return _real_utc_now()


def override() -> dict | None:
    """Return the active demo-time override, or None."""
    value = settings_service.get("clock_override")
    if not value or not value.get("set_to") or not value.get("set_at"):
        return None
    return value


def now() -> datetime:
    """Current time as an aware UTC datetime (demo time when set)."""
    real = _real_utc_now()
    active = override()
    if active is None:
        return real
    return _parse_utc(active["set_to"]) + (real - _parse_utc(active["set_at"]))


def local_now() -> datetime:
    """Current time in college local time (Asia/Kolkata)."""
    return now().astimezone(IST)


def today() -> date:
    """Today's date in college local time."""
    return local_now().date()


def is_overridden() -> bool:
    return override() is not None


def set_demo_time(local: datetime) -> None:
    """Start demo time at `local` (naive values are read as college time)."""
    if local.tzinfo is None:
        local = local.replace(tzinfo=IST)
    settings_service.set_value(
        "clock_override",
        {
            "set_to": local.astimezone(timezone.utc).isoformat(),
            "set_at": _real_utc_now().isoformat(),
        },
    )


def clear_demo_time() -> None:
    settings_service.set_value("clock_override", None)


def to_utc(value: datetime) -> datetime:
    """Normalise an aware datetime to UTC for storage."""
    return value.astimezone(timezone.utc)
