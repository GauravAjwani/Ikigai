# Ikigai — Build Plan (historical)

Decision memory for Slack. Track: **Taskmaster**.

**This file is the original planning note.** The product is implemented. Use [`README.md`](README.md) for setup, architecture, and how to call the agent. Some details below (card layout, probe generation, separate login slash commands) were changed in the shipped code.

## 1. What we are actually building

A working agent that watches Slack, detects when someone is about to re-open a settled question, and **privately** tells that person:

- what was decided
- why
- what happened after
- whether it is still current, reversed, or a concurrent fork
- a permalink to the original thread

It is not a chatbot. It does not join the public conversation unless the user chooses to share. About **95% of messages produce no visible response**.

The original write-up is the product. This plan keeps that product and changes three things:

1. **Replatform onto the required Google stack** (Gemini 3.5, a Google agent framework, Cloud Run / Firestore / Pub/Sub).
2. **Make retrieval actually work** instead of demoing the happy path. Hybrid derived-graph + live Slack search, plus a fixture workspace and an eval harness.
3. **Keep the first paid GCP run under $50**, with a kill switch so a thinking-token accident cannot blow the budget.

## 2. What was good in the original (keep)

| Idea | Why it stays |
|---|---|
| Silence as the core UX | A Slack agent that talks all the time is noise |
| Cross-vocabulary probes | Keyword search cannot connect “rotate tokens every night” to “synchronized credential renewal caused 401s” |
| Transient embed-rank-destroy | Semantic match without a persistent copy of Slack |
| Ephemeral cards, user chooses to share | Wrong in private. Right in public. |
| Derived metadata only at rest | Labels, status, confidence, permalinks, edges. Never message text, user IDs, or embeddings |
| Three entry points | `/ikigai`, `/check-ikigai`, passive watcher |
| Warning intensity follows risk | Current decision: calm. Reversed decision: loud |
| Temporal reasoning for supersession | Replacement over time vs two teams diverging concurrently |
| MCP `query_decisions` / `check_supersession` | Same privacy boundary for external agents |

## 3. What we change (make it better, and make it real)

The original was an AWS Bedrock pipeline with a live-Slack recall ceiling of 72.5% because Slack search was keyword-only and the graph never warmed up. We fix both.

### 3.1 Hybrid retrieval, not search-only

Two indexes, one privacy rule:

- **Live Slack** via `assistant.search.context` (Real-Time Search). Permission-inherited. Content lives only in request memory.
- **Derived decision graph** in Firestore: label, concepts, status, confidence, permalink, edges. No message text.

When the gate says “this message *is* a decision being made,” we write a derived record **after user-visible work is done**, still without storing the text. That is the “historical warm-up” the original listed as future work. We ship a going-forward version in v1 (no full-channel crawl — that would burn rate limits and budget).

At query time: graph hit → fetch the live thread from Slack by permalink. Miss or weak hit → probe Slack RTS in parallel → transient rank → adjudicate.

This is the single biggest product upgrade. Search-only cannot beat Slack’s retrieval ceiling. A content-free graph can.

### 3.2 Use Slack’s own semantic search

Slack RTS now treats a natural-language question as a semantic query. The original’s probes were fighting a keyword API. We send:

- 2–3 **decision-mechanism / consequence / alternative** probes (the ablation that doubled recall)
- 1 **natural-language question** aimed at Slack semantic search (“Has this team already decided against nightly credential rotation because it caused 401 cascades?”)

Cap **3 Slack searches per trigger** so we stay inside the ~10 req/min/user RTS budget.

### 3.3 Cheap pre-silence before any model

A zero-cost filter drops emoji-only, `+1`, `thanks`, gifs, and empty replies. Those never touch Gemini. The 95% silence target is then: prefilter + Flash-Lite gate, not “call a model on every message.”

### 3.4 Feedback on the private card

If the match is wrong, the user taps **Not the same decision**. That writes a negative edge on the derived graph. If two candidates are close, the card asks one clarifying question instead of guessing. Still private. Still Taskmaster — the agent took action, then adapted.

### 3.5 A working model without a Slack install

Judges and local dev get a **Workspace Replay** UI: a fixture Slack corpus, a compose box, and the same ephemeral card. The pipeline is identical; only the transport changes (`SlackLiveClient` vs `SlackFixtureClient`).

If the Slack path were stubbed, this would be a demo. The fixture client implements the same search/thread interface the live client does, and the eval suite runs against it.

### 3.6 Do not use ADK SlackRunner

`SlackRunner` replies to DMs and mentions. That is the opposite of Ikigai. Slack Bolt owns events, slash commands, and ephemeral Block Kit. ADK owns the pipeline as a sequential agent, not a chat loop.

## 4. Track and hackathon mapping

**Category: Taskmaster**

This is a multi-step chore (re-litigating settled decisions) that the agent handles: gate, probe, search, rank, adjudicate, private delivery, graph write. It is not a text generator.

| Requirement | How we meet it |
|---|---|
| Gemini 3.5 or newer | `gemini-3.5-flash-lite` (gate, probes) and `gemini-3.5-flash` (adjudication) via Vertex AI in cloud, Gemini API locally |
| Google agent framework | Google ADK sequential pipeline |
| GCP infrastructure | Cloud Run, Pub/Sub, Firestore |
| Beyond a chat loop | Async watcher, tools, derived graph, MCP |
| Proof on GCP | Cloud Run URL + console screenshots in the later demo video |

Out of v1 on purpose: Fortified Enterprise Fleet theater, Veo/Lyria, adaptive taxonomy crawler, guided conflict workshops, full-channel backfill.

## 5. System design

```
Slack event / slash command / Replay UI
        │
        ▼
Cloud Run  (ACK in <3s, enqueue)
        │
        ▼
Pub/Sub
        │
        ▼
┌──────────────────────────────────────┐
│  ADK sequential agent                │
│                                      │
│  0. Prefilter (no model)             │── obvious chatter exits
│  1. Gate  gemini-3.5-flash-lite      │── ~95% total exits
│     thinking_level = MINIMAL         │
│  2. If NEW decision: enqueue graph    │
│     write (labels only)              │
│  3. Probe gen  flash-lite            │
│  4. Retrieve                         │
│       Firestore graph lookup         │
│       Slack RTS (≤3 parallel)        │
│  5. Transient rank  gemini-embedding │── destroyed after request
│  6. Adjudicate  gemini-3.5-flash     │
│     thinking_level = LOW, or MEDIUM  │
│     when notes conflict / thin match │
└──────────────────────────────────────┘
        │
        ▼
Ephemeral Block Kit card  (or Replay UI card)
        │
        ▼
Firestore  labels · status · confidence · permalinks · edges
NEVER      message text · user IDs · embeddings
```

### 5.1 Three interaction paths (different feedback)

| Path | Feedback | Silence |
|---|---|---|
| Watcher | None unless a high-cost match | Default |
| `/check-ikigai` | Immediate “Checking this thread…” then card or “No prior decision found” | Never silent |
| `/ikigai <query>` | Immediate “Searching decision history…” then card or empty state | Never silent |
| Replay UI | Same cards; also show gate reason in a debug drawer | Same rules |

Watcher only posts when **all** of these hold:

- gate = decision-like proposal
- retrieval returned at least one candidate above rank threshold
- adjudicator says same underlying decision
- confidence ≥ threshold (start at 0.72, tune on evals)
- risk of ignoring the match is high (reopening a current decision, or following a reversed one)

A current, well-supported decision gets a calm card. A reversed decision gets a warning. Concurrent forks get a “two live approaches” card, not a false supersession.

### 5.2 Privacy (enforced by schema, not a retention policy)

Firestore `decisions/{id}`:

```
decision_id
label                  # "nightly credential rotation"
concepts[]             # controlled vocabulary ids
status                 # current | reversed | concurrent | unknown
confidence
permalink
channel_id             # needed to re-fetch live; not a user id
thread_ts
created_at, updated_at
edges[]                # {type: supersedes|conflicts|not_same, target_id}
```

A `GET /internal/privacy-inspector` dumps actual records and fails CI if any field looks like message text, a user id (`U…`), or a vector.

User tokens: slash/RTS with a **bot token + `action_token` from the triggering event** so we inherit the user’s search permissions without storing user tokens. Local/MCP may use a user token from env, in memory only.

### 5.3 Slack app (real, not mocked)

Manifest-driven Slack app:

- Slash: `/ikigai`, `/check-ikigai`
- Events: `message.channels`, `message.groups` (watcher; ignore subtype bots/joins)
- AI features enabled so RTS `action_token` is present
- Scopes: `chat:write`, `commands`, `search:read.public`, plus user scopes for private search when OAuth is used
- HTTP Events API → Cloud Run (not Socket Mode). Socket Mode needs a always-on websocket and costs more.

Always ACK in 3 seconds. Work happens on Pub/Sub. Commands use `response_url`. Replies use `chat.postMessage` in the channel.

## 6. Stack (one product, one Cloud Run service)

```
ikigai/
  agent/          Google ADK sequential agents + tools
  slack/          Bolt handlers, Block Kit, manifest
  api/            FastAPI: Replay UI backend, MCP, inspector, evals
  web/            Vite + React + Tailwind + shadcn (simulator + inspector)
  evals/          golden sets + runner
  fixtures/       synthetic Slack workspace
  infra/          deploy.sh, slack-manifest.yaml, IAM notes
```

- **Runtime:** Python 3.12, FastAPI, Slack Bolt
- **Agent:** Google ADK (sequential: gate → probes → retrieve → rank → adjudicate)
- **Models:** Vertex `gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-embedding-001`
- **Local fallback:** Gemini API key (`GEMINI_API_KEY`) so we can build before credits
- **State:** Firestore (emulator locally)
- **Async:** Pub/Sub (in-process queue locally)
- **Secrets:** Secret Manager in cloud; `.env` locally
- **Observability:** Cloud Logging + ADK/OpenTelemetry traces of the reasoning chain (stage, tokens, cost, not message text)

Genkit is a valid alternative (flows fit this pipeline). We still pick **ADK** because the hackathon is agent-platform-shaped and sequential agents-with-tools is the honest architecture. We will not also add Genkit.

## 7. Cost envelope — first GCP run < $50

### 7.1 Unit costs (approx., global Vertex, Aug 2026)

| Stage | Model | Thinking | Typical tokens | Cost / call |
|---|---|---|---|---|
| Gate | 3.5 Flash-Lite | MINIMAL | ~400 in / ~40 out | ~$0.0002 |
| Probes | 3.5 Flash-Lite | MINIMAL | ~600 in / ~200 out | ~$0.0007 |
| Embed | embedding-001 | — | ~2.5k in | ~$0.0004 |
| Adjudicate | 3.5 Flash | LOW, or MEDIUM if notes conflict | ~3k in / ~800 out incl. thinking | ~$0.012 |
| **Full pipeline** | | | | **~$0.014** |

Chatter never reaches a model (prefilter). Non-decisions that look linguistic still hit only the gate.

### 7.2 First-run budget (credits on, deploy + prove it works)

| Item | Cap |
|---|---|
| Gemini (gates + ≤250 full pipelines including evals) | $15 |
| Cloud Run min instances **0**, 1 vCPU / 512Mi, few hours of poking | $8 |
| Firestore + Pub/Sub + logging + Artifact Registry | $2 |
| Mistake buffer (thinking left on, retries, extra evals) | $15 |
| **Hard stop** | **$40 billed, $50 absolute** |

Do **not** run a 700-search live Slack benchmark on the first credits. That is how the original burned rate limits. First run = fixture evals + a handful of live Slack smokes.

### 7.3 Kill switches (must ship on day one)

- `IKIGAI_DAILY_BUDGET_USD` default `10`
- Token + USD meter per stage, written to Firestore `meter/daily`
- If meter ≥ budget: watcher goes fully silent; slash commands return “budget paused”
- `thinking_level` is set in code (MINIMAL / LOW, MEDIUM only when lookup needs more context), not left at Flash’s default (default thinking would 5–10× the bill)
- Cloud Run `minScale=0`, `maxScale=2`
- Billing budget alert at $10 / $25 / $40 in GCP (manual step when credits arrive)
- No Vertex Vector Search, no always-on GPU, no channel backfill job

Local development uses the Gemini API free/paid key and **never** requires GCP spend.

## 8. Working model, not a demo

A demo is a scripted screenshot. A working model is:

1. **Deterministic fixture workspace** (`fixtures/acme-eng.json`) with:
   - 40 cross-vocabulary decision pairs (including the token-rotation / 401-cascade pair)
   - 15 supersession cases (reversal over time vs concurrent forks)
   - 100 chatter messages that must stay silent
   - ~20 “new decision” messages that must write derived labels
2. **Eval CLI** `python -m evals.run` that scores gate, retrieval, adjudication, silence rate, and privacy inspector. CI fails if scores regress below:
   - Silence on chatter ≥ 93%
   - Gate precision on “is a decision” ≥ 85%
   - Cross-vocab recall (fixture) ≥ 85%
   - Supersession precision ≥ 90% on the 15 cases
   - Privacy inspector: 0 content leaks
3. **Workspace Replay UI** that a judge can use with no Slack account: type “Let’s rotate tokens every night.” and get the 401-cascade card.
4. **Live Slack path implemented**, not faked: Bolt handlers, ephemeral cards, slash commands, RTS client. If Slack credentials are missing, the server still runs on fixtures and says so.
5. **Privacy inspector** against the real Firestore emulator / project.
6. **Cost page** showing per-stage USD for the current day.

## 9. UX (cards and Replay)

Visual language stays quiet.

- **Current decision** — no warning badge. Decision, why, aftermath, permalink, Not the same.
- **Reversed** — explicit warning. “This was later reversed. Following it may recreate a failure the org already paid for.” Link to the reversing thread.
- **Concurrent fork** — “Two live approaches, not a reversal.” Both permalinks.
- **No match** (commands only) — “No prior decision found in the conversations you can access.”
- **Share** — posts a short public summary the user can edit before send. Ikigai never posts that on its own.

Desktop and mobile: Slack cards already reflow. Replay UI is a two-pane layout on desktop (channel + private card) and a stacked layout on small screens.

Empty / loading / error:

- Commands: loading message within 3s, then result or a plain error (“Slack search rate-limited, try in a minute”).
- Watcher: errors are swallowed. Never complain in-channel.
- Replay: visible error banner if Gemini is down; fixture search still runs so the UI is not a blank page.

## 10. MCP

Same process, `/mcp`:

- `query_decisions(query)` — derived graph + live re-fetch, permissioned by the caller’s Slack token if provided
- `check_supersession(permalink_or_text)` — status + edges

No content stored. No results without a caller identity in the live path.

## 11. Implementation order (when you say build)

Do this in order so the first GCP run stays cheap and the product is real before it is pretty.

1. **Local skeleton** — FastAPI, Replay UI, fixture client, ADK pipeline with Gemini API key, prefilter + gate + probes + fake rank + adjudicate.
2. **Evals** — golden sets and CLI. Iterate prompts until fixture targets pass. This is the working model.
3. **Graph write + privacy inspector + cost meter.**
4. **Block Kit cards + slash command shapes in Replay** (identical JSON Slack will use).
5. **Commit / push.** Then, with credits: Firestore, Pub/Sub, Cloud Run min=0, Secret Manager, Vertex.
6. **Slack manifest + live client** behind env flags. Smoke 5 messages, not 700.
7. **README, architecture diagram, spin-up, demo script.**

## 12. What we need from you when credits arrive

- GCP project id and permission to enable Vertex AI, Cloud Run, Firestore, Pub/Sub, Secret Manager
- A billing budget alert at $40
- Slack workspace you can install an internal app into (can be a throwaway)
- Gemini: Vertex in that project (cloud) + optional AI Studio key (local)

Until then, local work can proceed on fixtures + `GEMINI_API_KEY` only. **This planning pass does not start that work.**

## 13. Risks

| Risk | Mitigation |
|---|---|
| Flash default thinking blows the budget | Hard-code MINIMAL/LOW, MEDIUM only when lookup needs more context; meter; kill switch |
| Slack RTS rate limit | ≤3 searches/trigger; command ACK; no backfill job |
| ADK SlackRunner temptation | Do not import it |
| Storing text “just for debug” | Inspector CI; no log of message bodies |
| Treating concurrent forks as reversals | Temporal adjudicator prompt + 15-case eval |
| Demo-only Slack | Fixture interface + live client share a protocol |
| Cloud Run cold start > 3s | ACK first, Pub/Sub rest |

## 14. Success for v1

A teammate types “Let’s rotate tokens every night.” Ikigai stays out of the channel and privately shows the older 401-cascade decision, why it was made, that it is still current, and a permalink. Chatter gets nothing. A reversed decision is visually louder than a current one. Firestore contains no message text. Fixture evals pass. First GCP bill is under $50.
