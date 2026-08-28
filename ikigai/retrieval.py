from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ikigai.gemini_client import embed
from ikigai.graph import graph
from ikigai.notes import notable, slack_permalink
from ikigai.prefilter import is_chatter, is_decision_call, looks_decisionish, tokenize
from ikigai.schemas import RankedCandidate
from ikigai.slack_store import SlackStore

_KEEP = 28
_RANK = 8
_THREADS = 6


def _cos(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    n = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if n == 0:
        return 0.0
    return float(np.dot(va, vb) / n)


def _live_bot() -> bool:
    from ikigai.settings import get_settings

    tok = (get_settings().slack_bot_token or "").strip()
    return bool(tok) and not tok.startswith("xoxb-not-set")


def _needed(text: str, qtok: set[str]) -> bool:
    if not (text or "").strip() or is_chatter(text):
        return False
    if looks_decisionish(text) or is_decision_call(text):
        return True
    return bool(qtok) and bool(qtok & tokenize(text))


def retrieve(
    *,
    store: SlackStore,
    trigger: str,
    probes: list[str],
    max_searches: int,
    channel_id: str = "",
    all_channels: bool = False,
) -> list[RankedCandidate]:
    """Only decision-like or query-overlapping notes. Group chat: that channel. DM: workspace search."""
    scoped = bool(channel_id) and not all_channels
    qtok = tokenize(trigger)
    found: dict[str, RankedCandidate] = {}

    def _add(m, source: str = "slack") -> None:
        text = (m.text or "").strip()
        if not text:
            return
        low = text.lower()
        if "checking decision history" in low or "searching decision history" in low or "didn't find a prior decision" in low:
            return
        if trigger and text == trigger.strip():
            return
        if source == "slack" and not _needed(text, qtok):
            return
        if scoped and m.channel_id != channel_id:
            return
        key = m.permalink or m.ts
        if not key:
            return
        found[key] = RankedCandidate(
            permalink=m.permalink or slack_permalink(m.channel_id, m.ts),
            channel_id=m.channel_id,
            thread_ts=m.thread_ts,
            channel_name=m.channel_name,
            snippet=text[:220],
            score=0.0,
            source=source,
            at=m.at,
            user_label=(m.user_label or "").strip(),
        )

    if scoped:
        try:
            hist = store.history(channel_id)
        except Exception:
            hist = []
        for m in hist:
            _add(m)
    else:
        try:
            chans = store.channels()[:6]
        except Exception:
            chans = []
        for ch in chans:
            try:
                hist = store.history(ch.id)[-30:]
            except Exception:
                continue
            kept = 0
            for m in notable(hist):
                _add(m)
                if _needed(m.text, qtok):
                    kept += 1
                if kept >= 4:
                    break

    queries = [q for q in probes if q][:max_searches]
    for q in queries:
        try:
            hits = store.search(q, limit=4, channel_id=channel_id if scoped else None)
        except TypeError:
            hits = store.search(q, limit=4)
        except Exception:
            hits = []
        for m in hits:
            _add(m)

    live = _live_bot()
    allowed: set[str] | None = None
    if scoped:
        allowed = {channel_id}
    elif live:
        try:
            allowed = {c.id for c in store.channels() if c.id}
        except Exception:
            allowed = set()

    for d in graph().list():
        if allowed is not None and d.channel_id not in allowed:
            continue
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
    rows = list(found.values())
    if scoped:
        rows = [c for c in rows if c.channel_id == channel_id]
    if len(rows) > _KEEP:
        hot = [c for c in rows if looks_decisionish(c.snippet) or c.source == "graph"]
        rest = [c for c in rows if c.permalink not in {h.permalink for h in hot}]
        rows = (hot + rest)[:_KEEP]
    return rows


def with_thread_context(store: SlackStore, ranked: list[RankedCandidate], limit: int = _THREADS) -> list[RankedCandidate]:
    """Attach short thread notes for Gemini. Not shown in the Slack reply."""
    from ikigai.notes import pack_messages

    def _fill(c: RankedCandidate) -> None:
        if c.context:
            return
        ts = c.thread_ts or ""
        if not c.channel_id or not ts:
            c.context = c.snippet
            return
        try:
            msgs = store.thread(c.channel_id, ts)
        except Exception:
            msgs = []
        if msgs:
            c.context = pack_messages(msgs, limit=10, each=180)
        else:
            c.context = c.snippet

    todo = [c for c in ranked[:limit] if not c.context]
    if len(todo) <= 1:
        for c in todo:
            _fill(c)
        return ranked
    with ThreadPoolExecutor(max_workers=min(6, len(todo))) as pool:
        list(pool.map(_fill, todo))
    return ranked


def _keyword_rank(trigger: str, candidates: list[RankedCandidate], limit: int) -> list[RankedCandidate]:
    q = tokenize(trigger)
    scored = []
    for c in candidates:
        overlap = len(q & tokenize(c.snippet or c.context))
        c.score = round(min(1.0, overlap / max(3, len(q))), 4) if q else 0.0
        scored.append(c)
    scored.sort(key=lambda c: (-c.score, 0 if looks_decisionish(c.snippet) else 1))
    return scored[:limit]


def rank(trigger: str, candidates: list[RankedCandidate], limit: int) -> list[RankedCandidate]:
    if not candidates:
        return []
    short = _keyword_rank(trigger, candidates, max(limit, 8))
    if len(short) <= 1:
        return short[:limit]
    corpus = [trigger] + [c.snippet for c in short]
    try:
        vectors = embed(corpus, stage="rank")
    except Exception:
        return short[:limit]
    if len(vectors) != len(corpus):
        return short[:limit]
    qv = vectors[0]
    scored = []
    for cand, vec in zip(short, vectors[1:], strict=False):
        cand.score = round(_cos(qv, vec), 4)
        scored.append(cand)
    scored.sort(key=lambda c: -c.score)
    return scored[:limit]
