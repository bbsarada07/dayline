"""Canteen: student menu, quote, order, cancel; kitchen board, prep list, menu control."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth import Principal, current_principal, require_roles, require_student
from app.db import get_session
from app.errors import ApiError
from app.models import Staff, Student
from app.services import canteen_service

router = APIRouter(prefix="/canteen", tags=["canteen"])


class LineIn(BaseModel):
    menu_item_id: int
    qty: int = Field(ge=1, le=canteen_service.MAX_QTY_PER_ITEM)


class CartIn(BaseModel):
    items: list[LineIn] = Field(min_length=1, max_length=canteen_service.MAX_LINES)
    pickup_time: datetime | None = Field(default=None, description="College local time; default comes from the timetable")
    expected_total: int | None = Field(default=None, ge=0, description="Total (paise) the student saw; checked when paying")

    def lines(self) -> list[canteen_service.CartLine]:
        return [canteen_service.CartLine(l.menu_item_id, l.qty) for l in self.items]


class StatusIn(BaseModel):
    status: Literal["preparing", "ready", "collected"]


class MenuPatch(BaseModel):
    is_available: bool | None = None
    stock_today: int | None = Field(default=None, ge=0, le=1000)
    price: int | None = Field(default=None, ge=100, le=100_000, description="Paise")


@router.get("/menu")
def get_menu(principal: Principal = Depends(current_principal), session: Session = Depends(get_session)) -> dict:
    """Menu grouped data: every item with price, veg mark, stock and whether it can be ordered."""
    if principal.role not in ("student", "canteen"):
        raise ApiError(403, "forbidden", "Your account doesn't have access to this.")
    return {"categories": canteen_service.CATEGORY_ORDER, "items": [canteen_service.menu_item_view(i) for i in canteen_service.menu(session)]}


@router.post("/quote")
def quote(body: CartIn, student: Student = Depends(require_student), session: Session = Depends(get_session)) -> canteen_service.Quote:
    """Total, suggested pickup time and every pickup choice for a cart. Places nothing."""
    return canteen_service.quote(session, student, body.lines(), body.pickup_time)


@router.post("/orders")
def place_order(body: CartIn, student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Pay (demo payment) and place the order. Only called when the student presses "Confirm and pay"."""
    order = canteen_service.place_order(session, student, body.lines(), body.pickup_time, body.expected_total)
    return canteen_service.order_view(session, order)


@router.get("/orders/mine")
def my_orders(student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """The student's orders: active first (by pickup time), then recent finished ones."""
    return {"orders": canteen_service.list_mine(session, student.id)}


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: int, student: Student = Depends(require_student), session: Session = Depends(get_session)) -> dict:
    """Cancel the student's own order while it's still placed. Stock goes back."""
    return canteen_service.order_view(session, canteen_service.cancel(session, student.id, order_id))


@router.get("/board")
def board(_staff: Staff = Depends(require_roles("canteen")), session: Session = Depends(get_session)) -> dict:
    """Kitchen: today's tickets in Placed / Preparing / Ready columns."""
    return canteen_service.board(session)


@router.get("/prep-list")
def prep_list(_staff: Staff = Depends(require_roles("canteen")), session: Session = Depends(get_session)) -> dict:
    """Kitchen: quantity per item for each 15-minute pickup window (orders not yet ready)."""
    return canteen_service.prep_list(session)


@router.get("/suggested-prep")
def suggested_prep(_staff: Staff = Depends(require_roles("canteen")), session: Session = Depends(get_session)) -> dict:
    """Kitchen: average quantity on the same weekday over the last 4 weeks, beside today's pre-orders."""
    return canteen_service.suggested_prep(session)


@router.post("/orders/{order_id}/status")
def set_status(
    order_id: int, body: StatusIn, _staff: Staff = Depends(require_roles("canteen")), session: Session = Depends(get_session)
) -> dict:
    """Kitchen moves an order one step forward: preparing, ready, or collected (manual fallback)."""
    order = canteen_service.set_status(session, order_id, body.status)
    return canteen_service.order_view(session, order)


@router.patch("/menu/{item_id}")
def patch_menu(
    item_id: int, body: MenuPatch, _staff: Staff = Depends(require_roles("canteen")), session: Session = Depends(get_session)
) -> dict:
    """Kitchen: toggle availability, set today's stock, or edit the price."""
    item = canteen_service.update_menu_item(
        session, item_id, is_available=body.is_available, stock_today=body.stock_today, price=body.price
    )
    return canteen_service.menu_item_view(item)
