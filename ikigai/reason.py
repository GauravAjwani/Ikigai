"""Gemini understands context first, then the caller writes the user-facing reply."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Situation(BaseModel):
    situation: str = ""
    their_role: str = ""
    decision_permalinks: list[str] = Field(default_factory=list)


def first_understand(
    *,
    stage: str,
    prompt: str,
    model: str,
    fallback: str,
    thinking: str = "LOW",
    generate=None,
) -> Situation:
    """One pass: what happened. Never the Slack reply. Safe if the model fails."""
    from ikigai.gemini_client import generate_json as _gj

    fn = generate or _gj
    try:
        got, _model = fn(
            stage=stage,
            model=model,
            fallback=fallback,
            prompt=prompt,
            schema=Situation,
            thinking=thinking,
        )
        if isinstance(got, Situation):
            return got
    except Exception:
        pass
    return Situation()
