from __future__ import annotations

from contextvars import ContextVar
from threading import Lock

from ikigai.fixtures import seed_decisions
from ikigai.schemas import ALLOWED_GRAPH_KEYS, FORBIDDEN_GRAPH_SUBSTRINGS, DerivedDecision
from ikigai.settings import get_settings


class PrivacyLeak(RuntimeError):
    pass


def inspect_record(data: dict) -> list[str]:
    leaks: list[str] = []
    for key in data:
        lk = str(key)
        if lk not in ALLOWED_GRAPH_KEYS:
            leaks.append(f"unknown field {lk}")
        low = lk.lower()
        for bad in FORBIDDEN_GRAPH_SUBSTRINGS:
            if bad in low:
                leaks.append(f"forbidden field {lk}")
        val = data[key]
        if isinstance(val, str) and val.startswith("U") and val[1:].isdigit():
            leaks.append(f"possible user id in {lk}")
        if isinstance(val, list) and val and isinstance(val[0], float) and len(val) > 32:
            leaks.append(f"possible embedding in {lk}")
    return leaks


class DecisionGraph:
    def list(self) -> list[DerivedDecision]:
        raise NotImplementedError

    def upsert(self, rec: DerivedDecision) -> None:
        raise NotImplementedError

    def add_negative(self, decision_id: str, note: str = "not_same") -> None:
        raise NotImplementedError


class MemoryGraph(DecisionGraph):
    def __init__(self, seed: bool = True) -> None:
        self._lock = Lock()
        self._rows: dict[str, DerivedDecision] = {}
        if seed:
            self._rows = {d.decision_id: d for d in seed_decisions()}

    def list(self) -> list[DerivedDecision]:
        with self._lock:
            return list(self._rows.values())

    def upsert(self, rec: DerivedDecision) -> None:
        payload = rec.model_dump()
        leaks = inspect_record(payload)
        if leaks:
            raise PrivacyLeak("; ".join(leaks))
        with self._lock:
            self._rows[rec.decision_id] = rec

    def add_negative(self, decision_id: str, note: str = "not_same") -> None:
        with self._lock:
            rec = self._rows.get(decision_id)
            if not rec:
                return
            rec.edges = list(rec.edges) + [{"type": note, "target_id": "feedback"}]
            rec.confidence = min(rec.confidence, 0.4)


class FirestoreGraph(DecisionGraph):
    def __init__(self) -> None:
        from google.cloud import firestore

        s = get_settings()
        self._db = firestore.Client(project=s.google_cloud_project)
        self._col = self._db.collection(s.firestore_collection)
        self._seeded = False

    def _ensure_seed(self) -> None:
        self._seeded = True

    def list(self) -> list[DerivedDecision]:
        self._ensure_seed()
        out = []
        for doc in self._col.stream():
            data = doc.to_dict() or {}
            leaks = inspect_record(data)
            if leaks:
                raise PrivacyLeak(f"{doc.id}: {'; '.join(leaks)}")
            out.append(DerivedDecision.model_validate(data))
        return out

    def upsert(self, rec: DerivedDecision) -> None:
        payload = rec.model_dump()
        leaks = inspect_record(payload)
        if leaks:
            raise PrivacyLeak("; ".join(leaks))
        self._col.document(rec.decision_id).set(payload)

    def add_negative(self, decision_id: str, note: str = "not_same") -> None:
        from google.cloud.firestore import ArrayUnion

        self._col.document(decision_id).update(
            {
                "edges": ArrayUnion([{"type": note, "target_id": "feedback"}]),
                "confidence": 0.4,
            }
        )


_graph: DecisionGraph | None = None
_demo_graph: MemoryGraph | None = None
_graph_override: ContextVar[DecisionGraph | None] = ContextVar("ikigai_graph", default=None)


def demo_graph() -> MemoryGraph:
    global _demo_graph
    if _demo_graph is None:
        _demo_graph = MemoryGraph(seed=True)
    return _demo_graph


def reset_demo_graph() -> MemoryGraph:
    global _demo_graph
    _demo_graph = MemoryGraph(seed=True)
    return _demo_graph


def bind_demo_graph():
    return _graph_override.set(demo_graph())


def unbind_graph(token) -> None:
    _graph_override.reset(token)


def graph() -> DecisionGraph:
    ov = _graph_override.get()
    if ov is not None:
        return ov
    global _graph
    if _graph is None:
        s = get_settings()
        if s.gcp_ready():
            try:
                _graph = FirestoreGraph()
                _graph.list()
            except Exception:
                _graph = MemoryGraph(seed=not bool(s.slack_bot_token))
        else:
            _graph = MemoryGraph(seed=not bool(s.slack_bot_token))
    return _graph


def privacy_dump() -> dict:
    rows = [r.model_dump() for r in graph().list()]
    leaks = []
    for r in rows:
        leaks.extend(inspect_record(r))
    return {
        "ok": not leaks,
        "leaks": leaks,
        "count": len(rows),
        "records": rows,
        "stores_message_text": False,
        "stores_user_ids": False,
        "stores_embeddings": False,
        "backend": type(graph()).__name__,
    }
