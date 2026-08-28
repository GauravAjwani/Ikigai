# Ikigai

Decision memory for Slack.

When someone reopens a settled question, Ikigai finds the original decision — even when the two conversations share almost no vocabulary.

You can use it in public or in private. They are separate chats.

## How you call it

**Public** (everyone in the channel can see it)

- `@Ikigai <proposal>` in a channel — replies in that thread, in public

**Private** (only you)

- `/ikigai <proposal>` in a channel — only you see the reply
- `/ikigai logout` — you're done for the day (private). Ikigai notes the time.
- `/ikigai login` — private catch-up of what you missed. Tap an item to jump to the original thread.
- `/check-ikigai [name]` — summary of that person's calls **in this chat**, plus who agreed or opposed
- Open a DM with Ikigai: mention a person or a decision and it searches **every channel** it can access

Greetings, thanks, and emoji-only prompts (`@Ikigai hello`, `/ikigai thanks`) get no reply and do not call a model.

Every decision card starts with a one-line summary, then What / Why / After as before.

## Stack

| Requirement | This repo |
|---|---|
| Gemini 3.5+ | `gemini-3.5-flash-lite` (gate, probes), `gemini-3.5-flash` (adjudicate), `gemini-embedding-001` (rank) |
| Google agent framework | Google ADK — `root_agent` in `ikigai/agent.py` |
| GCP | Cloud Run, Firestore, Pub/Sub (deploy script), Vertex AI |

## Architecture

```
Slash / @mention / DM / Replay UI
        │
        ▼
Cloud Run  (ACK < 3s)
        │
        ▼
┌──────────────────────────────────────┐
│  ADK agent  (IkigaiAgent)            │
│  0. Prefilter — no model             │
│  1. Gate — gemini-3.5-flash-lite     │
│  2. Probes — mechanism / consequence │
│  3. Retrieve — Slack + graph         │
│  4. Transient embed-rank-destroy     │
│  5. Adjudicate — gemini-3.5-flash    │
└──────────────────────────────────────┘
        │
        ▼
Public channel reply (everyone sees it)
        │
        ▼
Firestore  labels · status · confidence · permalinks · edges
```

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set GEMINI_API_KEY and Slack tokens

cd web && npm install && npm run build && cd ..
python -m uvicorn ikigai.api:app --host 0.0.0.0 --port 43177
```

Open http://127.0.0.1:43177

Type `Let's rotate tokens every night.` Ikigai should attach the lock-free rotator reversal (and the earlier 401 cascade), not a keyword match.

Without `GEMINI_API_KEY` the API returns 503. The product does not fake Gemini.

```bash
python -m pytest tests/ -q
```

## Deploy to Google Cloud

1. Create a GCP project and enable billing. Set a budget alert at **$40**.
2. Create a Firestore native database (nam5 or us-central1).
3. From this repo:

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GEMINI_API_KEY=...
chmod +x infra/deploy.sh
./infra/deploy.sh
```

Set Slack Request URLs to `https://<service>.run.app/slack/events` and `/slack/commands`, or use Socket Mode locally with `SLACK_APP_TOKEN`. Install from `infra/slack-manifest.yaml`.

## MCP

- `POST /mcp/query_decisions` `{"query":"..."}`
- `POST /mcp/check_supersession` `{"text":"..."}`

## What we do not store

Message text, Slack user IDs, embeddings, or a vector index of the workspace. Confirm with **Graph inspector** in the UI or `GET /api/privacy`.
