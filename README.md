# Ikigai

Decision memory for Slack. **All Things Agentic** · track **Taskmaster**.

When someone reopens a settled question, Ikigai finds the original call — even when the two conversations share almost no vocabulary. It is not a chatbot. Greetings, thanks, and emoji-only prompts get no reply and do not call a model.

Public and private are separate. `@Ikigai` is a channel reply everyone can see. `/ikigai` is ephemeral: only you see it.

## For judges

You do **not** need a Slack workspace, GCP project, or Vertex account to evaluate the agent.

1. **Demo video** (primary). The live Slack agent is what the product is.
2. **Replay UI** (no Slack). Run locally with the steps below, then type `Let's rotate tokens every night.` You should get the lock-free rotator reversal and the earlier 401 cascade — not a keyword match. Full click-through: [Reproducible testing](#reproducible-testing).
3. **Hosted Replay** (no Slack, no laptop):
   - App: https://ikigai-uipuf5bksa-uc.a.run.app
   - Health: https://ikigai-uipuf5bksa-uc.a.run.app/api/health
   - Open the app. Fixture threads stay in each channel. Switch accounts with **@you / @priya / @marcus / @aisha**.
   - Logout is per account. As @priya, **/ikigai logout**, switch to @marcus, **Message** a proposal, switch back, **/ikigai login**. Catch-up is only what landed while Priya was away — not the whole fixture history.
   - Direct messages: **ikigai** (bot, searches every chat), **priya**, **marcus**, **aisha**. Private groups: **core-leads**, **oncall-leads**, **growth-leads** — each with its own thread.
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

A card leads with one warm line (`This was already decided` / `Heads up — this was later reversed` / `Two live approaches here` / `I didn't find a matching call`), then **Status**, **Confidence**, **Who** (`@username`), **Now**, and **Open thread**. A miss does not fill Who or Now, and confidence stays low — never 100% on a guess.

## Stack

| Requirement | This repo |
|---|---|
| Gemini 3.5+ | `gemini-3.5-flash-lite` (watcher gate), `gemini-3.5-flash` (lookup / login / check), `gemini-embedding-001` (transient rank) |
| Google agent framework | Google ADK — `root_agent` in `ikigai/agent.py` |
| GCP | Cloud Run, Firestore, Vertex AI (Pub/Sub enabled on deploy) |

Search, login, and check use **one** Flash call each. Lookup thinking is **LOW** when one clear hit is already in a small set of notes, and **MEDIUM** only when notes conflict, several threads compete, or the match is thin. The unsolicited watcher adds a Flash-Lite gate (`thinking=MINIMAL`). Probes are heuristic (no model).

## Architecture

```
Slash / @mention / DM / Replay UI
        │
        ▼
Cloud Run  (ACK < 3s, then lookup)
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
│     thinking LOW, or MEDIUM if needed│
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

On Windows, if `.env` has Slack tokens, set `IKIGAI_NO_SOCKET=1` so uvicorn does not start Socket Mode (that path fails TLS on some laptops). Cloud Run always uses HTTP events, not Socket Mode.

Open http://127.0.0.1:43177

- **Workspace** — pick a fixture channel, paste a proposal, Run.
- Try `Let's rotate tokens every night.` then `thanks!` (should stay silent).
- **Graph inspector** — derived labels only; no message text.
- **Architecture** / **Cost** — stack and the day's meter.

Without `GEMINI_API_KEY` (and without Vertex), lookup returns 503. The product does not fake Gemini.

## Reproducible testing

No Slack workspace is required for A or B. Slack is C.

### A. Automated tests (no Slack, no Gemini)

From the repo root, venv on, **unset** `GOOGLE_CLOUD_PROJECT` if `.env` points at a live GCP project (otherwise `test_health` / `test_privacy` can hang on SSL):

```bash
python -m pytest tests/test_core.py tests/test_api.py -q
```

Expect every test to pass. These hit FastAPI with `FixtureSlack` and mocked or skipped Gemini. They do not call a live Slack workspace.

### B. Replay UI (same pipeline as Slack, fixture workspace)

**Hosted (no laptop):** open https://ikigai-uipuf5bksa-uc.a.run.app — first load can take ~15s if the service is cold.

1. Click **Skip** on the tour.
2. Stay **@you**. Open **#security**. Select **/ikigai**.
3. Type `Let's rotate tokens every night.` and search.
4. Expect a **reversed** card: stagger after the 401s, then nightly rotation again via the lock-free rotator. **Status**, **Confidence**, **Who**, **Now**. Not a keyword match — the question never said “stagger.”
5. Select **Message**. Type `thanks!`. Expect silence (no card, no Gemini).
6. **/check-ikigai** with `priya`. Expect Priya’s calls in that channel plus who supported or opposed.
7. As **@priya**, **/ikigai logout**. Switch to **@marcus**, **Message** a short proposal. Switch back to **@priya**, **/ikigai login**. Catch-up is only what Marcus posted after logout — not the 2024 fixture history.

Health: `GET https://ikigai-uipuf5bksa-uc.a.run.app/api/health` should be `{"ok": true, ...}`.

**Local:** after the uvicorn steps above, do the same at http://127.0.0.1:43177. Lookup needs `GEMINI_API_KEY` or Vertex.

### C. Live Slack (your Cloud Run, HTTP events)

You **cannot** create a new Slack app and point it at the public Cloud Run URL. HMAC uses **this** service’s signing secret, so a stranger’s app will get `401`. To reproduce Slack, deploy your own service and put **your** tokens on it. The hosted agent in the demo video is already installed in the submission workspace.

1. Deploy with [section 2](#2-deploy-to-google-cloud). Confirm `https://<YOUR>.run.app/api/health` is `"ok": true`.
2. Open [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**.
3. Paste [`infra/slack-manifest.yaml`](infra/slack-manifest.yaml). Replace every `ikigai-uipuf5bksa-uc.a.run.app` with `<YOUR>.run.app`. Leave **Socket Mode off**.
4. **Install App** to a workspace you admin.
5. Copy **Bot User OAuth Token** (`xoxb-…`) and **Signing Secret**.
6. Put them on Cloud Run (never commit `.env`):

```bash
gcloud run services update ikigai --region us-central1 \
  --update-env-vars "SLACK_BOT_TOKEN=xoxb-…,SLACK_SIGNING_SECRET=…"
```

7. In Slack → your app → **Event Subscriptions** and **Slash Commands**, confirm the request URLs verify (green).
8. In a **public channel**: `/invite @Ikigai`. The bot only reads channels it is in.
9. Seed a call the channel does not already have, for example post:  
   `from now on runtime flags go through LaunchDarkly. env vars are just for boot-time config.`
10. Then run the table below. You should see **Searching decision history…** within 3 seconds, then the card. If Slack says `operation_timeout` and never ACKs, the service is cold or still waiting on Gemini before ACK — that is a bug; a warm instance should ACK first.

| What you type | Where | What you should see |
|---|---|---|
| `/ikigai should we put the kill switch in an env var?` | Same channel | Private card. Only you. LaunchDarkly / not env. **Who**, **Now**. |
| `@Ikigai should we put the kill switch in an env var?` | Same channel | Same lookup, **public** in the thread. |
| `/ikigai hello` or `@Ikigai thanks` | Same channel | Silence. No card. |
| `/check-ikigai @YourSlackUsername` | Same channel | That person’s calls **in this chat**, plus supported / opposed. Use a Slack `@username`, not a display name. |
| `/ikigai logout` | Same channel | Private goodbye. Marks **you** away. |
| Post a decision-like message as someone else (or another account) | Same channel | Ordinary Slack message. |
| `/ikigai login` | Same channel | Private catch-up of what landed **after your logout**, not the whole history. |
| DM **Ikigai**: `should we put the kill switch in an env var?` | 1:1 with the bot | Private lookup across channels the bot can see. |

Leave `SLACK_USER_TOKEN` empty unless you have a user token with `search:read`. Without it, Ikigai scans `conversations.history` on channels it has joined.

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

## MCP

On Cloud Run these routes need `X-Ikigai-Token` if `IKIGAI_API_TOKEN` is set. Locally they are open.

- `POST /mcp/query_decisions` `{"query":"..."}`
- `POST /mcp/check_supersession` `{"text":"..."}`

## What we do not store

Message text, Slack user IDs, embeddings, or a vector index of the workspace. Confirm with **Graph inspector** in Replay or `GET /api/privacy` (local).
