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
    )


settings = load_settings()
