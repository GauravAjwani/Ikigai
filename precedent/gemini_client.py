from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from precedent import cost
from precedent.settings import get_settings

_client: genai.Client | None = None
_resolved: dict[str, str] = {}


class GeminiError(RuntimeError):
    pass


def client() -> genai.Client:
    global _client
    if _client is not None:
        return _client
    s = get_settings()
    if s.vertex_enabled and s.google_cloud_project:
        _client = genai.Client(
            vertexai=True,
            project=s.google_cloud_project,
            location=s.google_cloud_location,
        )
        return _client
    if s.gemini_api_key:
        _client = genai.Client(api_key=s.gemini_api_key)
        return _client
    if s.google_cloud_project:
        _client = genai.Client(
            vertexai=True,
            project=s.google_cloud_project,
            location=s.google_cloud_location,
        )
        return _client
    raise GeminiError(
        "No Gemini credentials. Set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT for Vertex."
    )


def _usage(resp: Any) -> tuple[int, int]:
    um = getattr(resp, "usage_metadata", None)
    if not um:
        return 0, 0
    inn = int(getattr(um, "prompt_token_count", 0) or 0)
    out = int(getattr(um, "candidates_token_count", 0) or 0)
    think = int(getattr(um, "thoughts_token_count", 0) or 0)
    return inn, out + think


def generate_json(
    *,
    stage: str,
    model: str,
    fallback: str,
    prompt: str,
    schema: type[BaseModel],
    thinking: str,
) -> tuple[BaseModel, str]:
    s = get_settings()
    ok, why = cost.budget_ok()
    if not ok:
        raise GeminiError(why)
    cfg = types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=thinking, include_thoughts=False),
    )
    last_err: Exception | None = None
    used = _resolved.get(model, model)
    for candidate in (used, fallback, s.fallback_gate_model, s.fallback_adjudicate_model):
        if not candidate:
            continue
        try:
            resp = client().models.generate_content(
                model=candidate, contents=prompt, config=cfg
            )
            tin, tout = _usage(resp)
            cost.record(stage, candidate, tin, tout)
            text = (resp.text or "").strip()
            parsed = schema.model_validate_json(text)
            _resolved[model] = candidate
            return parsed, candidate
        except GeminiError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise GeminiError(f"{stage} failed: {last_err}")


def embed(texts: list[str], stage: str = "embed") -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    ok, why = cost.budget_ok()
    if not ok:
        raise GeminiError(why)
    model = s.embed_model
    resp = client().models.embed_content(model=model, contents=texts)
    embs = []
    for e in resp.embeddings or []:
        embs.append(list(e.values or []))
    # usage is not always populated; estimate
    tokens = sum(max(8, len(t.split()) * 2) for t in texts)
    cost.record(stage, model, tokens, 0)
    return embs
