"""Isolation and search on the REAL Qdrant cluster, with Cloud Inference embeddings.

Skipped unless asked for:

    DAYLINE_LIVE_QDRANT=1 pytest tests/test_memory_live.py

Uses QDRANT_URL / QDRANT_API_KEY from backend/.env and a throwaway collection that
is deleted at the end. Never touches the app's real collection.
"""

import os
import uuid

import pytest

from app.config import settings
from app.errors import ApiError
from app.services import memory_service
from app.services.memory_backends import QdrantBackend

URL = os.environ.get("LIVE_QDRANT_URL", "")
KEY = os.environ.get("LIVE_QDRANT_API_KEY", "")

pytestmark = pytest.mark.skipif(
    os.environ.get("DAYLINE_LIVE_QDRANT") != "1" or not (URL and KEY),
    reason="live Qdrant test: set DAYLINE_LIVE_QDRANT=1 and QDRANT_URL/QDRANT_API_KEY in backend/.env",
)


@pytest.fixture
def live():
    collection = f"dayline_memory_test_{uuid.uuid4().hex[:8]}"
    backend = QdrantBackend.cloud(URL, KEY, collection, settings.memory_model)
    backend.ensure()
    memory_service.configure(backend)
    yield backend
    memory_service.drain()
    backend.client.delete_collection(collection)
    memory_service.configure(QdrantBackend.local())
    memory_service.backend().ensure()


def test_live_isolation_and_semantic_search(live):
    a, b = 101, 202
    mine = memory_service.remember(a, "My lab record is due Thursday", kind="fact", written_by="student")
    memory_service.remember(a, "I like masala dosa for breakfast", kind="preference", written_by="student")
    secret = memory_service.remember(b, "Secret: my lab record is due Thursday too", kind="fact", written_by="student")

    found = memory_service.recall(a, "When do I have to hand in my lab work?")
    assert found[0].id == mine.id  # meaning, not exact words, via the free Cloud Inference model
    assert all(m.id != secret.id for m in found)
    assert secret.id not in {m.id for m in memory_service.list_memories(a)}

    with pytest.raises(ApiError):
        memory_service.forget(a, secret.id)  # A can't delete B's memory by id
    assert [m.id for m in memory_service.list_memories(b)] == [secret.id]
    assert memory_service.forget_all(a) == 2
    assert [m.id for m in memory_service.list_memories(b)] == [secret.id]

    info = live.client.get_collection(live.collection)
    assert info.config.params.vectors.size == 384
    assert info.payload_schema["student_id"].params.is_tenant is True
