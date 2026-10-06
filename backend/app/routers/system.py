"""Deployment endpoints (addendum F): health check and demo reset."""

import os

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app import clock, demo
from app.config import APP_NAME, settings
from app.db import get_session
from app.models import Student
from app.agents import llm
from app.services import memory_service

router = APIRouter(tags=["system"])

LYZR_AGENT_VARS = (
    "LYZR_ORCHESTRATOR_AGENT_ID", "LYZR_TIMETABLE_AGENT_ID", "LYZR_PRINT_AGENT_ID",
    "LYZR_CANTEEN_AGENT_ID", "LYZR_LISTENER_AGENT_ID",
)


def _set(*names: str) -> bool:
    return all(os.environ.get(name, "").strip() for name in names)


def _qdrant_health() -> dict:
    memory = memory_service.status()
    return {
        "configured": memory["configured"],
        "connection_checked": memory["configured"],
        "ok": memory["ok"],
        "store": memory["backend"],
        "collection": memory["collection"],
    }


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    """Is the app up, and which integrations are configured? No login; never returns secret values.

    Qdrant is checked live. Lyzr reports which mode the agents run in and how many of
    today's Lyzr calls are used (no call is made). Omi's check comes with Phase 8.
    """
    try:
        students = session.exec(select(func.count(Student.id))).one()
        database = {"ok": True, "students": students}
    except Exception:
        database = {"ok": False, "students": 0}
    return {
        "status": "ok" if database["ok"] else "degraded",
        "app": APP_NAME,
        "demo_mode": settings.demo_mode,
        "now": clock.local_now(),
        "demo_time": clock.is_overridden(),
        "public_base_url": settings.public_base_url or None,
        "database": database,
        "qdrant": _qdrant_health(),
        "lyzr": {
            "configured": _set("LYZR_API_KEY"),
            "agents_configured": sum(_set(name) for name in LYZR_AGENT_VARS),
            "agents_expected": len(LYZR_AGENT_VARS),
            "mode": llm.mode(),
            "calls_today": llm.budget.used_today(),
            "daily_call_limit": llm.budget.limit,
            "connection_checked": False,
        },
        "omi": {"configured": _set("OMI_APP_ID", "OMI_APP_SECRET"), "connection_checked": False},
    }


@router.post("/demo/reset")
def reset_demo() -> dict:
    """Demo mode only: re-seed all data and put the clock back to Monday 12:20.

    Open to anyone using the demo (judges have no admin account); rate limited.
    """
    now = demo.reset_demo()
    return {"now": now, "demo": True}
