# Ikigai

Decision memory for Slack. **All Things Agentic** · track **Taskmaster**.

When someone reopens a settled question, Ikigai finds the original call — even when the two conversations share almost no vocabulary. It is not a chatbot. Greetings, thanks, and emoji-only prompts get no reply and do not call a model.

Public and private are separate. `@Ikigai` is a channel reply everyone can see. `/ikigai` is ephemeral: only you see it.

## For judges

You do **not** need a Slack workspace, GCP project, or Vertex account to evaluate the agent.

1. **Demo video** (primary). The live Slack agent is what the product is.
2. **Replay UI** (no Slack). Run locally with the steps below, then type `Let's rotate tokens every night.` You should get the lock-free rotator reversal and the earlier 401 cascade — not a keyword match.
3. **Hosted Replay** (no Slack, no laptop):
   - App: https://ikigai-uipuf5bksa-uc.a.run.app
   - Health: https://ikigai-uipuf5bksa-uc.a.run.app/api/health
   - Open the app. You should see fixture channels and messages already in the thread. Type `Let's rotate tokens every night.`
   - That UI is a **demo corpus**, not your live Slack. `@Ikigai` in Slack is the live agent.
4. **Architecture diagram** (upload this on Devpost): [`docs/architecture.html`](docs/architecture.html) or [`docs/ikigai-architecture.pdf`](docs/ikigai-architecture.pdf).
5. Private repo access: add `testing@devpost.com` and `cloudhackathons@google.com` as collaborators.

The hosted URL is Cloud Run: Replay (fixture workspace) plus Slack HTTP events. Live Slack history is not exposed on the website. `/mcp/*` and `/api/privacy` stay locked unless `X-Ikigai-Token` is sent.

`PLAN.md` is the original planning note. The shipped product is this README and the `ikigai/` package.

## How you call it

| Call | Who sees it | What it does |
|---|---|---|
| `@Ikigai <question>` | Public, in that thread | Decision lookup in **this channel** |
| `/ikigai <question>` | Private (ephemeral) | Same lookup |
| `/ikigai logout` | Private | Warm goodbye; records when you left |
| `/ikigai login` | Private | Catch-up since you left; tap a line to open the thread |
| `/check-ikigai @username` | Private | That person's calls in this chat, plus who supported or opposed |
| DM Ikigai | Private | Search / person-check across channels the bot can see |

`/check-ikigai` needs a Slack `@username`, not a free-text name.

A card leads with one warm line (`This was already decided` / `Heads up — this was later reversed` / `Two live approaches here`), then **Status**, **Who** (`@username`), **Now**, and **Open thread**.

## Stack

| Requirement | This repo |
|---|---|
| Gemini 3.5+ | `gemini-3.5-flash-lite` (watcher gate), `gemini-3.5-flash` (lookup / login / check), `gemini-embedding-001` (transient rank) |
| Google agent framework | Google ADK — `root_agent` in `ikigai/agent.py` |
| GCP | Cloud Run, Firestore, Vertex AI (Pub/Sub enabled on deploy) |

Search, login, and check use **one** Flash call each (`thinking=LOW`). The unsolicited watcher adds a Flash-Lite gate (`thinking=MINIMAL`). Probes are heuristic (no model).

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
│  1. Gate — flash-lite (watcher only) │
│  2. Probes — heuristic               │
│  3. Retrieve — Slack + graph         │
│  4. Transient embed-rank-destroy     │
│  5. Adjudicate — gemini-3.5-flash    │
└──────────────────────────────────────┘
        │
        ▼
Card (Replay JSON or Slack Block Kit)
        │
        ▼
Firestore  labels · status · confidence · permalinks · edges
```

Without Slack tokens the same pipeline runs on a fixture workspace (`FixtureSlack`). That is the Replay UI.

## 1. Run locally (Replay UI, no Slack)

You need **Python 3.12+**, **Node 20+**, and a [Gemini API key](https://aistudio.google.com/apikey). Slack tokens are optional.

### macOS / Linux

```bash
git clone https://github.com/GauravAjwani/Ikigai.git
cd Ikigai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Windows (PowerShell)

```powershell
git clone https://github.com/GauravAjwani/Ikigai.git
cd Ikigai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set at least:

```
GEMINI_API_KEY=your-key
```

Leave Slack fields empty. Replay uses the fixture corpus.

Build the UI and start the API (same on every OS, from the repo root, venv on):

```bash
cd web
npm install
npm run build
cd ..
python -m uvicorn ikigai.api:app --host 0.0.0.0 --port 43177
```

Open http://127.0.0.1:43177

- **Workspace** — pick a fixture channel, paste a proposal, Run.
- Try `Let's rotate tokens every night.` then `thanks!` (should stay silent).
- **Graph inspector** — derived labels only; no message text.
- **Architecture** / **Cost** — stack and the day's meter.

Without `GEMINI_API_KEY` (and without Vertex), lookup returns 503. The product does not fake Gemini.

### Tests

```bash
python -m pytest tests/test_core.py tests/test_api.py -q
```

If `test_health` / `test_privacy` hang, your `.env` is pointing at a live GCP project. Use `pytest tests/test_core.py -q` instead, or unset `GOOGLE_CLOUD_PROJECT` for the test run.

## 2. Deploy to Google Cloud

Already live for this submission: **https://ikigai-uipuf5bksa-uc.a.run.app**. To reproduce:

1. Create a GCP project, enable billing, set a budget alert at **$40**.
2. Create a Firestore **Native** database (`nam5` or `us-central1`).
3. Authenticate (`gcloud auth login` and `gcloud auth application-default login`).
4. From the repo (Git Bash on Windows; set `CLOUDSDK_PYTHON` if `gcloud` is tied to a broken Python):

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
# Vertex on Cloud Run; optional AI Studio key as a Secret Manager fallback:
# export GEMINI_API_KEY=...
chmod +x infra/deploy.sh
./infra/deploy.sh
```

The script builds the image with Cloud Build, then `gcloud run deploy --image`. It enables Run, Vertex, Firestore, Pub/Sub, Secret Manager, and Artifact Registry. Confirm `"ok": true` on `/api/health`.

Optional: set `IKIGAI_API_TOKEN` before deploy so `/api/privacy`, `/mcp/*`, and other private routes require header `X-Ikigai-Token`. Replay (`/api/workspace`, `/api/run`, …) stays public on Cloud Run and only serves the **fixture** corpus. Slack routes stay signature-checked and do not use that header.

## 3. Connect Slack (optional — live agent)

Replay does not need this. This is how the Cloud Run service becomes `@Ikigai` in a workspace.

1. Open [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**.
2. Paste [`infra/slack-manifest.yaml`](infra/slack-manifest.yaml). Replace the `run.app` URLs with your Cloud Run URL if you deployed your own project.
3. **Install App** to the workspace.
4. Copy **Bot User OAuth Token** (`xoxb-…`) and **Signing Secret** into Cloud Run env (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`) or into local `.env`.
5. Confirm:
   - **Event Subscriptions** request URL: `https://<service>.run.app/slack/events` (bot events: `app_mention`, `message.channels`, `message.groups`, `message.im`)
   - **Slash Commands** `/ikigai` and `/check-ikigai`: `https://<service>.run.app/slack/commands`
   - **Interactivity** request URL: same as events
6. In each channel: `/invite @Ikigai`.

**Local Slack (laptop only):** set `SLACK_APP_TOKEN` (`xapp-…`) and turn **Socket Mode** on for that app. Cloud Run must use HTTP events, not Socket Mode.

Leave `SLACK_USER_TOKEN` empty unless you have a user token with `search:read`. Without it, Ikigai scans `conversations.history` on channels the bot is in.

### Smoke in Slack

| Type | Expect |
|---|---|
| `/ikigai logout` | Private goodbye |
| `/ikigai login` | Private catch-up |
| `/ikigai should we rotate tokens every night?` | Private card, only you |
| `@Ikigai should we rotate tokens every night?` | Public thread reply |
| `/check-ikigai @someone` | That person's calls + supported / opposed |
| `@Ikigai hello` | Silence |

## MCP

On Cloud Run these routes need `X-Ikigai-Token` if `IKIGAI_API_TOKEN` is set. Locally they are open.

- `POST /mcp/query_decisions` `{"query":"..."}`
- `POST /mcp/check_supersession` `{"text":"..."}`

## What we do not store

Message text, Slack user IDs, embeddings, or a vector index of the workspace. Confirm with **Graph inspector** in Replay or `GET /api/privacy` (local).
