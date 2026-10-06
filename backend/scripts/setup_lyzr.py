"""Create or update Dayline's Lyzr agents from app/agents/prompts, and print their ids.

    python -m scripts.setup_lyzr               # show what would change (reads only; no credits)
    python -m scripts.setup_lyzr --apply       # create or update the 5 agents (no credits)
    python -m scripts.setup_lyzr --check       # one real chat call to the Orchestrator (uses a little credit)

Needs LYZR_API_KEY and LYZR_TEMPLATE_AGENT_ID (an agent you made by hand in Lyzr Studio
with the model you want, e.g. GPT-4o-mini): its provider and credential settings are
copied, because the API doesn't list them. Agents are matched by name, so running it
again updates them instead of making duplicates. Run from the backend folder.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import prompts  # noqa: E402
from app.agents.llm import LLMError, LyzrClient  # noqa: E402
from app.config import settings  # noqa: E402

AGENTS = {
    "orchestrator": ("Dayline Orchestrator", "Routes a student's request to Dayline's agents and writes the reply."),
    "timetable": ("Dayline Timetable", "Schedule, free time and attendance for one student."),
    "print": ("Dayline Print", "Prepares print jobs at the campus print shop for the student to confirm."),
    "canteen": ("Dayline Canteen", "Prepares canteen orders for the student to confirm."),
    "listener": ("Dayline Listener", "Picks facts worth remembering out of Omi transcripts."),
}
COPIED = ("provider_id", "llm_credential_id", "top_p", "additional_model_params")


def _id(agent: dict[str, Any]) -> str | None:
    return agent.get("_id") or agent.get("id") or agent.get("agent_id")


def _list(http: httpx.Client) -> list[dict[str, Any]]:
    response = http.get("/agents/")
    response.raise_for_status()
    data = response.json()
    return data.get("agents", []) if isinstance(data, dict) else data


def _payload(key: str, template: dict[str, Any], model: str) -> dict[str, Any]:
    name, description = AGENTS[key]
    body = {field: template[field] for field in COPIED if template.get(field) is not None}
    body.update({
        "name": name,
        "description": description,
        "agent_role": description,
        "agent_goal": "Reply with one JSON object exactly as the instructions describe.",
        "agent_instructions": prompts.render(key),
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "store_messages": False,  # our backend keeps the conversation; Lyzr needn't
        "file_output": False,
        "features": [],
        "tools": [],
        "tool_configs": [],
        "managed_agents": [],
    })
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="create or update the agents")
    parser.add_argument("--check", action="store_true", help="send one test message to the Orchestrator")
    args = parser.parse_args()

    if not settings.lyzr_api_key:
        print("LYZR_API_KEY isn't set (backend/.env).")
        return 1
    http = httpx.Client(base_url=settings.lyzr_base_url, timeout=30,
                        headers={"x-api-key": settings.lyzr_api_key, "Content-Type": "application/json"})

    if args.check:
        if not settings.lyzr_agent_ids.get("orchestrator"):
            print("Set LYZR_ORCHESTRATOR_AGENT_ID first (run with --apply).")
            return 1
        client = LyzrClient(settings.lyzr_api_key, settings.lyzr_agent_ids, settings.lyzr_base_url,
                            settings.lyzr_timeout_seconds)
        envelope = {"message": "What's my attendance?", "now": "Monday 5 Oct, 12:20 pm", "attachment": None,
                    "memories": [], "context": {"subjects": ["DBMS", "OS"], "menu": ["Veg fried rice"]}, "history": []}
        try:
            print(json.dumps(client.complete("orchestrator", envelope, user_id="dayline-setup-check",
                                             session_id="setup-check"), indent=2))
        except LLMError as exc:
            print(f"The check failed: {exc}")
            return 1
        return 0

    template_id = os.environ.get("LYZR_TEMPLATE_AGENT_ID", "").strip()
    existing = {a.get("name"): a for a in _list(http)}
    if not template_id:
        others = [a for a in existing.values() if not str(a.get("name", "")).startswith("Dayline ")]
        if len(others) != 1:
            print("Set LYZR_TEMPLATE_AGENT_ID to the agent you made in Lyzr Studio "
                  f"(found {len(others)} candidate agents).")
            return 1
        template_id = _id(others[0])
    response = http.get(f"/agents/{template_id}")
    response.raise_for_status()
    template = response.json()
    model = os.environ.get("LYZR_MODEL", "").strip() or template.get("model") or "gpt-4o-mini"
    print(f"Template: {template.get('name')} ({template.get('provider_id')}, {template.get('model')}). "
          f"Agents will use {model}.")

    lines = []
    for key, (name, _) in AGENTS.items():
        body = _payload(key, template, model)
        found = existing.get(name)
        action = "update" if found else "create"
        if not args.apply:
            print(f"Would {action} {name} ({len(body['agent_instructions'])} characters of instructions).")
            continue
        if found:
            agent_id = _id(found)
            http.put(f"/agents/{agent_id}", json=body).raise_for_status()
        else:
            response = http.post("/agents/", json=body)
            response.raise_for_status()
            agent_id = response.json()["agent_id"]
        print(f"{action.capitalize()}d {name}: {agent_id}")
        lines.append(f"LYZR_{key.upper()}_AGENT_ID={agent_id}")

    if lines:
        print("\nAdd these to backend/.env (and to Render's environment):")
        print("\n".join(lines))
    else:
        print("\nNothing changed. Run again with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
