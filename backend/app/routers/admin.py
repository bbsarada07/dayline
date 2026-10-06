"""Admin controls: demo time and (so far) print settings. The full settings editor is Phase 6."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import clock
from app.auth import require_roles
from app.errors import ApiError
from app.events import hub
from app.models import Staff
from app.services import settings_service

router = APIRouter(prefix="/admin", tags=["admin"])


class DemoTimeIn(BaseModel):
    local: datetime  # college local time, e.g. "2026-10-05T12:20"


def _clock_payload() -> dict:
    return {"now": clock.local_now().isoformat(), "demo": clock.is_overridden()}


class PrintRates(BaseModel):
    bw_single: int = Field(ge=0, le=100_000)
    bw_double: int = Field(ge=0, le=100_000)
    colour_single: int = Field(ge=0, le=100_000)
    colour_double: int = Field(ge=0, le=100_000)


class SettingsIn(BaseModel):
    """Keys editable so far. Phase 6 opens up every setting."""

    print_rates: PrintRates | None = None
    print_seconds_per_page: int | None = Field(default=None, ge=1, le=120)


@router.get("/settings")
def get_settings(_admin: Staff = Depends(require_roles("admin"))) -> dict:
    """Every setting with its current value."""
    values = settings_service.get_all()
    values.pop("demo_pin", None)
    return values


@router.put("/settings")
def put_settings(body: SettingsIn, _admin: Staff = Depends(require_roles("admin"))) -> dict:
    """Update the given settings. Saving print rates marks them as real (no longer placeholders)."""
    changed = body.model_dump(exclude_none=True)
    if not changed:
        raise ApiError(400, "nothing_to_save", "There were no settings to save.")
    for key, value in changed.items():
        settings_service.set_value(key, value)
    if "print_rates" in changed:
        settings_service.set_value("print_rates_confirmed", True)
        changed["print_rates_confirmed"] = True
    hub.publish("settings.updated", {"keys": sorted(changed)})
    return get_settings(_admin)


@router.put("/demo-time")
def set_demo_time(body: DemoTimeIn, _admin: Staff = Depends(require_roles("admin"))) -> dict:
    """Start demo time at the given local date and time. The clock keeps ticking from there."""
    clock.set_demo_time(body.local)
    hub.publish("settings.updated", {"keys": ["clock_override"]})
    return _clock_payload()


@router.delete("/demo-time")
def clear_demo_time(_admin: Staff = Depends(require_roles("admin"))) -> dict:
    """Go back to real time."""
    clock.clear_demo_time()
    hub.publish("settings.updated", {"keys": ["clock_override"]})
    return _clock_payload()
