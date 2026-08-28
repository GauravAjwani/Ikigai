import { useMemo, useState } from "react";

type ArchModels = {
  gate?: string;
  probes?: string;
  adjudicate?: string;
  embed?: string;
};

type ArchPayload = {
  track?: string;
  models?: ArchModels;
  stored?: string[];
  never_stored?: string[];
  gcp?: string[];
  framework?: string;
};

type NodeId =
  | "replay"
  | "slack"
  | "mcp"
  | "guard"
  | "fastapi"
  | "pipeline"
  | "notes"
  | "gemini"
  | "firestore"
  | "slacklive"
  | "card";

type Node = {
  id: NodeId;
  title: string;
  kicker: string;
  body: string;
  talks: string;
};

const NODES: Node[] = [
  {
    id: "replay",
    title: "Replay UI",
    kicker: "Frontend",
    body: "Vite + React, served from FastAPI as web/dist. Calls /api/run, /api/graph, /api/cost. Never holds GEMINI_API_KEY and never talks to Google or Firestore.",
    talks: "HTTPS JSON to FastAPI only",
  },
  {
    id: "slack",
    title: "Slack",
    kicker: "Client",
    body: "@Ikigai, /ikigai, /check-ikigai, and DMs hit Cloud Run at /slack/events and /slack/commands. Bolt ACKs in under 3s, then runs the same pipeline as Replay.",
    talks: "Events API / Socket Mode → FastAPI",
  },
  {
    id: "mcp",
    title: "MCP",
    kicker: "Client",
    body: "POST /mcp/query_decisions and /mcp/check_supersession. Cloud Run requires IKIGAI_API_TOKEN. Returns permalinks and status, not Slack snippets.",
    talks: "HTTPS JSON to FastAPI only",
  },
  {
    id: "guard",
    title: "Security edge",
    kicker: "Guard",
    body: "ApiGuardMiddleware: payload cap, security headers, IKIGAI_API_TOKEN on Cloud Run for /api and /mcp. Slack HMAC (v0) fail-closed. Events API retries (x-slack-retry-num) are dropped so Gemini slowness does not double-post.",
    talks: "Every request hits this before the pipeline",
  },
  {
    id: "fastapi",
    title: "Cloud Run · FastAPI",
    kicker: "Backend",
    body: "ikigai.api:app is the only process that talks to Gemini, Firestore, and Slack search. Locally: uvicorn on :43177. Production: Cloud Run (Vertex via IKIGAI_VERTEX).",
    talks: "Owns every outbound Google and Slack call",
  },
  {
    id: "pipeline",
    title: "ADK pipeline",
    kicker: "Agent",
    body: "prefilter (no model) → Flash-Lite gate on the watcher only → cheap probes (heuristic, no Gemini) → retrieve + thread notes → embed-rank-destroy → Flash lookup. Not a chat loop. Not ADK SlackRunner.",
    talks: "Calls gemini_client, graph(), slack_store, notes.py",
  },
  {
    id: "notes",
    title: "Untrusted notes",
    kicker: "Prompt boundary",
    body: "notes.py wraps Slack text as UNTRUSTED data inside <<< >>>. Gemini is told to treat it as evidence, never as instructions, and never to paste raw quotes into user-facing fields. Working notes are never shown raw in Slack.",
    talks: "Pipeline → Gemini only. Not stored.",
  },
  {
    id: "gemini",
    title: "Gemini 3.5",
    kicker: "Models",
    body: "Reached only from ikigai/gemini_client.py. Gate (watcher) is Flash-Lite. Lookup, briefing, and stances are Flash. Rank is gemini-embedding-001. Probes are heuristic — they do not call a model. System instruction: notes only, no jailbreaks from Slack text.",
    talks: "google.genai.Client ← FastAPI only",
  },
  {
    id: "firestore",
    title: "Firestore",
    kicker: "Database",
    body: "Derived decision graph: label, concepts, status, confidence, permalink, edges. Local fallback is MemoryGraph. Gemini never reads or writes it — the pipeline upserts after the card is built.",
    talks: "graph().upsert / list from FastAPI",
  },
  {
    id: "slacklive",
    title: "Slack search",
    kicker: "Live recall",
    body: "Permission-inherited search and channel history. Snippets exist only in request memory for ranking. FixtureSlack stands in when no bot token is set.",
    talks: "slack_store from FastAPI, discarded after the request",
  },
  {
    id: "card",
    title: "Decision card",
    kicker: "Response",
    body: "JSON card to Replay, Block Kit to Slack. Watcher stays silent unless a costly match. Commands always answer. Share is a user action — Ikigai does not post the private card publicly.",
    talks: "FastAPI → Replay or Slack",
  },
];

function node(id: NodeId): Node {
  return NODES.find((n) => n.id === id)!;
}

export default function Architecture({
  health,
  arch,
}: {
  health: Record<string, unknown> | null;
  arch: ArchPayload | null;
}) {
  const [sel, setSel] = useState<NodeId>("gemini");
  const models = arch?.models ?? {};
  const selected = node(sel);

  const geminiHow = useMemo(() => {
    if (health?.vertex) return "Vertex AI (google.genai.Client vertexai=True)";
    if (health?.gemini) return "Gemini API key (local / Secret Manager)";
    return "Not configured — API returns 503";
  }, [health]);

  const graphName = String(health?.graph || "MemoryGraph");
  const storeName = String(health?.store || "FixtureSlack");

  return (
    <div className="h-full min-h-0 overflow-auto">
      <div className="px-6 pt-6 pb-8 max-w-[1100px]">
        <p className="text-[11px] uppercase tracking-[0.16em] text-[#8b8790]">System map</p>
        <h1 className="serif text-[32px] leading-none mt-1">How Gemini is wired</h1>
        <p className="text-[14px] text-[#8b8790] leading-relaxed mt-3 max-w-2xl">
          Slack text never goes to Gemini as a prompt. It is wrapped as untrusted
          notes, ranked in memory, then discarded. FastAPI on Cloud Run is still
          the only <code className="text-[#e8e4db]">google.genai</code> client.
          A security edge sits in front of every hop.
        </p>

        <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
          <Badge ok={Boolean(health?.gemini)} label={geminiHow} />
          <Badge ok={Boolean(health?.gcp_project)} label={health?.gcp_project ? `GCP ${String(health.gcp_project)}` : "No GCP project"} />
          <Badge ok={graphName === "FirestoreGraph"} label={`Graph · ${graphName}`} />
          <Badge ok={Boolean(health?.slack)} label={`Store · ${storeName}`} />
        </div>

        <p className="mt-5 text-[12px] text-[#8b8790]">
          Click a box to inspect that hop. Sage arrows are the only Gemini path.
        </p>
        <div className="mt-3 overflow-x-auto">
          <Diagram selected={sel} onSelect={setSel} models={models} />
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="border border-[#2a2e38] rounded-lg p-4 bg-[#15181f]">
            <div className="text-[11px] uppercase tracking-wider text-[#8b8790]">{selected.kicker}</div>
            <div className="serif text-[22px] mt-1">{selected.title}</div>
            <p className="text-[14px] leading-relaxed mt-2 text-[#e8e4db]/90">{selected.body}</p>
            <div className="mt-3 text-[12px] text-[#8faf86]">{selected.talks}</div>
          </div>
          <div className="border border-[#2a2e38] rounded-lg p-4">
            <div className="text-[11px] uppercase tracking-wider text-[#8b8790]">Gemini models</div>
            <dl className="mt-3 space-y-2 text-[13px]">
              <KV k="Gate (watcher)" v={models.gate || "gemini-3.5-flash-lite"} />
              <KV k="Probes" v="heuristic — no model" />
              <KV k="Lookup / briefing" v={models.adjudicate || "gemini-3.5-flash"} />
              <KV k="Transient rank" v={models.embed || "gemini-embedding-001"} />
            </dl>
          </div>
        </div>

        <h2 className="serif text-[22px] mt-10">Who talks to whom</h2>
        <p className="text-[13px] text-[#8b8790] mt-1 mb-4">
          Gemini is a backend RPC. It has no session to the Replay UI, Slack, or Firestore.
        </p>
        <div className="overflow-x-auto border border-[#2a2e38] rounded-lg">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-[#8b8790] border-b border-[#2a2e38]">
                <th className="py-2.5 px-4 font-medium">From</th>
                <th className="py-2.5 px-4 font-medium">To</th>
                <th className="py-2.5 px-4 font-medium">How</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["Replay UI", "FastAPI", "fetch POST /api/run  ·  no Gemini key in the browser"],
                ["Slack", "Guard", "HMAC v0 signature  ·  drop x-slack-retry-num  ·  then Bolt ACK"],
                ["MCP / Replay", "Guard", "IKIGAI_API_TOKEN on Cloud Run for /api and /mcp"],
                ["FastAPI", "Gemini 3.5", "untrusted notes via gemini_client.py  ·  not raw Slack quotes"],
                ["FastAPI", "Firestore", "graph().upsert  ·  labels, status, permalinks, edges"],
                ["FastAPI", "Slack search", "slack_store  ·  packed as notes, discarded after the request"],
                ["Gemini", "Replay UI", "Never — the browser only reads the JSON card from FastAPI"],
                ["Gemini", "Firestore", "Never — the pipeline writes derived metadata after lookup"],
              ].map(([from, to, how], i) => {
                const never = from === "Gemini";
                return (
                  <tr key={i} className="border-t border-[#2a2e38]">
                    <td className="py-2.5 px-4 whitespace-nowrap">{from}</td>
                    <td className="py-2.5 px-4 whitespace-nowrap">{to}</td>
                    <td className={`py-2.5 px-4 ${never ? "text-[#d07255]" : "text-[#8b8790]"}`}>{how}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <h2 className="serif text-[22px] mt-10">Request path</h2>
        <p className="text-[13px] text-[#8b8790] mt-1 mb-4">
          Guard first, then FastAPI. Gemini only sees notes.py wrappers. Embeddings die
          with the request.
        </p>
        <ol className="space-y-3 text-[13px] leading-relaxed">
          <li className="flex gap-3">
            <Num n="1" />
            <span>
              Slack HMAC and Cloud Run API token are checked. Events API retries are
              dropped. Then Replay <code>POST /api/run</code>, Slack{" "}
              <code>/slack/commands</code> / <code>/slack/events</code>, or MCP{" "}
              <code>/mcp/query_decisions</code>.
            </span>
          </li>
          <li className="flex gap-3">
            <Num n="2" />
            <span>
              Prefilter drops chatter with no model. Watcher gate uses Flash-Lite on
              untrusted text. Commands skip the gate.
            </span>
          </li>
          <li className="flex gap-3">
            <Num n="3" />
            <span>
              Cheap probes are heuristic — no Gemini. Retrieve fans out to live Slack
              and the Firestore label graph, then packs thread notes.
            </span>
          </li>
          <li className="flex gap-3">
            <Num n="4" />
            <span>
              <code>embed()</code> ranks in memory and drops the vectors. Flash lookup
              reads notes only and writes a JSON verdict. Never a raw Slack quote.
            </span>
          </li>
          <li className="flex gap-3">
            <Num n="5" />
            <span>
              FastAPI writes derived labels to Firestore and returns a card to Replay or
              Block Kit to Slack. Gemini never sees the database.
            </span>
          </li>
        </ol>

        <h2 className="serif text-[22px] mt-10">What crosses the database</h2>
        <div className="mt-4 grid sm:grid-cols-2 gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-[#8faf86] mb-2">Stored</div>
            <ul className="text-[13px] space-y-1.5 text-[#e8e4db]/90">
              {(arch?.stored || ["derived labels", "status", "confidence", "permalinks", "edges"]).map(
                (x) => (
                  <li key={x} className="flex gap-2">
                    <span className="text-[#8faf86]">+</span>
                    {x}
                  </li>
                ),
              )}
            </ul>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider text-[#d07255] mb-2">Never stored</div>
            <ul className="text-[13px] space-y-1.5 text-[#e8e4db]/90">
              {(arch?.never_stored || [
                "Slack message text",
                "Slack user IDs",
                "content embeddings",
                "a persistent vector index",
              ]).map((x) => (
                <li key={x} className="flex gap-2">
                  <span className="text-[#d07255]">×</span>
                  {x}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-[#2a2e38] text-[#c8c4bc]">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-[#8faf86]" : "bg-[#5a564e]"}`} />
      {label}
    </span>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-[#8b8790]">{k}</dt>
      <dd className="text-right font-medium">{v}</dd>
    </div>
  );
}

function Num({ n }: { n: string }) {
  return (
    <span className="shrink-0 h-5 w-5 rounded-full border border-[#2a2e38] text-[11px] grid place-items-center text-[#d4a574]">
      {n}
    </span>
  );
}

function Diagram({
  selected,
  onSelect,
  models,
}: {
  selected: NodeId;
  onSelect: (id: NodeId) => void;
  models: ArchModels;
}) {
  return (
    <svg
      viewBox="0 0 960 620"
      className="w-full min-w-[720px] h-auto"
      role="img"
      aria-label="Ikigai architecture: clients to FastAPI to Gemini, Firestore, and Slack search"
    >
      <defs>
        <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8" fill="none" stroke="#5a564e" />
        </marker>
        <marker id="arrSage" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8" fill="none" stroke="#8faf86" />
        </marker>
      </defs>

      <Box x={24} y={28} w={210} h={70} id="slack" title="Slack" sub="@mention · slash · DM" selected={selected} onSelect={onSelect} />
      <Box x={250} y={28} w={220} h={70} id="replay" title="Replay UI" sub="React · fetch /api/*" selected={selected} onSelect={onSelect} />
      <Box x={486} y={28} w={178} h={70} id="mcp" title="MCP" sub="/mcp/query_decisions" selected={selected} onSelect={onSelect} />

      <line x1={129} y1={98} x2={129} y2={154} stroke="#5a564e" markerEnd="url(#arr)" />
      <line x1={360} y1={98} x2={360} y2={154} stroke="#5a564e" markerEnd="url(#arr)" />
      <line x1={575} y1={98} x2={500} y2={154} stroke="#5a564e" markerEnd="url(#arr)" />

      <Box
        x={24}
        y={158}
        w={640}
        h={78}
        id="fastapi"
        title="Cloud Run · FastAPI"
        sub="ikigai.api:app · ACK < 3s · serves web/dist · gemini_client.py"
        selected={selected}
        onSelect={onSelect}
      />

      <line x1={344} y1={236} x2={344} y2={262} stroke="#5a564e" markerEnd="url(#arr)" />

      <Box
        x={24}
        y={266}
        w={640}
        h={92}
        id="pipeline"
        title="ADK sequential pipeline"
        sub="prefilter → gate → probes → retrieve → embed-rank-destroy → adjudicate"
        selected={selected}
        onSelect={onSelect}
      />

      <text x="704" y="148" fill="#8faf86" fontSize="11" letterSpacing="0.14em">
        GEMINI
      </text>
      <Box
        x={704}
        y={158}
        w={232}
        h={200}
        id="gemini"
        title="Gemini 3.5"
        sub={`${models.gate || "flash-lite"} · ${models.adjudicate || "flash"} · embed`}
        selected={selected}
        onSelect={onSelect}
        accent
        tall
      />

      <line x1={664} y1={198} x2={702} y2={198} stroke="#8faf86" strokeWidth={2} markerEnd="url(#arrSage)" />
      <line x1={704} y1={318} x2={666} y2={318} stroke="#8faf86" strokeWidth={2} markerEnd="url(#arrSage)" />

      <line x1={178} y1={358} x2={178} y2={398} stroke="#5a564e" markerEnd="url(#arr)" />
      <line x1={510} y1={358} x2={510} y2={398} stroke="#5a564e" markerEnd="url(#arr)" />

      <Box
        x={24}
        y={402}
        w={308}
        h={86}
        id="firestore"
        title="Firestore graph"
        sub="labels · status · permalinks · edges"
        selected={selected}
        onSelect={onSelect}
      />
      <Box
        x={356}
        y={402}
        w={308}
        h={86}
        id="slacklive"
        title="Slack live search"
        sub="snippets in RAM · then destroyed"
        selected={selected}
        onSelect={onSelect}
      />

      <line x1={820} y1={358} x2={820} y2={444} stroke="#5a564e" strokeDasharray="5 4" />
      <text x={828} y={410} fill="#8b8790" fontSize="10">
        no DB session
      </text>

      <line x1={344} y1={488} x2={344} y2={516} stroke="#5a564e" markerEnd="url(#arr)" />
      <Box
        x={24}
        y={520}
        w={640}
        h={72}
        id="card"
        title="Decision card"
        sub="Replay JSON · Slack Block Kit · watcher silent unless costly"
        selected={selected}
        onSelect={onSelect}
      />
    </svg>
  );
}

function Box({
  x,
  y,
  w,
  h,
  id,
  title,
  sub,
  selected,
  onSelect,
  accent,
  tall,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  id: NodeId;
  title: string;
  sub: string;
  selected: NodeId;
  onSelect: (id: NodeId) => void;
  accent?: boolean;
  tall?: boolean;
}) {
  const on = selected === id;
  const stroke = on ? "#d4a574" : accent ? "#8faf86" : "#2a2e38";
  const fill = on ? "#1c1814" : accent ? "#141a16" : "#171a21";
  return (
    <g
      role="button"
      tabIndex={0}
      style={{ cursor: "pointer" }}
      onClick={() => onSelect(id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect(id);
      }}
    >
      <rect x={x} y={y} width={w} height={h} rx={8} fill={fill} stroke={stroke} strokeWidth={on ? 2 : 1} />
      {tall ? (
        <>
          <text x={x + 16} y={y + 36} fill="#8faf86" fontSize="11" letterSpacing="0.08em">
            MODELS
          </text>
          <text x={x + 16} y={y + 64} fill="#e8e4db" fontSize="20" fontFamily="Fraunces, Georgia, serif">
            {title}
          </text>
          <foreignObject x={x + 16} y={y + 80} width={w - 32} height={120}>
            <div className="text-[11px] leading-snug text-[#8b8790]">{sub}</div>
            <div className="text-[11px] leading-snug text-[#8faf86] mt-2">
              Vertex or API key. Called only by gemini_client.py.
            </div>
          </foreignObject>
        </>
      ) : (
        <>
          <text x={x + 14} y={y + 28} fill="#e8e4db" fontSize="14" fontWeight={500}>
            {title}
          </text>
          {sub ? (
            <foreignObject x={x + 14} y={y + 36} width={w - 28} height={36}>
              <div className="text-[11px] leading-snug text-[#8b8790]">{sub}</div>
            </foreignObject>
          ) : null}
        </>
      )}
    </g>
  );
}
