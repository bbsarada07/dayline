"""Environment settings, read once from `.env` and the process environment.

Only deployment-level values live here. Values staff can change at runtime
(threshold, rates, demo time...) live in the Setting table instead.
"""

import json
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# The product name lives in one place, shared with the frontend.
APP_NAME: str = json.loads((REPO_DIR / "app.config.json").read_text(encoding="utf-8"))["name"]

# Asia/Kolkata has a fixed +05:30 offset and no daylight saving, so a fixed
# offset is exact and avoids needing the tzdata package on Windows.
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file without overriding real env vars."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    session_days: int
    cors_origins: list[str]
    serve_frontend: bool
    frontend_dist: Path
    upload_dir: Path
    port: int
    # Addendum D/F: public URL of the deployment (webhooks, secure cookies) and demo mode.
    public_base_url: str
    demo_mode: bool
    # Agents: "lyzr" or "mock" (keyword router). Phase 6 only uses the mock router.
    agent_mode: str
    # Qdrant shared memory (addendum G).
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str
    memory_model: str
    # Lyzr agents (addendum H, Phase 7). Agent ids come from scripts/setup_lyzr.py.
    lyzr_api_key: str
    lyzr_base_url: str
    lyzr_agent_ids: dict[str, str]
    lyzr_timeout_seconds: float
    lyzr_daily_call_limit: int
    # Shared secret for /api/agent-tools/* (sent with a per-run token).
    tool_key: str
    # Omi (addendum I, Phase 8): the private Omi app that sends notifications, and the wake phrase.
    omi_app_id: str
    omi_app_secret: str
    omi_api_base: str
    omi_wake_phrases: list[str]

    @property
    def https(self) -> bool:
        """True when the app is served over HTTPS (deployed), so cookies must be Secure."""
        return self.public_base_url.startswith("https://")


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "")
    if key and key != "change-me":
        return key
    # Hugging Face Spaces provides a stable per-Space signing secret.
    if os.environ.get("SPACE_SIGNING_SECRET"):
        return os.environ["SPACE_SIGNING_SECRET"]
    print(
        f"[{APP_NAME}] SECRET_KEY is not set in .env; using a random key. "
        "Sessions will end when the server restarts.",
        file=sys.stderr,
    )
    return secrets.token_hex(32)


def _public_base_url() -> str:
    """PUBLIC_BASE_URL, else the URL the host provides (Render, Hugging Face Spaces)."""
    explicit = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    if os.environ.get("RENDER_EXTERNAL_URL"):
        return os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
    if os.environ.get("SPACE_HOST"):
        return f"https://{os.environ['SPACE_HOST']}"
    return ""


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'dayline.db'}"),
        secret_key=_secret_key(),
        session_days=int(os.environ.get("SESSION_DAYS", "7")),
        cors_origins=[o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o],
        serve_frontend=os.environ.get("SERVE_FRONTEND", "false").lower() == "true",
        frontend_dist=Path(os.environ.get("FRONTEND_DIST", str(REPO_DIR / "frontend" / "dist"))),
        upload_dir=Path(os.environ.get("UPLOAD_DIR", str(BACKEND_DIR / "uploads"))),
        port=int(os.environ.get("PORT", "8000")),
        public_base_url=_public_base_url(),
        demo_mode=_flag("DEMO_MODE", False),
        agent_mode=os.environ.get("AGENT_MODE", "mock").strip().lower() or "mock",
        qdrant_url=os.environ.get("QDRANT_URL", "").strip().rstrip("/"),
        qdrant_api_key=os.environ.get("QDRANT_API_KEY", "").strip(),
        qdrant_collection=os.environ.get("QDRANT_COLLECTION", "").strip() or "dayline_memory",
        memory_model=os.environ.get("MEMORY_MODEL", "").strip() or "sentence-transformers/all-minilm-l6-v2",
        lyzr_api_key=os.environ.get("LYZR_API_KEY", "").strip(),
        lyzr_base_url=os.environ.get("LYZR_BASE_URL", "").strip().rstrip("/") or "https://agent-prod.studio.lyzr.ai/v3",
        lyzr_agent_ids={
            agent: os.environ.get(f"LYZR_{agent.upper()}_AGENT_ID", "").strip()
            for agent in ("orchestrator", "timetable", "print", "canteen", "listener")
        },
        lyzr_timeout_seconds=float(os.environ.get("LYZR_TIMEOUT_SECONDS", "20")),
        lyzr_daily_call_limit=int(os.environ.get("LYZR_DAILY_CALL_LIMIT", "100")),
        tool_key=os.environ.get("TOOL_KEY", "").strip(),
        omi_app_id=os.environ.get("OMI_APP_ID", "").strip(),
        omi_app_secret=os.environ.get("OMI_APP_SECRET", "").strip(),
        omi_api_base=os.environ.get("OMI_API_BASE", "").strip().rstrip("/") or "https://api.omi.me",
        omi_wake_phrases=[p.strip() for p in os.environ.get("OMI_WAKE_PHRASES", "hey dayline").split(",") if p.strip()],
    )


settings = load_settings()
