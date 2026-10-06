"""Login, logout and the current user."""

from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import (
    Principal,
    clear_session_cookie,
    current_principal,
    set_session_cookie,
    verify_pin,
)
from app.db import get_session
from app.errors import ApiError
from app.models import Staff, Student
from app.services import settings_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    kind: Literal["student", "staff"]
    username: str = Field(min_length=1, max_length=40, description="Roll number or staff username")
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


def me_payload(principal: Principal) -> dict:
    user = principal.user
    base = {"kind": principal.kind, "role": principal.role, "id": principal.id, "name": principal.name}
    if isinstance(user, Student):
        return base | {
            "roll_no": user.roll_no,
            "branch": user.branch,
            "year": user.year,
            "section": user.section,
            "card_linked": user.card_uid is not None,
            "card_uid": user.card_uid,  # the student's own ID barcode, shown on their ID card
        }
    return base | {"username": user.username}


@router.post("/login")
def login(body: LoginIn, response: Response, session: Session = Depends(get_session)) -> dict:
    """Log in a student (roll number + PIN) or staff member (username + PIN)."""
    username = body.username.strip()
    if body.kind == "student":
        user = session.exec(select(Student).where(Student.roll_no == username.upper())).first()
        wrong = "That roll number and PIN don't match. Check both and try again."
    else:
        user = session.exec(select(Staff).where(Staff.username == username.lower())).first()
        wrong = "That username and PIN don't match. Check both and try again."
    if user is None or not verify_pin(body.pin, user.pin_hash):
        raise ApiError(401, "wrong_credentials", wrong)
    set_session_cookie(response, body.kind, user.id)
    role = "student" if body.kind == "student" else user.role
    return me_payload(Principal(body.kind, user.id, role, user.name, user))


@router.post("/logout")
def logout(response: Response) -> dict:
    """End the session."""
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(current_principal)) -> dict:
    """The logged-in user's profile and role."""
    return me_payload(principal)


@router.get("/demo-accounts")
def demo_accounts(session: Session = Depends(get_session)) -> dict:
    """Seeded accounts for the login drawer. Empty unless demo mode is on."""
    if not settings_service.get("demo_mode"):
        return {"enabled": False, "pin": None, "students": [], "staff": []}
    students = session.exec(select(Student).order_by(Student.roll_no)).all()
    staff = session.exec(select(Staff).order_by(Staff.username)).all()
    return {
        "enabled": True,
        "pin": settings_service.get("demo_pin"),
        "students": [{"roll_no": s.roll_no, "name": s.name} for s in students],
        "staff": [{"username": s.username, "name": s.name, "role": s.role} for s in staff],
    }
