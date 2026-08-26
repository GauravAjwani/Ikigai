from __future__ import annotations

import math

import numpy as np

from precedent.gemini_client import embed
from precedent.graph import graph
from precedent.schemas import DerivedDecision, RankedCandidate, SlackMessage
from precedent.slack_store import SlackStore


def _cos(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    n = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if n == 0:
        return 0.0
    return float(np.dot(va, vb) / n)


def retrieve(
    *,
    store: SlackStore,
    trigger: str,
    probes: list[str],
    max_searches: int,
) -> list[RankedCandidate]:
    found: dict[str, RankedCandidate] = {}
    queries = [q for q in probes if q][:max_searches]
    for q in queries:
        for m in store.search(q, limit=6):
            found[m.permalink or m.ts] = RankedCandidate(
                permalink=m.permalink,
                channel_id=m.channel_id,
                thread_ts=m.thread_ts,
                channel_name=m.channel_name,
                snippet=m.text[:280],
                score=0.0,
                source="slack",
                at=m.at,
            )
    for d in graph().list():
        key = d.permalink
        if key in found:
            found[key].source = "graph"
            found[key].decision_id = d.decision_id
            found[key].graph_status = d.status
            if not found[key].snippet:
                found[key].snippet = d.label
        else:
            found[key] = RankedCandidate(
                permalink=d.permalink,
                channel_id=d.channel_id,
                thread_ts=d.thread_ts,
                snippet=d.label,
                score=0.0,
                source="graph",
                decision_id=d.decision_id,
                graph_status=d.status,
            )
    return list(found.values())


def rank(trigger: str, candidates: list[RankedCandidate], limit: int) -> list[RankedCandidate]:
    if not candidates:
        return []
    # Transient embed-rank-destroy. Vectors never leave this call.
    corpus = [trigger] + [c.snippet for c in candidates]
    vectors = embed(corpus, stage="rank")
    if len(vectors) != len(corpus):
        return candidates[:limit]
    qv = vectors[0]
    scored = []
    for cand, vec in zip(candidates, vectors[1:], strict=False):
        cand.score = round(_cos(qv, vec), 4)
        scored.append(cand)
    scored.sort(key=lambda c: -c.score)
    return scored[:limit]
