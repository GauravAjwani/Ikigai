# Precedent

Decision memory for Slack. Track: **Taskmaster**.

When someone reopens a settled question, Precedent privately surfaces the original decision, why it was made, what happened after, and whether it was reversed — even when the two conversations share almost no vocabulary.

Wrong in private. Right in public. About 95% of messages produce no visible response.

## This is a working agent, not a screenshot

- **Workspace Replay** is a real pipeline: Gemini 3.5 gate → cross-vocabulary probes → Slack-style search + derived graph → transient embeddings → adjudication → ephemeral card.
- **Live Slack** is implemented (`/precedent`, `/check-precedent`, watcher → `chat.postEphemeral`). Point HTTP events at the Cloud Run URL.
- **Firestore** holds derived labels, status, confidence, permalinks, and edges. Message text, user IDs, and embeddings are never written. The privacy inspector dumps live records and fails if those fields appear.
- **Cost kill switch** pauses the watcher at $10/day and hard-stops at $40.

Runtime data is not written to local files. The synthetic Acme workspace lives in process memory (and is source code for evals). The decision graph lives in Firestore when `GOOGLE_CLOUD_PROJECT` is set.

## Stack (hackathon requirements)

| Requirement | This repo |
|---|---|
| Gemini 3.5+ | `gemini-3.5-flash-lite` (gate, probes), `gemini-3.5-flash` (adjudicate), `gemini-embedding-001` (rank) via Gemini API or Vertex AI |
| Google agent framework | Google ADK — `root_agent` in `precedent/agent.py` |
| GCP | Cloud Run, Firestore, Pub/Sub (deploy script), Vertex AI |

## Architecture

```
Slack event / slash / Replay UI
        │
        ▼
Cloud Run  (ACK < 3s)
        │
        ▼
┌──────────────────────────────────────┐
│  ADK agent  (PrecedentAgent)         │
│  0. Prefilter — no model             │
│  1. Gate — gemini-3.5-flash-lite     │  ~95% exit
│  2. Probes — mechanism / consequence │
│  3. Retrieve — Slack RTS + graph     │
│  4. Transient embed-rank-destroy     │
│  5. Adjudicate — gemini-3.5-flash    │
└──────────────────────────────────────┘
        │
        ▼
Ephemeral card (only the triggering user)
        │
        ▼
Firestore  labels · status · confidence · permalinks · edges
```

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set GEMINI_API_KEY

cd web && npm install && npm run build && cd ..
python -m uvicorn precedent.api:app --host 0.0.0.0 --port 43177
```

Open http://127.0.0.1:43177

Type `Let's rotate tokens every night.` Precedent should privately attach the lock-free rotator reversal (and the earlier 401 cascade), not a keyword match.

Without `GEMINI_API_KEY` the API returns 503. The product does not fake Gemini.

```bash
# unit tests (no network)
python -m pytest tests/ -q
```

## Deploy to Google Cloud (first run < $50)

On the account that holds the credits (`asroyalfcb@gmail.com` or whichever project you attach):

1. Create a GCP project and enable billing. Set a budget alert at **$40**.
2. Create a Firestore native database (nam5 or us-central1).
3. From this repo:

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GEMINI_API_KEY=...          # or rely on Vertex ADC
chmod +x infra/deploy.sh
./infra/deploy.sh
```

The script deploys Cloud Run with **min instances = 0**, memory 512Mi, max 2. It prints the `*.run.app` URL — that is the hosted project and the proof the backend is on Google Cloud.

Set Slack Request URLs to `https://<service>.run.app/slack/events` and `/slack/commands`. Install from `infra/slack-manifest.yaml`.

## Slack commands

- `/precedent <proposal>` — search decision history (always answers)
- `/check-precedent` — check the current thread
- Watcher — silent unless a high-cost match (current decision being reopened, or reversed guidance)

## MCP

- `POST /mcp/query_decisions` `{"query":"..."}`
- `POST /mcp/check_supersession` `{"text":"..."}`

Same privacy boundary. No content stored.

## What we do not store

Message text, Slack user IDs, embeddings, or a vector index of the workspace. Confirm with **Graph inspector** in the UI or `GET /api/privacy`.
