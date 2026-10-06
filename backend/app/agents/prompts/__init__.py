"""Agent instructions. The Lyzr agents use these as their instructions (scripts/setup_lyzr.py)."""

import json
from pathlib import Path

from app.agents.tools import describe

HERE = Path(__file__).parent


def render(agent: str) -> str:
    """The instructions for one agent, with its tool list filled in."""
    text = (HERE / f"{agent}.md").read_text(encoding="utf-8")
    if "{{SUBAGENT}}" in text:
        text = text.replace("{{SUBAGENT}}", (HERE / "subagent.md").read_text(encoding="utf-8"))
        tools = "\n".join(json.dumps(t, ensure_ascii=False) for t in describe(agent))
        text = text.replace("{{TOOLS}}", tools)
    return text.strip() + "\n"
