"""PIN hashing, signed session cookies and role guards.

The session cookie holds {kind, id, exp} signed with HMAC-SHA256 using
SECRET_KEY. Identity always comes from this cookie, never from a request body.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import timedelta

import bcrypt
from fastapi import Depends, Request, Response
from sqlmodel import Session

from app import clock
from app.config import settings
from app.db import get_session
from app.errors import ApiError
from app.models import Staff, Student

COOKIE_NAME = "dayline_session"


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pin.encode(), pin_hash.encode())
    except ValueError:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(kind: str, user_id: int) -> str:
    expires = clock.real_now() + timedelta(days=settings.session_days)
    payload = _b64(json.dumps({"k": kind, "id": user_id, "exp": int(expires.timestamp())}).encode())
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> tuple[str, int] | None:
    """Return (kind, id) for a valid, unexpired token, else None."""
    try:
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        data = json.loads(_unb64(payload))
        if data["exp"] < clock.real_now().timestamp() or data["k"] not in ("student", "staff"):
            return None
        return data["k"], int(data["id"])
    except (ValueError, KeyError, TypeError):
        return None


def set_session_cookie(response: Response, kind: str, user_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_token(kind, user_id),
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.https,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@dataclass
class Principal:
    kind: str  # student | staff
    id: int
    role: str  # student | canteen | print | admin
    name: str
    user: Student | Staff


def principal_from_token(token: str | None, session: Session) -> Principal | None:
    """Resolve a session token to the logged-in user, if any."""
    parsed = read_token(token) if token else None
    if parsed is None:
        return None
    kind, user_id = parsed
    if kind == "student":
        student = session.get(Student, user_id)
        return Principal("student", student.id, "student", student.name, student) if student else None
    staff = session.get(Staff, user_id)
    return Principal("staff", staff.id, staff.role, staff.name, staff) if staff else None


def current_principal(request: Request, session: Session = Depends(get_session)) -> Principal:
    principal = principal_from_token(request.cookies.get(COOKIE_NAME), session)
    if principal is None:
        raise ApiError(401, "not_logged_in", "Please log in to continue.")
    return principal


def require_student(principal: Principal = Depends(current_principal)) -> Student:
    """Guard: only students. Returns the logged-in Student."""
    if principal.role != "student":
        raise ApiError(403, "students_only", "This is only available to students.")
    return principal.user  # type: ignore[return-value]


def require_roles(*roles: str):
    """Guard factory: only staff with one of `roles`. Returns the Staff row."""

    def guard(principal: Principal = Depends(current_principal)) -> Staff:
        if principal.kind != "staff" or principal.role not in roles:
            raise ApiError(403, "forbidden", "Your account doesn't have access to this.")
        return principal.user  # type: ignore[return-value]

    return guard
