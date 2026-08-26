import { useEffect, useMemo, useState } from "react";
import {
  api,
  type Card,
  type Channel,
  type Message,
  type PipelineResult,
} from "./api";

type Tab = "replay" | "graph" | "cost" | "architecture";

const SAMPLES = [
  { label: "Nightly token rotation", text: "Let's rotate tokens every night." },
  { label: "Remember the 401s", text: "We shouldn't do a global rotation job, remember the 401s." },
  { label: "Kill switch in env", text: "Can we just put the checkout kill switch in an env var on Cloud Run?" },
  { label: "Move APM", text: "Grafana Cloud looks cheaper, should we move APM off the current vendor?" },
  { label: "Company-wide queue", text: "We should pick one company-wide queue. Everything on Postgres." },
  { label: "Chatter (should stay silent)", text: "thanks!" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("replay");
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("C-PLATFORM");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("Let's rotate tokens every night.");
  const [path, setPath] = useState<"watcher" | "search">("watcher");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [shared, setShared] = useState(false);
  const [graph, setGraph] = useState<{ records?: unknown[]; leaks?: string[]; backend?: string; ok?: boolean } | null>(null);
  const [cost, setCost] = useState<Record<string, unknown> | null>(null);
  const [arch, setArch] = useState<Record<string, unknown> | null>(null);

  const channel = useMemo(
    () => channels.find((c) => c.id === channelId),
    [channels, channelId],
  );

  async function loadWorkspace(id?: string) {
    const w = await api.workspace(id);
    setChannels(w.channels);
    setChannelId(w.channel_id);
    setMessages(w.messages);
  }

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    loadWorkspace().catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    if (tab === "graph") api.graph().then(setGraph).catch(() => {});
    if (tab === "cost") api.cost().then(setCost).catch(() => {});
    if (tab === "architecture") api.architecture().then(setArch).catch(() => {});
  }, [tab]);

  async function run() {
    setBusy(true);
    setError("");
    setShared(false);
    try {
      const data = await api.run({
        text: draft,
        channel_id: channelId,
        path,
        post: path === "watcher",
      });
      setResult(data.result);
      await loadWorkspace(channelId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const card: Card | null = result?.card ?? null;
  const gemini = Boolean(health?.gemini);

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-[220px] shrink-0 border-r border-[#2a2e38] bg-[#0e1014] flex flex-col">
        <div className="px-5 pt-6 pb-4">
          <div className="serif text-[28px] leading-none tracking-tight">Precedent</div>
          <div className="mt-2 text-[12px] text-[#8b8790] leading-snug">
            Decision memory for Slack. Wrong in private. Right in public.
          </div>
        </div>
        <nav className="px-2 mt-2 flex flex-col gap-0.5">
          {(
            [
              ["replay", "Workspace"],
              ["graph", "Graph inspector"],
              ["cost", "Cost"],
              ["architecture", "Architecture"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`text-left px-3 py-2 rounded-md text-[13px] ${
                tab === id ? "bg-[#171a21] text-[#e8e4db]" : "text-[#8b8790] hover:text-[#e8e4db]"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="mt-auto px-4 py-4 text-[11px] text-[#8b8790] space-y-1">
          <Row ok={gemini} label="Gemini 3.5" />
          <Row ok={Boolean(health?.gcp_project)} label="GCP project" />
          <Row ok={Boolean(health?.slack)} label="Slack live" />
          <div>Graph · {String(health?.graph || "—")}</div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 min-h-0 flex flex-col">
        {tab === "replay" && (
          <div className="flex flex-1 min-h-0">
            <div className="w-[200px] shrink-0 border-r border-[#2a2e38] bg-[#14171d] p-3 overflow-auto">
              <div className="text-[11px] uppercase tracking-wider text-[#8b8790] px-2 mb-2">
                Acme engineering
              </div>
              {channels.map((c) => (
                <button
                  key={c.id}
                  onClick={() => loadWorkspace(c.id)}
                  className={`w-full text-left px-2 py-1.5 rounded text-[13px] ${
                    c.id === channelId ? "bg-[#1d222b] text-[#e8e4db]" : "text-[#a8a49c] hover:text-[#e8e4db]"
                  }`}
                >
                  #{c.name}
                </button>
              ))}
            </div>

            <section className="flex-1 min-w-0 flex flex-col">
              <header className="border-b border-[#2a2e38] px-5 py-3">
                <div className="text-[15px] font-medium">#{channel?.name || "channel"}</div>
                <div className="text-[12px] text-[#8b8790]">{channel?.purpose}</div>
              </header>
              <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
                {messages.map((m) => (
                  <div key={m.ts} className="flex gap-3">
                    <div className="h-8 w-8 rounded-md bg-[#2a2e38] grid place-items-center text-[11px] uppercase text-[#d4a574]">
                      {m.user_label.slice(0, 2)}
                    </div>
                    <div className="min-w-0">
                      <div className="text-[13px]">
                        <span className="font-medium">{m.user_label}</span>{" "}
                        <span className="text-[#8b8790] text-[11px]">{m.at}</span>
                      </div>
                      <div className="text-[14px] leading-relaxed text-[#e8e4db]/90 whitespace-pre-wrap">
                        {m.text}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <form
                className="border-t border-[#2a2e38] p-4 space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  run();
                }}
              >
                <div className="flex gap-2 flex-wrap">
                  {SAMPLES.map((s) => (
                    <button
                      key={s.label}
                      type="button"
                      onClick={() => setDraft(s.text)}
                      className="text-[11px] px-2 py-1 rounded-full border border-[#2a2e38] text-[#8b8790] hover:text-[#e8e4db]"
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
                <div className="flex gap-2">
                  <select
                    value={path}
                    onChange={(e) => setPath(e.target.value as "watcher" | "search")}
                    className="bg-[#12141a] border border-[#2a2e38] rounded-md text-[12px] px-2"
                  >
                    <option value="watcher">Watcher (silent unless costly)</option>
                    <option value="search">/precedent (always answers)</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={2}
                    className="flex-1 bg-[#12141a] border border-[#2a2e38] rounded-md px-3 py-2 text-[14px] outline-none focus:border-[#d4a574]"
                    placeholder="Write a proposal…"
                  />
                  <button
                    disabled={busy || !draft.trim()}
                    className="self-stretch px-4 rounded-md bg-[#e8e4db] text-[#12141a] text-[13px] font-medium disabled:opacity-40"
                  >
                    {busy ? "Working…" : path === "search" ? "Search" : "Send"}
                  </button>
                </div>
                {error && (
                  <div className="text-[13px] text-[#d07255] bg-[#d07255]/10 rounded-md px-3 py-2">
                    {error}
                  </div>
                )}
                {result?.silenced && path === "watcher" && !error && (
                  <div className="text-[12px] text-[#8b8790]">
                    Precedent stayed silent ({result.silence_reason || "no costly match"}). About 95% of
                    messages should look like this.
                  </div>
                )}
              </form>
            </section>

            <aside className="w-[360px] max-w-[42vw] shrink-0 border-l border-[#2a2e38] bg-[#15181f] overflow-auto">
              <div className="px-4 py-3 border-b border-[#2a2e38] text-[11px] uppercase tracking-wider text-[#8b8790]">
                Private to you
              </div>
              {!card && (
                <div className="p-5 text-[13px] text-[#8b8790] leading-relaxed">
                  Nothing is posted to the channel. If Precedent finds a settled decision worth
                  interrupting you for, the card appears here — ephemeral, only for the person who
                  triggered it.
                </div>
              )}
              {card && (
                <div className="p-4">
                  <div
                    className={`rounded-lg border p-4 ${
                      card.warning === "warning"
                        ? "border-[#d07255] bg-[#d07255]/8"
                        : card.warning === "info"
                          ? "border-[#d4a574] bg-[#d4a574]/8"
                          : "border-[#2a2e38] bg-[#12141a]"
                    }`}
                  >
                    {card.warning === "warning" && (
                      <div className="text-[11px] uppercase tracking-wide text-[#d07255] mb-2">
                        Reversed — following this may recreate a known failure
                      </div>
                    )}
                    {card.warning === "info" && (
                      <div className="text-[11px] uppercase tracking-wide text-[#d4a574] mb-2">
                        Concurrent approaches
                      </div>
                    )}
                    <div className="serif text-[22px] leading-tight mb-3">{card.title}</div>
                    <Field label="What" body={card.what} />
                    <Field label="Why" body={card.why} />
                    <Field label="After" body={card.aftermath} />
                    <div className="mt-3 text-[12px] text-[#8b8790]">
                      {card.status} · {(card.confidence * 100).toFixed(0)}%
                    </div>
                    <a
                      className="mt-2 inline-block text-[13px] text-[#8faf86] underline"
                      href={card.permalink}
                    >
                      Open original thread
                    </a>
                    {card.clarifying_question && (
                      <div className="mt-3 text-[13px] text-[#e8e4db]">{card.clarifying_question}</div>
                    )}
                    <div className="mt-4 flex gap-2">
                      <button
                        className="text-[12px] px-3 py-1.5 rounded-md bg-[#e8e4db] text-[#12141a]"
                        onClick={() => setShared(true)}
                      >
                        Share to thread
                      </button>
                      <button
                        className="text-[12px] px-3 py-1.5 rounded-md border border-[#2a2e38]"
                        onClick={() => setResult(null)}
                      >
                        Not the same decision
                      </button>
                    </div>
                    {shared && (
                      <div className="mt-3 text-[12px] text-[#8faf86]">
                        You chose to share. Precedent never posts this on its own.
                      </div>
                    )}
                  </div>
                  {result && (
                    <div className="mt-4 text-[11px] text-[#8b8790] space-y-1">
                      <div>This call ${result.cost_usd.toFixed(4)}</div>
                      {result.probes?.length > 0 && (
                        <div>Probes: {result.probes.filter(Boolean).slice(0, 3).join(" · ")}</div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </aside>
          </div>
        )}

        {tab === "graph" && (
          <div className="p-6 overflow-auto">
            <h1 className="serif text-3xl mb-2">What is stored</h1>
            <p className="text-[14px] text-[#8b8790] max-w-2xl mb-6">
              Derived labels, status, confidence, permalinks, edges. No message text, user IDs, or
              embeddings. Inspector reads the live graph backend ({graph?.backend || "…"}).
            </p>
            {graph && !graph.ok && (
              <div className="text-[#d07255] mb-4">Leaks: {(graph.leaks || []).join(", ")}</div>
            )}
            {graph?.ok && <div className="text-[#8faf86] mb-4">Privacy inspector: clean</div>}
            <div className="grid gap-3">
              {(graph?.records as Record<string, unknown>[] | undefined)?.map((r) => (
                <div key={String(r.decision_id)} className="border border-[#2a2e38] rounded-lg p-4">
                  <div className="text-[11px] uppercase text-[#8b8790]">{String(r.status)}</div>
                  <div className="text-[15px] mt-1">{String(r.label)}</div>
                  <div className="text-[12px] text-[#8b8790] mt-2 break-all">{String(r.permalink)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "cost" && (
          <div className="p-6 overflow-auto max-w-3xl">
            <h1 className="serif text-3xl mb-2">First-run budget</h1>
            <p className="text-[14px] text-[#8b8790] mb-6">
              Daily pause at $10. Hard stop at $40. Flash thinking is MINIMAL/LOW so a default
              thinking bill cannot land.
            </p>
            <div className="text-[28px] serif">${Number(cost?.spent_usd || 0).toFixed(4)}</div>
            <div className="text-[13px] text-[#8b8790] mb-4">
              of ${Number(cost?.daily_budget_usd || 10)} today
            </div>
            <pre className="text-[12px] bg-[#0e1014] border border-[#2a2e38] rounded-lg p-4 overflow-auto">
              {JSON.stringify(cost, null, 2)}
            </pre>
          </div>
        )}

        {tab === "architecture" && (
          <div className="p-6 overflow-auto max-w-3xl space-y-4">
            <h1 className="serif text-3xl">How it runs</h1>
            <p className="text-[14px] text-[#8b8790] leading-relaxed">
              Google ADK agent, Gemini 3.5 Flash-Lite gate and probes, Gemini 3.5 Flash
              adjudication, gemini-embedding-001 transient rank, Firestore for derived metadata,
              Cloud Run + Pub/Sub in production. Slack content is searched live and discarded.
            </p>
            <pre className="text-[12px] leading-relaxed bg-[#0e1014] border border-[#2a2e38] rounded-lg p-4 overflow-auto">{`Slack / Replay
  → prefilter (no model)
  → gate  gemini-3.5-flash-lite   ~95% exit
  → probes gemini-3.5-flash-lite
  → Slack RTS + Firestore labels
  → embed-rank-destroy
  → adjudicate gemini-3.5-flash
  → ephemeral card`}</pre>
            <pre className="text-[12px] bg-[#0e1014] border border-[#2a2e38] rounded-lg p-4 overflow-auto">
              {JSON.stringify(arch, null, 2)}
            </pre>
          </div>
        )}
      </main>
    </div>
  );
}

function Row({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-[#8faf86]" : "bg-[#5a564e]"}`} />
      {label}
    </div>
  );
}

function Field({ label, body }: { label: string; body: string }) {
  if (!body) return null;
  return (
    <div className="mt-3">
      <div className="text-[11px] uppercase tracking-wide text-[#8b8790]">{label}</div>
      <div className="text-[14px] leading-relaxed mt-0.5">{body}</div>
    </div>
  );
}
