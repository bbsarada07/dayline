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


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "")
    if key and key != "change-me":
        return key
    print(
        f"[{APP_NAME}] SECRET_KEY is not set in .env; using a random key. "
        "Sessions will end when the server restarts.",
        file=sys.stderr,
    )
    return secrets.token_hex(32)


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
    )


settings = load_settings()
