"""SQLModel tables (spec section 3).

Conventions: datetimes are timezone-aware and stored as UTC (SQLModel's
datetime type converts on write and returns aware UTC on read); money is
integer paise; times of day (timetable) are local college time.
"""

from datetime import date, datetime, time
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class Student(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    roll_no: str = Field(unique=True, index=True)
    name: str
    branch: str
    year: int
    section: str = Field(index=True)
    pin_hash: str
    card_uid: Optional[str] = Field(default=None, unique=True, index=True)
    interests: Optional[str] = None
    # The student's Omi user id (Phase 8): Omi webhooks carry it as ?uid=.
    omi_uid: Optional[str] = Field(default=None, unique=True, index=True)


class Staff(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    name: str
    pin_hash: str
    role: str  # canteen | print | admin


class Room(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    block: str
    floor: int
    directions: str = ""


class Subject(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    # Short form students actually use ("DBMS"); not in the original spec table,
    # added so the day line and the agents can use the common abbreviation.
    short_name: Optional[str] = None
    kind: str = "theory"  # theory | lab


class TimetableSlot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    section: str = Field(index=True)
    weekday: int = Field(index=True)  # 0 = Monday ... 6 = Sunday
    start_time: time
    end_time: time
    subject_id: int = Field(foreign_key="subject.id")
    room_id: int = Field(foreign_key="room.id")


class Attendance(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("student_id", "subject_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    subject_id: int = Field(foreign_key="subject.id")
    classes_held: int = 0
    classes_attended: int = 0


class MenuItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    price: int  # paise
    category: str
    is_veg: bool = True
    prep_minutes: int = 5
    stock_today: int = 0
    is_available: bool = True


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    token_no: int
    status: str = "placed"  # placed | preparing | ready | collected | cancelled | no_show
    pickup_time: datetime
    total: int  # paise
    payment_status: str = "unpaid"  # unpaid | paid_demo
    created_at: datetime
    ready_at: Optional[datetime] = None
    collected_at: Optional[datetime] = None


class OrderItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    menu_item_id: int = Field(foreign_key="menuitem.id")
    qty: int
    unit_price: int  # paise


class PrepLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    menu_item_id: int = Field(foreign_key="menuitem.id")
    date: date
    prepared_qty: int
    leftover_qty: int


class PrintJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    code: str = Field(unique=True)
    original_filename: str
    stored_path: Optional[str] = None
    pages: int
    copies: int
    color: bool = False
    double_sided: bool = False
    cost: int  # paise
    deadline: datetime
    est_ready_at: datetime
    status: str = "queued"  # queued | printing | ready | collected | cancelled | expired
    # Not in the spec table; mirrors Order.payment_status so both flows record payment the same way.
    payment_status: str = "unpaid"  # unpaid | paid_demo
    created_at: datetime
    ready_at: Optional[datetime] = None
    collected_at: Optional[datetime] = None


class PrintUpload(SQLModel, table=True):
    """A PDF uploaded but not yet turned into a print job.

    Not in the spec table: the upload step (and the ask bar's attachment in
    Phase 5) needs an id to quote against before anything is paid for.
    """

    id: str = Field(primary_key=True)  # random, unguessable
    student_id: int = Field(foreign_key="student.id", index=True)
    original_filename: str
    stored_path: str
    pages: int
    size_bytes: int
    created_at: datetime


class TapLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reader_id: str
    card_uid: str
    student_id: Optional[int] = Field(default=None, foreign_key="student.id")
    result: str
    created_at: datetime


class AgentMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    conversation_id: str = Field(index=True)
    role: str
    content: str
    trace_json: Optional[str] = None
    created_at: datetime


class OmiLog(SQLModel, table=True):
    """One Omi webhook call, for debugging. Never holds transcript text."""

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: Optional[int] = Field(default=None, foreign_key="student.id", index=True)
    kind: str  # transcript | memory | reply
    source: str  # omi | simulator
    uid_tail: Optional[str] = None  # last 4 characters of the uid, enough to tell ids apart
    segments: int = 0
    words: int = 0
    outcome: str  # ignored | buffered | listening | request | duplicate | rate_limited | stored | skipped | replied ...
    detail: Optional[str] = None  # plain explanation, no transcript text
    ms: int = 0
    created_at: datetime


class OmiProcessed(SQLModel, table=True):
    """Requests and conversations already handled, so a retried webhook is never handled twice."""

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    key: str = Field(unique=True, index=True)  # req:<fingerprint> | conv:<omi conversation id>
    text_hash: Optional[str] = Field(default=None, index=True)  # same request again within a minute
    created_at: datetime


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str  # JSON-encoded
