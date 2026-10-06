"""The student's shared memory: list, search, add a note, delete (addendum G)."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.agents import mock_router
from app.auth import require_student
from app.errors import ApiError
from app.models import Student
from app.services import memory_service

router = APIRouter(prefix="/memory", tags=["memory"])


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=600, description='e.g. "Remember that my lab record is due Thursday"')


@router.get("")
def memories(
    q: str | None = Query(default=None, max_length=200, description="Search by meaning; omit to list newest first"),
    student: Student = Depends(require_student),
) -> dict:
    """The student's memories, newest first, or the best matches for `q` (the top match is marked as used)."""
    found = (memory_service.recall(student.id, q, limit=10, mark="top") if q and q.strip()
             else memory_service.list_memories(student.id))
    return {"status": memory_service.status(), "query": q, "memories": [asdict(m) for m in found]}


@router.get("/status")
def status(_student: Student = Depends(require_student)) -> dict:
    """Whether memories are in Qdrant or the temporary store."""
    return memory_service.status()


@router.post("/notes")
def add_note(body: NoteIn, student: Student = Depends(require_student)) -> dict:
    """ "Remember that ..." through the mock router: stores the fact, written by the student."""
    intent = mock_router.route(body.text)
    if intent is None or intent.name != "remember":
        raise ApiError(422, "not_a_memory", 'Start with "Remember that…", for example: Remember that my lab record is due Thursday.')
    memory = memory_service.remember(student.id, intent.slots["fact"], kind=intent.slots["kind"], written_by="student")
    return asdict(memory)


@router.delete("/{memory_id}")
def delete_one(memory_id: str, student: Student = Depends(require_student)) -> dict:
    """Delete one of the student's own memories."""
    memory_service.forget(student.id, memory_id)
    return {"deleted": 1}


@router.delete("")
def delete_all(student: Student = Depends(require_student)) -> dict:
    """Delete all of the student's memories."""
    return {"deleted": memory_service.forget_all(student.id)}
