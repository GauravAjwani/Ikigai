from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PathKind = Literal["watcher", "search", "check"]
DecisionStatus = Literal["current", "reversed", "concurrent", "unknown"]
WarningLevel = Literal["none", "info", "warning"]


class Trigger(BaseModel):
    text: str
    channel_id: str = "C-PLATFORM"
    thread_ts: str | None = None
    path: PathKind = "watcher"
    user_label: str = "you"


class SlackMessage(BaseModel):
    channel_id: str
    channel_name: str
    ts: str
    thread_ts: str
    user_label: str
    text: str
    permalink: str
    at: str


class Channel(BaseModel):
    id: str
    name: str
    purpose: str


class DerivedDecision(BaseModel):
    """Persisted at rest. Never includes message text, user IDs, or embeddings."""

    decision_id: str
    label: str
    concepts: list[str] = Field(default_factory=list)
    status: DecisionStatus = "current"
    confidence: float = 0.5
    permalink: str
    channel_id: str
    thread_ts: str
    created_at: str
    updated_at: str
    edges: list[dict] = Field(default_factory=list)


ALLOWED_GRAPH_KEYS = set(DerivedDecision.model_fields.keys())
FORBIDDEN_GRAPH_SUBSTRINGS = ("user_id", "userId", "embedding", "vector", "message_text", "raw_text")


class GateResult(BaseModel):
    is_decision_like: bool
    is_new_decision: bool = False
    is_reopening: bool = False
    proposal: str = ""
    reason: str = ""
    confidence: float = 0.0


class ProbeSet(BaseModel):
    mechanism: str
    consequence: str
    alternative: str
    semantic_question: str
    concepts: list[str] = Field(default_factory=list)


class RankedCandidate(BaseModel):
    permalink: str
    channel_id: str
    thread_ts: str
    channel_name: str = ""
    snippet: str
    score: float
    source: Literal["slack", "graph"] = "slack"
    at: str = ""
    decision_id: str | None = None
    graph_status: DecisionStatus | None = None


class Verdict(BaseModel):
    same_decision: bool
    status: DecisionStatus = "unknown"
    confidence: float = 0.0
    warning: WarningLevel = "none"
    what: str = ""
    why: str = ""
    aftermath: str = ""
    still_current: bool = False
    concurrent_note: str = ""
    permalink: str = ""
    related_permalinks: list[str] = Field(default_factory=list)
    should_surface: bool = False
    clarifying_question: str = ""


class StageTrace(BaseModel):
    stage: str
    ok: bool = True
    detail: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    ms: int = 0


class Card(BaseModel):
    warning: WarningLevel = "none"
    title: str
    status: DecisionStatus
    what: str
    why: str
    aftermath: str
    permalink: str
    related_permalinks: list[str] = Field(default_factory=list)
    clarifying_question: str = ""
    confidence: float = 0.0
    share_text: str = ""


class PipelineResult(BaseModel):
    silenced: bool
    silence_reason: str = ""
    gate: GateResult | None = None
    probes: list[str] = Field(default_factory=list)
    candidates: list[RankedCandidate] = Field(default_factory=list)
    verdict: Verdict | None = None
    card: Card | None = None
    captured: DerivedDecision | None = None
    cost_usd: float = 0.0
    stages: list[StageTrace] = Field(default_factory=list)
    gemini_used: bool = False
    path: PathKind = "watcher"
