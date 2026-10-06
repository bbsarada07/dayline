"""Tool endpoint for agents hosted outside our backend (addendum H).

POST /api/agent-tools/{name} with the tool's arguments as the JSON body and two headers:
  X-Tool-Key: the shared TOOL_KEY (proves the caller is our agent platform);
  X-Run-Token: the live run's token (says which student, without the caller knowing who).
There is no student id anywhere in the request: the run token decides. The endpoint is
off when TOOL_KEY isn't set. Our own engine calls the same tools in-process.
"""

import hmac
from typing import Any

from fastapi import APIRouter, Body, Header
from sqlmodel import Session

from app.agents import runs
from app.agents.tools import ACCESS, REGISTRY, RunContext, ToolError, run_tool
from app.config import settings
from app.db import engine
from app.errors import ApiError
from app.models import Student

router = APIRouter(prefix="/agent-tools", tags=["agent"])


@router.post("/{name}")
def call_tool(
    name: str,
    args: dict[str, Any] = Body(default_factory=dict),
    x_tool_key: str | None = Header(default=None),
    x_run_token: str | None = Header(default=None),
    x_agent: str | None = Header(default=None, description="timetable | print | canteen"),
) -> dict:
    """Run one tool for the run's student. 401 without a valid key and a live run token."""
    if not settings.tool_key:
        raise ApiError(404, "not_found", "That API endpoint doesn't exist.")
    if not x_tool_key or not hmac.compare_digest(x_tool_key, settings.tool_key):
        raise ApiError(401, "bad_tool_key", "Missing or wrong tool key.")
    run = runs.by_token(x_run_token)
    if run is None:
        raise ApiError(401, "bad_run_token", "This run has ended or the run token is wrong.")
    if name not in REGISTRY:
        raise ApiError(404, "unknown_tool", f"There is no tool called {name}.")
    agent = x_agent if x_agent in ACCESS else None
    if agent and name not in ACCESS[agent]:
        raise ApiError(403, "tool_not_allowed", f"The {agent} agent can't use {name}.")
    with Session(engine) as session:
        student = session.get(Student, run.student_id)
        if student is None:
            raise ApiError(401, "bad_run_token", "This run has ended or the run token is wrong.")
        try:
            tool, result = run_tool(RunContext(session, student, run, agent or "orchestrator"), name, args)
        except ToolError as exc:
            run.send("tool_called", {"agent": agent or REGISTRY[name].owner, "tool": name, "label": str(exc), "ok": False})
            raise ApiError(422, "tool_failed", str(exc))
    run.send("tool_called", {"agent": agent or tool.owner, "tool": name, "label": tool.label(tool.args.model_validate(args)),
                             "ok": True})
    return {"result": result}
