from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from precedent import cost
from precedent.graph import graph, privacy_dump
from precedent.pipeline import run_pipeline
from precedent.schemas import Trigger
from precedent.settings import get_settings
from precedent.slack_store import reset_store, slack_store

try:
    from precedent.slack_app import handler as slack_handler
except Exception:  # pragma: no cover
    slack_handler = None

app = FastAPI(title="Precedent", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB = Path(__file__).resolve().parent.parent / "web" / "dist"


class WatchBody(BaseModel):
    text: str
    channel_id: str = "C-PLATFORM"
    path: str = "watcher"
    user_label: str = "you"
    post: bool = True


class FeedbackBody(BaseModel):
    decision_id: str
    note: str = "not_same"


class SearchBody(BaseModel):
    query: str = Field(min_length=2)


@app.get("/api/health")
def health():
    s = get_settings()
    return {
        "ok": True,
        "name": "Precedent",
        "gemini": s.gemini_ready(),
        "gcp_project": s.google_cloud_project or None,
        "vertex": s.vertex_enabled or bool(s.google_cloud_project and not s.gemini_api_key),
        "slack": s.slack_ready(),
        "graph": type(graph()).__name__,
        "budget": cost.snapshot(),
    }


@app.get("/api/workspace")
def workspace(channel_id: str | None = None):
    store = slack_store()
    channels = [c.model_dump() for c in store.channels()]
    cid = channel_id or (channels[0]["id"] if channels else "")
    messages = [m.model_dump() for m in store.history(cid)]
    return {"channels": channels, "channel_id": cid, "messages": messages}


@app.post("/api/reset")
def reset():
    reset_store()
    return {"ok": True}


@app.post("/api/run")
async def run(body: WatchBody):
    from precedent.prefilter import is_chatter, looks_decisionish
    from precedent.schemas import PipelineResult

    store = slack_store()
    posted = None
    if body.post and body.path == "watcher":
        posted = store.post(body.channel_id, body.text, body.user_label)

    if body.path == "watcher" and (is_chatter(body.text) or not looks_decisionish(body.text) and len(body.text.strip()) < 40):
        result = PipelineResult(
            silenced=True,
            silence_reason="chatter",
            path="watcher",
            gemini_used=False,
        )
        return {"posted": posted.model_dump() if posted else None, "result": result.model_dump()}

    s = get_settings()
    if not s.gemini_ready():
        raise HTTPException(
            503,
            "Gemini is not configured. Set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT.",
        )
    try:
        result = await run_pipeline(
            Trigger(
                text=body.text,
                channel_id=body.channel_id,
                thread_ts=posted.ts if posted else None,
                path=body.path if body.path in {"watcher", "search", "check"} else "watcher",
                user_label=body.user_label,
            )
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e)) from e
    return {
        "posted": posted.model_dump() if posted else None,
        "result": result.model_dump(),
    }


@app.post("/api/precedent")
async def slash_precedent(body: SearchBody):
    result = await run_pipeline(
        Trigger(text=body.query, path="search", channel_id="C-PLATFORM")
    )
    return result.model_dump()


@app.post("/api/check")
async def slash_check(body: WatchBody):
    result = await run_pipeline(
        Trigger(text=body.text, channel_id=body.channel_id, path="check")
    )
    return result.model_dump()


@app.get("/api/graph")
def graph_dump():
    return privacy_dump()


@app.get("/api/privacy")
def privacy():
    return privacy_dump()


@app.get("/api/cost")
def cost_api():
    return cost.snapshot()


@app.post("/api/feedback")
def feedback(body: FeedbackBody):
    graph().add_negative(body.decision_id, body.note)
    return {"ok": True}


@app.get("/api/evals")
async def evals(limit: int = 8):
    from precedent.evals import run_evals

    return await run_evals(limit=limit)


@app.post("/mcp/query_decisions")
async def mcp_query(body: SearchBody):
    result = await run_pipeline(
        Trigger(text=body.query, path="search", channel_id="C-PLATFORM")
    )
    return {
        "decisions": [c.model_dump() for c in result.candidates],
        "verdict": result.verdict.model_dump() if result.verdict else None,
    }


@app.post("/mcp/check_supersession")
async def mcp_super(body: WatchBody):
    result = await run_pipeline(
        Trigger(text=body.text, path="check", channel_id=body.channel_id)
    )
    v = result.verdict
    return {
        "status": v.status if v else "unknown",
        "same_decision": v.same_decision if v else False,
        "permalink": v.permalink if v else None,
    }


@app.post("/slack/events")
@app.post("/slack/commands")
async def slack_http(req: Request):
    if slack_handler is None or not get_settings().slack_ready():
        raise HTTPException(503, "Slack is not configured")
    return await slack_handler.handle(req)


@app.get("/api/architecture")
def architecture():
    return {
        "track": "Taskmaster",
        "models": {
            "gate": get_settings().gate_model,
            "probes": get_settings().probe_model,
            "adjudicate": get_settings().adjudicate_model,
            "embed": get_settings().embed_model,
        },
        "stored": [
            "derived labels",
            "status",
            "confidence",
            "permalinks",
            "edges",
        ],
        "never_stored": [
            "Slack message text",
            "Slack user IDs",
            "content embeddings",
            "a persistent vector index",
        ],
        "gcp": ["Cloud Run", "Firestore", "Pub/Sub", "Vertex AI"],
        "framework": "Google ADK sequential pipeline (not SlackRunner)",
    }


if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("mcp/"):
            raise HTTPException(404)
        candidate = WEB / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB / "index.html")
