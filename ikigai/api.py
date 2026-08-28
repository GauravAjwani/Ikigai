from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ikigai import cost
from ikigai.graph import graph, privacy_dump
from ikigai.pipeline import run_pipeline
from ikigai.schemas import Trigger
from ikigai.security import MAX_BODY, ApiGuardMiddleware, on_cloud, verify_slack_signature
from ikigai.settings import get_settings
from ikigai.slack_store import reset_store, slack_store

try:
    from ikigai.slack_app import handler as slack_handler
except Exception:  # pragma: no cover
    slack_handler = None

_socket_handler = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _socket_handler
    s = get_settings()
    # Socket Mode is for a laptop. Cloud Run must use HTTP events or the
    # instance freezes after Slack's 3s ACK and never posts a reply.
    on_cloud_run = bool(os.environ.get("K_SERVICE"))
    in_pytest = "pytest" in __import__("sys").modules
    if s.slack_ready() and s.slack_app_token and not on_cloud_run and not in_pytest:
        from slack_bolt.adapter.socket_mode import SocketModeHandler

        from ikigai.slack_app import bolt

        _socket_handler = SocketModeHandler(bolt, s.slack_app_token)
        _socket_handler.connect()
    yield
    if _socket_handler is not None:
        _socket_handler.close()
        _socket_handler = None


app = FastAPI(title="Ikigai", version="1.0.0", lifespan=lifespan)
if on_cloud():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["GET", "POST"],
        allow_headers=["X-Ikigai-Token", "Authorization", "Content-Type"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.add_middleware(ApiGuardMiddleware)

WEB = Path(__file__).resolve().parent.parent / "web" / "dist"


class WatchBody(BaseModel):
    text: str
    channel_id: str = "C-PLATFORM"
    path: str = "watcher"
    user_label: str = "you"
    post: bool = True
    all_channels: bool = False


class FeedbackBody(BaseModel):
    decision_id: str
    note: str = "not_same"


class SearchBody(BaseModel):
    query: str = Field(min_length=2)


@app.get("/api/health")
def health():
    s = get_settings()
    body = {
        "ok": True,
        "name": "Ikigai",
        "gemini": s.gemini_ready(),
        "slack": s.slack_ready(),
        "slack_http": slack_handler is not None,
        "slash_commands": ["/ikigai", "/check-ikigai"],
        "build": "fix-v21",
    }
    if on_cloud():
        body["vertex"] = s.vertex_enabled or bool(s.google_cloud_project and not s.gemini_api_key)
        return body
    body["gcp_project"] = s.google_cloud_project or None
    body["vertex"] = s.vertex_enabled or bool(s.google_cloud_project and not s.gemini_api_key)
    try:
        body["graph"] = type(graph()).__name__
    except Exception:
        body["graph"] = "unavailable"
    body["store"] = type(slack_store()).__name__
    body["budget"] = cost.snapshot()
    return body


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
    from ikigai.prefilter import is_chatter, is_trivial_prompt, looks_decisionish
    from ikigai.schemas import PipelineResult

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

    if body.path in {"search", "check"} and is_trivial_prompt(body.text):
        result = PipelineResult(
            silenced=True,
            silence_reason="trivial",
            path=body.path if body.path in {"watcher", "search", "check"} else "search",
            gemini_used=False,
            cost_usd=0,
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
                all_channels=body.all_channels,
            )
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e)) from e
    return {
        "posted": posted.model_dump() if posted else None,
        "result": result.model_dump(),
    }


@app.post("/api/ikigai")
async def slash_ikigai(body: SearchBody):
    from ikigai.prefilter import is_trivial_prompt
    from ikigai.schemas import PipelineResult

    if is_trivial_prompt(body.query):
        return PipelineResult(
            silenced=True, silence_reason="trivial", path="search", gemini_used=False
        ).model_dump()
    result = await run_pipeline(
        Trigger(text=body.query, path="search", channel_id="C-PLATFORM")
    )
    return result.model_dump()


@app.post("/api/check")
async def slash_check(body: WatchBody):
    from ikigai.prefilter import is_trivial_prompt
    from ikigai.stances import check_person, extract_person_query

    if is_trivial_prompt(body.text):
        from ikigai.schemas import PipelineResult

        return PipelineResult(
            silenced=True, silence_reason="trivial", path="check", gemini_used=False
        ).model_dump()
    store = slack_store()
    name = extract_person_query(body.text, store.user_labels())
    if name:
        import sys

        found = check_person(
            store,
            name,
            channel_id=body.channel_id,
            all_channels=False,
            analyze="pytest" not in sys.modules,
        )
        return {
            "name": found.name,
            "scope": found.scope,
            "summary": found.summary,
            "happened": found.happened,
            "reports": [
                {
                    "label": r.label,
                    "gist": r.gist,
                    "what": r.what,
                    "channel_name": r.channel_name,
                    "permalink": r.permalink,
                    "agreed": r.agreed,
                    "opposed": r.opposed,
                }
                for r in found.reports
            ],
            "gemini_used": bool(found.happened or found.headline),
            "cost_usd": 0,
        }
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
    from ikigai.evals import run_evals

    return await run_evals(limit=limit)


@app.post("/mcp/query_decisions")
async def mcp_query(body: SearchBody):
    result = await run_pipeline(
        Trigger(text=body.query, path="search", channel_id="C-PLATFORM")
    )
    return {
        "decisions": [
            {
                "permalink": c.permalink,
                "channel_id": c.channel_id,
                "status": c.graph_status,
                "score": c.score,
            }
            for c in result.candidates
        ],
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
    s = get_settings()
    if slack_handler is None or not s.slack_ready():
        raise HTTPException(503, "Slack is not configured")
    from slack_bolt.adapter.starlette.handler import to_bolt_request, to_starlette_response

    from ikigai.slack_app import bolt

    body = await req.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "payload too large")
    if not verify_slack_signature(
        signing_secret=s.slack_signing_secret,
        timestamp=req.headers.get("x-slack-request-timestamp") or "",
        signature=req.headers.get("x-slack-signature") or "",
        body=body,
    ):
        raise HTTPException(401, "invalid slack signature")

    # Slack retries the same Events API payload if it does not see HTTP 200
    # within ~3s. Gemini lookup is slower than that, so retries used to
    # post 3–6 @Ikigai replies. ACK is already immediate; drop the extras.
    if req.url.path.rstrip("/").endswith("/slack/events") and req.headers.get(
        "x-slack-retry-num"
    ):
        return Response(status_code=200, content="")

    bolt_req = to_bolt_request(req, body)
    bolt_resp = await run_in_threadpool(bolt.dispatch, bolt_req)
    if bolt_resp is None:
        return Response(status_code=200, content="")
    return to_starlette_response(bolt_resp)


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
else:

    @app.get("/")
    def setup_page():
        return HTMLResponse(
            """<!doctype html>
<html><head><meta charset="utf-8"><title>Ikigai</title>
<style>
  body{font:16px/1.5 system-ui;background:#12141a;color:#e8e4db;max-width:40rem;margin:4rem auto;padding:0 1.5rem}
  code{background:#1d222b;padding:.15rem .4rem;border-radius:4px}
  a{color:#8faf86}
</style></head><body>
<h1>Ikigai is running</h1>
<p>The API is up. The Replay UI is not built yet, so this page is a stand-in.</p>
<p>Health: <a href="/api/health">/api/health</a></p>
<p>In a terminal:</p>
<pre>cd web
npm install
npm run build</pre>
<p>Then restart the server. Also set <code>GEMINI_API_KEY</code> in <code>.env</code>.</p>
</body></html>"""
        )
