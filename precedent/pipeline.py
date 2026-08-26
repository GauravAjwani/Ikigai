from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from precedent import cost
from precedent.cards import card_from_verdict
from precedent.gemini_client import GeminiError, generate_json
from precedent.graph import graph
from precedent.prefilter import is_chatter, looks_decisionish
from precedent.retrieval import rank, retrieve
from precedent.schemas import (
    DerivedDecision,
    GateResult,
    PipelineResult,
    ProbeSet,
    StageTrace,
    Trigger,
    Verdict,
)
from precedent.settings import get_settings
from precedent.slack_store import slack_store


GATE_PROMPT = """You are the silence layer for Precedent, a Slack decision-memory agent.
Decide if this message is a meaningful proposal, recommendation, reopening of a past call, or a newly stated decision.

NOT decision-like: thanks, jokes, status links, stand-up chatter, pure questions with no proposal, FYI without a call.

JSON fields:
- is_decision_like: bool
- is_new_decision: team is settling something now
- is_reopening: team may be reopening a settled question
- proposal: short restatement of the proposed call (empty if none)
- reason: one sentence
- confidence: 0-1

Message:
{text}
"""

PROBE_PROMPT = """Generate cross-vocabulary search probes for this Slack proposal.
Do NOT reuse the message's distinctive nouns if a more general mechanism exists.
Cover: underlying mechanism, failure consequence, and a rejected alternative.
semantic_question must be a natural-language question Slack semantic search can use.
concepts: 1-4 ids from: {concepts}

Proposal:
{text}

Return JSON.
"""

ADJUDICATE_PROMPT = """You adjudicate whether a Slack message reopens a previously settled decision.

Trigger message:
{text}

Ranked candidates (derived labels and snippets from conversations the user can access).
These exist only for this request. Do not invent permalinks.
{candidates}

Rules:
- same_decision if they are the same underlying call even with different words.
- status=reversed if a later message replaced the earlier policy.
- status=concurrent if two teams made different valid choices at the same time (e.g. payments Postgres queue vs notifications Pub/Sub).
- status=current if the matching decision still stands.
- should_surface on the watcher path only if ignoring the match is costly (reopening a current call, or following reversed guidance).
- warning=warning for reversed, info for concurrent, none for a calm current match.
- If two strong candidates disagree, set clarifying_question.
- what / why / aftermath: 1-2 sentences each, no user IDs.

Path: {path}
"""


def _trace(stage: str, ok: bool, detail: str, usd: float, t0: float) -> StageTrace:
    return StageTrace(
        stage=stage, ok=ok, detail=detail, usd=round(usd, 8), ms=int((time.time() - t0) * 1000)
    )


def _new_id(label: str) -> str:
    h = hashlib.sha256(label.encode()).hexdigest()[:12]
    return f"d-{h}"


async def run_pipeline(trigger: Trigger) -> PipelineResult:
    s = get_settings()
    t_all = time.time()
    stages: list[StageTrace] = []
    spent0 = cost.spent_today()

    ok, why = cost.budget_ok()
    if not ok:
        return PipelineResult(
            silenced=True, silence_reason=why, path=trigger.path, stages=stages
        )

    text = (trigger.text or "").strip()
    t0 = time.time()
    if trigger.path == "watcher" and is_chatter(text):
        stages.append(_trace("prefilter", True, "chatter", 0, t0))
        return PipelineResult(
            silenced=True,
            silence_reason="chatter",
            path=trigger.path,
            stages=stages,
            cost_usd=0,
        )
    if trigger.path == "watcher" and not looks_decisionish(text) and len(text) < 40:
        stages.append(_trace("prefilter", True, "not decision-like", 0, t0))
        return PipelineResult(
            silenced=True,
            silence_reason="not decision-like",
            path=trigger.path,
            stages=stages,
        )
    stages.append(_trace("prefilter", True, "pass", 0, t0))

    try:
        t0 = time.time()
        gate, gmodel = generate_json(
            stage="gate",
            model=s.gate_model,
            fallback=s.fallback_gate_model,
            prompt=GATE_PROMPT.format(text=text),
            schema=GateResult,
            thinking="MINIMAL",
        )
        stages.append(_trace("gate", True, gmodel, cost.spent_today() - spent0, t0))
    except GeminiError as e:
        stages.append(_trace("gate", False, str(e), 0, t0))
        if trigger.path == "watcher":
            return PipelineResult(
                silenced=True, silence_reason=str(e), path=trigger.path, stages=stages
            )
        raise

    if trigger.path == "watcher" and not gate.is_decision_like:
        return PipelineResult(
            silenced=True,
            silence_reason=gate.reason or "gate",
            gate=gate,
            path=trigger.path,
            stages=stages,
            gemini_used=True,
            cost_usd=round(cost.spent_today() - spent0, 6),
        )

    from precedent.concepts import CONCEPTS

    t0 = time.time()
    probes_model, pmodel = generate_json(
        stage="probes",
        model=s.probe_model,
        fallback=s.fallback_gate_model,
        prompt=PROBE_PROMPT.format(text=text, concepts=", ".join(CONCEPTS)),
        schema=ProbeSet,
        thinking="MINIMAL",
    )
    probes = [
        probes_model.mechanism,
        probes_model.consequence,
        probes_model.alternative,
        probes_model.semantic_question,
    ]
    stages.append(_trace("probes", True, pmodel, 0, t0))

    t0 = time.time()
    store = slack_store()
    candidates = retrieve(
        store=store, trigger=text, probes=probes, max_searches=s.max_slack_searches
    )
    ranked = rank(text, candidates, s.max_rank_candidates)
    ranked = [c for c in ranked if c.score >= s.rank_threshold or c.source == "graph"]
    stages.append(_trace("retrieve", True, f"{len(ranked)} ranked", 0, t0))

    if not ranked and trigger.path == "watcher":
        captured = None
        if gate.is_new_decision:
            captured = _capture(gate, trigger, probes_model.concepts)
        return PipelineResult(
            silenced=True,
            silence_reason="no candidates",
            gate=gate,
            probes=probes,
            captured=captured,
            path=trigger.path,
            stages=stages,
            gemini_used=True,
            cost_usd=round(cost.spent_today() - spent0, 6),
        )

    cand_lines = []
    for i, c in enumerate(ranked[:8], 1):
        cand_lines.append(
            f"{i}. score={c.score:.2f} source={c.source} status={c.graph_status} "
            f"permalink={c.permalink} snippet={c.snippet[:240]}"
        )
    t0 = time.time()
    verdict, amodel = generate_json(
        stage="adjudicate",
        model=s.adjudicate_model,
        fallback=s.fallback_adjudicate_model,
        prompt=ADJUDICATE_PROMPT.format(
            text=text, candidates="\n".join(cand_lines) or "(none)", path=trigger.path
        ),
        schema=Verdict,
        thinking="LOW",
    )
    if ranked and not verdict.permalink:
        verdict.permalink = ranked[0].permalink
    stages.append(_trace("adjudicate", True, amodel, 0, t0))

    captured = None
    if gate.is_new_decision and trigger.path != "check":
        captured = _capture(gate, trigger, probes_model.concepts)

    should = verdict.should_surface and verdict.same_decision
    if trigger.path != "watcher":
        should = bool(verdict.same_decision or ranked)
    if trigger.path == "watcher" and verdict.confidence < s.watcher_confidence_threshold:
        should = False

    card = card_from_verdict(verdict) if should and verdict.same_decision else None
    if trigger.path != "watcher" and not card and ranked:
        # Commands always speak.
        if not verdict.same_decision:
            card = None
        else:
            card = card_from_verdict(verdict)

    silenced = card is None and trigger.path == "watcher"
    reason = ""
    if silenced:
        reason = "low confidence" if verdict.same_decision else "no match"
    return PipelineResult(
        silenced=silenced,
        silence_reason=reason,
        gate=gate,
        probes=probes,
        candidates=ranked,
        verdict=verdict,
        card=card,
        captured=captured,
        path=trigger.path,
        stages=stages,
        gemini_used=True,
        cost_usd=round(cost.spent_today() - spent0, 6),
    )


def _capture(gate: GateResult, trigger: Trigger, concepts: list[str]) -> DerivedDecision:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = DerivedDecision(
        decision_id=_new_id(gate.proposal or trigger.text)[:20],
        label=(gate.proposal or trigger.text)[:160],
        concepts=concepts[:4],
        status="current",
        confidence=gate.confidence or 0.6,
        permalink=f"https://acme.slack.com/archives/{trigger.channel_id}/p{now}",
        channel_id=trigger.channel_id,
        thread_ts=trigger.thread_ts or now,
        created_at=now,
        updated_at=now,
    )
    graph().upsert(rec)
    return rec
