"""Where memories live: Qdrant (normal), or an in-process store when Qdrant can't be reached.

Both backends take the student id on every call and filter by it themselves, so no
caller can ever read, change or delete another student's memories.
"""

import hashlib
import math
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from qdrant_client import QdrantClient, models

VECTOR_SIZE = 384  # sentence-transformers/all-minilm-l6-v2


@dataclass
class Stored:
    id: str
    payload: dict[str, Any]
    score: float | None = None


class Backend(Protocol):
    name: str  # "qdrant" | "temporary"

    def ensure(self) -> None: ...
    def upsert(self, point_id: str, text: str, payload: dict[str, Any]) -> None: ...
    def search(self, student_id: int, query: str, limit: int, **match: str) -> list[Stored]: ...
    def scroll(self, student_id: int, limit: int, **match: str) -> list[Stored]: ...
    def delete(self, student_id: int, point_id: str) -> bool: ...
    def delete_all(self, student_id: int) -> int: ...
    def mark_used(self, student_id: int, point_ids: list[str], payload: dict[str, Any]) -> None: ...
    def ping(self) -> None: ...


# --- offline embedder (tests and the temporary store) -----------------------------

_WORD = re.compile(r"[a-z0-9]+")


def hash_embed(text: str) -> list[float]:
    """A small, deterministic bag-of-words embedding (word stems plus letter trigrams).

    Not a language model: it's for tests and the temporary store, where texts that
    share words still find each other. Real deployments embed with the Qdrant model.
    """
    vector = [0.0] * VECTOR_SIZE
    features: list[str] = []
    for word in _WORD.findall(text.lower()):
        stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
        features.append(f"w:{stem}")
        padded = f"#{stem}#"
        features.extend(f"t:{padded[i:i + 3]}" for i in range(len(padded) - 2))
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % VECTOR_SIZE
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


# --- Qdrant -----------------------------------------------------------------------

class QdrantBackend:
    """Qdrant collection with one tenant per student (payload index `student_id`, is_tenant).

    `embed` turns text into what Qdrant stores: by default a `models.Document`, which
    Qdrant Cloud Inference embeds server-side with the free model; tests pass
    `hash_embed` and an in-memory client instead.
    """

    name = "qdrant"

    def __init__(self, client: QdrantClient, collection: str, embed: Callable[[str], Any]):
        self.client = client
        self.collection = collection
        self.embed = embed

    @classmethod
    def cloud(cls, url: str, api_key: str, collection: str, model: str) -> "QdrantBackend":
        client = QdrantClient(url=url, api_key=api_key, cloud_inference=True, timeout=8)
        return cls(client, collection, lambda text: models.Document(text=text, model=model))

    @classmethod
    def local(cls, collection: str = "dayline_memory_test") -> "QdrantBackend":
        """In-process Qdrant (no server) with the offline embedder. Used by the tests."""
        return cls(QdrantClient(":memory:"), collection, hash_embed)

    def ensure(self) -> None:
        """Create the collection and payload indexes if they don't exist. Safe to repeat."""
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
                # Per-student index only: every search is filtered to one student.
                hnsw_config=models.HnswConfigDiff(payload_m=16, m=0),
            )
        indexes: dict[str, Any] = {
            "student_id": models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True),
            "created_ts": models.PayloadSchemaType.INTEGER,
            "kind": models.PayloadSchemaType.KEYWORD,
            "written_by": models.PayloadSchemaType.KEYWORD,
        }
        existing = self.client.get_collection(self.collection).payload_schema or {}
        for field, schema in indexes.items():
            if field not in existing:
                self.client.create_payload_index(self.collection, field_name=field, field_schema=schema)

    @staticmethod
    def _for_student(student_id: int, *extra: models.Condition, **match: str) -> models.Filter:
        """The only way a filter is built: always this student, optionally narrowed further."""
        conditions: list[models.Condition] = [
            models.FieldCondition(key="student_id", match=models.MatchValue(value=str(student_id)))
        ]
        conditions += [models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in match.items()]
        conditions += list(extra)
        return models.Filter(must=conditions)

    def upsert(self, point_id: str, text: str, payload: dict[str, Any]) -> None:
        self.client.upsert(self.collection, points=[models.PointStruct(id=point_id, vector=self.embed(text), payload=payload)])

    def search(self, student_id: int, query: str, limit: int, **match: str) -> list[Stored]:
        result = self.client.query_points(
            self.collection, query=self.embed(query), query_filter=self._for_student(student_id, **match),
            limit=limit, with_payload=True,
        )
        return [Stored(str(p.id), p.payload or {}, p.score) for p in result.points]

    def scroll(self, student_id: int, limit: int, **match: str) -> list[Stored]:
        rows, _ = self.client.scroll(
            self.collection, scroll_filter=self._for_student(student_id, **match), limit=limit,
            order_by=models.OrderBy(key="created_ts", direction=models.Direction.DESC), with_payload=True,
        )
        return [Stored(str(r.id), r.payload or {}) for r in rows]

    def _count(self, flt: models.Filter) -> int:
        return self.client.count(self.collection, count_filter=flt, exact=True).count

    def delete(self, student_id: int, point_id: str) -> bool:
        # Student AND id: guessing another student's id deletes nothing.
        flt = self._for_student(student_id, models.HasIdCondition(has_id=[point_id]))
        if not self._count(flt):
            return False
        self.client.delete(self.collection, points_selector=models.FilterSelector(filter=flt))
        return True

    def delete_all(self, student_id: int) -> int:
        flt = self._for_student(student_id)
        count = self._count(flt)
        self.client.delete(self.collection, points_selector=models.FilterSelector(filter=flt))
        return count

    def mark_used(self, student_id: int, point_ids: list[str], payload: dict[str, Any]) -> None:
        if point_ids:
            flt = self._for_student(student_id, models.HasIdCondition(has_id=point_ids))
            self.client.set_payload(self.collection, payload=payload, points=models.FilterSelector(filter=flt))

    def ping(self) -> None:
        self.client.get_collection(self.collection)


# --- temporary in-process store ---------------------------------------------------------

class TemporaryBackend:
    """Used when Qdrant is missing or unreachable. Same behaviour, kept only until restart."""

    name = "temporary"

    def __init__(self) -> None:
        self._points: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def ensure(self) -> None:
        return None

    def _mine(self, student_id: int, **match: str) -> list[tuple[str, dict[str, Any]]]:
        sid = str(student_id)
        return [
            (pid, p) for pid, p in self._points.items()
            if p["payload"].get("student_id") == sid and all(p["payload"].get(k) == v for k, v in match.items())
        ]

    def upsert(self, point_id: str, text: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._points[point_id] = {"vector": hash_embed(text), "payload": dict(payload)}

    def search(self, student_id: int, query: str, limit: int, **match: str) -> list[Stored]:
        q = hash_embed(query)
        with self._lock:
            scored = [(sum(a * b for a, b in zip(q, p["vector"])), pid, p) for pid, p in self._mine(student_id, **match)]
        scored.sort(key=lambda s: s[0], reverse=True)
        return [Stored(pid, dict(p["payload"]), score) for score, pid, p in scored[:limit]]

    def scroll(self, student_id: int, limit: int, **match: str) -> list[Stored]:
        with self._lock:
            mine = self._mine(student_id, **match)
        mine.sort(key=lambda item: item[1]["payload"].get("created_ts", 0), reverse=True)
        return [Stored(pid, dict(p["payload"])) for pid, p in mine[:limit]]

    def delete(self, student_id: int, point_id: str) -> bool:
        with self._lock:
            point = self._points.get(point_id)
            if point is None or point["payload"].get("student_id") != str(student_id):
                return False
            del self._points[point_id]
            return True

    def delete_all(self, student_id: int) -> int:
        with self._lock:
            ids = [pid for pid, _ in self._mine(student_id)]
            for pid in ids:
                del self._points[pid]
            return len(ids)

    def mark_used(self, student_id: int, point_ids: list[str], payload: dict[str, Any]) -> None:
        with self._lock:
            for pid in point_ids:
                point = self._points.get(pid)
                if point and point["payload"].get("student_id") == str(student_id):
                    point["payload"].update(payload)

    def ping(self) -> None:
        return None
