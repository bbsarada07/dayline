"""One LLM interface, two implementations: Lyzr (real agents) and mock (keyword router).

Agents answer with a JSON object (see prompts/*.md). The engine treats both clients the
same way, so mock mode produces the same trace events and proposals with no API key.
"""

import hashlib
import hmac
import json
import re
import threading
from datetime import date
from typing import Any, Protocol

import httpx

from app import clock
from app.config import settings


class LLMError(Exception):
    """The agent call failed (network, timeout, HTTP error, or a reply that isn't valid JSON)."""


class LLMClient(Protocol):
    name: str  # "lyzr" | "mock"

    def complete(self, agent: str, envelope: dict[str, Any], *, user_id: str, session_id: str) -> dict[str, Any]: ...


def parse_json(text: str) -> dict[str, Any]:
    """The JSON object in an agent's reply (tolerates ```json fences and text around it)."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("The agent's reply wasn't JSON.")
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError("The agent's reply wasn't valid JSON.") from exc
    if not isinstance(value, dict):
        raise LLMError("The agent's reply wasn't a JSON object.")
    return value


def pseudonym(student_id: int) -> str:
    """What Lyzr sees as the user: stable per student, but not the id, roll number or name."""
    digest = hmac.new(settings.secret_key.encode(), f"student:{student_id}".encode(), hashlib.sha256).hexdigest()
    return f"dayline-{digest[:16]}"


class Budget:
    """Caps real Lyzr calls per day (LYZR_DAILY_CALL_LIMIT) so credits can't run out unnoticed."""

    def __init__(self, limit: int):
        self.limit = limit
        self._day: date | None = None
        self._used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        """Use one call if the day's budget allows it."""
        today = clock.real_now().date()
        with self._lock:
            if self._day != today:
                self._day, self._used = today, 0
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    def used_today(self) -> int:
        with self._lock:
            return self._used if self._day == clock.real_now().date() else 0


budget = Budget(settings.lyzr_daily_call_limit)


class LyzrClient:
    """POST {base}/inference/chat/ with x-api-key; the reply text is in "response"."""

    name = "lyzr"

    def __init__(self, api_key: str, agent_ids: dict[str, str], base_url: str, timeout: float,
                 transport: httpx.BaseTransport | None = None):
        self.agent_ids = agent_ids
        self.http = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
        )

    def complete(self, agent: str, envelope: dict[str, Any], *, user_id: str, session_id: str) -> dict[str, Any]:
        agent_id = self.agent_ids.get(agent)
        if not agent_id:
            raise LLMError(f"No Lyzr agent id configured for {agent}.")
        body = {
            "user_id": user_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "message": json.dumps(envelope, ensure_ascii=False, default=str),
        }
        try:
            response = self.http.post("/inference/chat/", json=body)
        except httpx.TimeoutException as exc:
            raise LLMError("Lyzr didn't answer in time.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("Couldn't reach Lyzr.") from exc
        if response.status_code != 200:
            raise LLMError(f"Lyzr answered with HTTP {response.status_code}.")
        try:
            text = response.json().get("response", "")
        except ValueError as exc:
            raise LLMError("Lyzr's answer wasn't JSON.") from exc
        return parse_json(text if isinstance(text, str) else json.dumps(text))


class MockClient:
    """The keyword router, answering in exactly the same JSON shape as the real agents."""

    name = "mock"

    def complete(self, agent: str, envelope: dict[str, Any], *, user_id: str, session_id: str) -> dict[str, Any]:
        from app.agents import mock_router

        return mock_router.respond(agent, envelope)


def lyzr_ready() -> bool:
    ids = settings.lyzr_agent_ids
    return bool(settings.lyzr_api_key and all(ids[a] for a in ("orchestrator", "timetable", "print", "canteen")))


_lyzr: LyzrClient | None = None
_lyzr_lock = threading.Lock()


def default_client() -> LLMClient:
    """Lyzr when AGENT_MODE=lyzr and it's fully configured; the mock otherwise."""
    global _lyzr
    if settings.agent_mode == "lyzr" and lyzr_ready():
        with _lyzr_lock:
            if _lyzr is None:  # one HTTP client (connection pool) for the whole app
                _lyzr = LyzrClient(settings.lyzr_api_key, settings.lyzr_agent_ids, settings.lyzr_base_url,
                                   settings.lyzr_timeout_seconds)
            return _lyzr
    return MockClient()


def mode() -> str:
    """'lyzr' or 'mock', for the health check and the ask panel."""
    return "lyzr" if settings.agent_mode == "lyzr" and lyzr_ready() else "mock"
