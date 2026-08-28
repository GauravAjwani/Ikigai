import { useEffect, useMemo, useState } from "react";
import Architecture from "./Architecture";
import {
  api,
  type Briefing,
  type Card,
  type Channel,
  type Message,
  type PersonCheck,
  type PipelineResult,
} from "./api";

type Tab = "replay" | "graph" | "cost" | "architecture";
type Call = "watcher" | "mention" | "slash" | "dm" | "check" | "login" | "logout";

function tabFromHash(): Tab {
  const h = window.location.hash.replace("#", "");
  if (h === "graph" || h === "cost" || h === "architecture") return h;
  return "replay";
}

const CALLS: { id: Call; label: string; hint: string }[] = [
  { id: "watcher", label: "Channel post", hint: "Unsolicited. Quiet unless a past call is reopened." },
  { id: "mention", label: "@Ikigai", hint: "Public lookup in this channel." },
  { id: "slash", label: "/ikigai", hint: "Private lookup. Only you would see this in Slack." },
  { id: "dm", label: "DM Ikigai", hint: "Private search across every channel the bot can see." },
  { id: "check", label: "/check-ikigai", hint: "That person's calls plus who supported or opposed." },
  { id: "logout", label: "/ikigai logout", hint: "Warm goodbye. Marks you away." },
  { id: "login", label: "/ikigai login", hint: "Catch-up since logout. Tap a line to open the thread." },
];

const LOOKUP_SAMPLES = [
  { label: "Nightly token rotation", text: "Let's rotate tokens every night." },
  { label: "Remember the 401s", text: "We shouldn't do a global rotation job, remember the 401s." },
  { label: "Kill switch in env", text: "Can we just put the checkout kill switch in an env var on Cloud Run?" },
  { label: "Move APM", text: "Grafana Cloud looks cheaper, should we move APM off the current vendor?" },
  { label: "Company-wide queue", text: "We should pick one company-wide queue. Everything on Postgres." },
  { label: "Chatter (silent)", text: "thanks!" },
];

const CHECK_SAMPLES = [
  { label: "@priya", text: "priya" },
  { label: "@marcus", text: "marcus" },
  { label: "@aisha", text: "aisha" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("C-PLATFORM");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("Let's rotate tokens every night.");
  const [call, setCall] = useState<Call>("slash");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [person, setPerson] = useState<PersonCheck | null>(null);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [note, setNote] = useState("");
  const [graph, setGraph] = useState<{ records?: unknown[]; leaks?: string[]; backend?: string; ok?: boolean } | null>(null);
  const [cost, setCost] = useState<Record<string, unknown> | null>(null);
  const [arch, setArch] = useState<{
    track?: string;
    models?: { gate?: string; probes?: string; adjudicate?: string; embed?: string };
    stored?: string[];
    never_stored?: string[];
    gcp?: string[];
    framework?: string;
  } | null>(null);

  const channel = useMemo(
    () => channels.find((c) => c.id === channelId),
    [channels, channelId],
  );
  const callMeta = CALLS.find((c) => c.id === call)!;
  const chips = call === "check" ? CHECK_SAMPLES : LOOKUP_SAMPLES;
  const needsText = call !== "login" && call !== "logout";

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
    const next = tab === "replay" ? "" : `#${tab}`;
    if (window.location.hash !== next) {
      window.history.replaceState(null, "", next || window.location.pathname);
    }
  }, [tab]);

  useEffect(() => {
    if (tab === "graph") api.graph().then(setGraph).catch(() => {});
    if (tab === "cost") api.cost().then(setCost).catch(() => {});
    if (tab === "architecture") api.architecture().then(setArch).catch(() => {});
  }, [tab]);

  function clearReply() {
    setResult(null);
    setPerson(null);
    setBriefing(null);
    setNote("");
  }

  async function run() {
    if (needsText && !draft.trim()) return;
    setBusy(true);
    setError("");
    clearReply();
    try {
      if (call === "logout") {
        const data = await api.logout({ channel_id: channelId, user_label: "you" });
        setNote(data.text);
        return;
      }
      if (call === "login") {
        const data = await api.login({ channel_id: channelId, user_label: "you" });
        setBriefing(data);
        return;
      }
      if (call === "check") {
        const data = await api.check({
          text: draft,
          channel_id: channelId,
          all_channels: true,
        });
        if (data.reports) setPerson(data as PersonCheck);
        else setResult(data as PipelineResult);
        return;
      }
      const data = await api.run({
        text: draft,
        channel_id: channelId,
        path: call === "watcher" ? "watcher" : "search",
        post: call === "watcher",
        all_channels: call === "dm",
      });
      setResult(data.result);
      if (call === "watcher") await loadWorkspace(channelId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const card: Card | null = result?.card ?? null;
  const gemini = Boolean(health?.gemini);
  const hasReply = Boolean(card || person || briefing || note || (result?.silenced && call === "watcher"));

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-[232px] shrink-0 border-r border-[#2a2e38] bg-[#0e1014] flex flex-col">
        <div className="px-5 pt-6 pb-4">
          <div className="serif text-[28px] leading-none tracking-tight">Ikigai</div>
          <div className="mt-2 text-[12px] text-[#8b8790] leading-snug">
            Demo workspace. Same pipeline as Slack. Fixture messages, not live Slack history.
          </div>
        </div>
        <nav className="px-2 mt-1 flex flex-col gap-0.5">
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
        <div className="px-4 mt-4 text-[11px] text-[#8b8790] space-y-2">
          <div className="uppercase tracking-wider">On Slack</div>
          <p>@Ikigai is public in the thread. /ikigai is private. /ikigai login and logout. /check-ikigai @name. DMs search every channel.</p>
          <p>Greetings and thanks stay silent. Cards: Status, Confidence, Who, Now.</p>
        </div>
        <div className="mt-auto px-4 py-4 text-[11px] text-[#8b8790] space-y-1">
          <Row ok={gemini} label="Gemini 3.5" />
          <Row ok={Boolean(health?.vertex || health?.gcp_project)} label="Vertex / GCP" />
          <Row ok={Boolean(health?.slack)} label="Slack live (separate)" />
          <div>Build · {String(health?.build || "—")}</div>
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
                  {CALLS.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => {
                        setCall(c.id);
                        clearReply();
                        if (c.id === "check") setDraft("priya");
                        if (c.id === "watcher" || c.id === "mention" || c.id === "slash" || c.id === "dm") {
                          setDraft("Let's rotate tokens every night.");
                        }
                      }}
                      className={`text-[11px] px-2 py-1 rounded-full border ${
                        call === c.id
                          ? "border-[#d4a574] text-[#e8e4db]"
                          : "border-[#2a2e38] text-[#8b8790] hover:text-[#e8e4db]"
                      }`}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
                <div className="text-[12px] text-[#8b8790]">{callMeta.hint}</div>
                {needsText && (
                  <div className="flex gap-2 flex-wrap">
                    {chips.map((s) => (
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
                )}
                <div className="flex gap-2">
                  {needsText ? (
                    <textarea
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      rows={2}
                      className="flex-1 bg-[#12141a] border border-[#2a2e38] rounded-md px-3 py-2 text-[14px] outline-none focus:border-[#d4a574]"
                      placeholder={call === "check" ? "Slack username, e.g. priya" : "Write a proposal…"}
                    />
                  ) : (
                    <div className="flex-1 text-[13px] text-[#8b8790] self-center">
                      {call === "logout"
                        ? "Marks you away in this demo, then a private goodbye."
                        : "Catch-up of fixture decisions since logout. Try logout first."}
                    </div>
                  )}
                  <button
                    disabled={busy || (needsText && !draft.trim())}
                    className="self-stretch px-4 rounded-md bg-[#e8e4db] text-[#12141a] text-[13px] font-medium disabled:opacity-40"
                  >
                    {busy ? "Working…" : actionLabel(call)}
                  </button>
                </div>
                {error && (
                  <div className="text-[13px] text-[#d07255] bg-[#d07255]/10 rounded-md px-3 py-2">
                    {error}
                  </div>
                )}
              </form>
            </section>

            <aside className="w-[360px] max-w-[42vw] shrink-0 border-l border-[#2a2e38] bg-[#15181f] overflow-auto">
              <div className="px-4 py-3 border-b border-[#2a2e38] text-[11px] uppercase tracking-wider text-[#8b8790]">
                {call === "slash" || call === "dm" || call === "check" || call === "login" || call === "logout"
                  ? "Private · only you"
                  : call === "mention"
                    ? "Public thread"
                    : "Watcher"}
              </div>
              {!hasReply && (
                <div className="p-5 text-[13px] text-[#8b8790] leading-relaxed space-y-3">
                  <p>Same agent as Slack. Pick a call above, then run it.</p>
                  <ul className="space-y-2 text-[12px]">
                    <li><span className="text-[#e8e4db]">@Ikigai / /ikigai</span> — decision card</li>
                    <li><span className="text-[#e8e4db]">/check-ikigai</span> — supported / opposed</li>
                    <li><span className="text-[#e8e4db]">login / logout</span> — catch-up and goodbye</li>
                    <li><span className="text-[#e8e4db]">Channel post</span> — silent on chatter</li>
                  </ul>
                </div>
              )}
              {result?.silenced && call === "watcher" && !error && (
                <div className="p-5 text-[13px] text-[#8b8790]">
                  Ikigai stayed quiet ({result.silence_reason || "no costly match"}). Unsolicited
                  channel messages only get a reply when a prior decision is being reopened.
                </div>
              )}
              {note && (
                <div className="p-5 text-[14px] leading-relaxed whitespace-pre-wrap">{note}</div>
              )}
              {briefing && <BriefingPane briefing={briefing} />}
              {person && <PersonPane person={person} />}
              {card && (
                <div className="p-4">
                  <DecisionCard
                    card={card}
                    onDismiss={() => {
                      if (card.decision_id) api.feedback(card.decision_id).catch(() => {});
                      clearReply();
                    }}
                  />
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
              embeddings. Inspector reads the demo graph ({graph?.backend || "…"}).
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
              Daily pause at $10. Hard stop at $40. Watcher gate is MINIMAL. Lookup is LOW.
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

        {tab === "architecture" && <Architecture health={health} arch={arch} />}
      </main>
    </div>
  );
}

function actionLabel(call: Call): string {
  if (call === "logout") return "Logout";
  if (call === "login") return "Login";
  if (call === "check") return "Check";
  if (call === "slash" || call === "mention" || call === "dm") return "Search";
  return "Send";
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

function DecisionCard({ card, onDismiss }: { card: Card; onDismiss: () => void }) {
  return (
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
      {card.summary && (
        <div className="text-[14px] leading-snug text-[#e8e4db] mb-3">{card.summary}</div>
      )}
      <Field label="Status" body={card.status} />
      {card.confidence > 0 ? (
        <Field label="Confidence" body={`${Math.round(card.confidence * 100)}%`} />
      ) : null}
      {card.who ? <Field label="Who" body={`@${card.who.replace(/^@/, "")}`} /> : null}
      <Field label="Now" body={card.aftermath || card.why} />
      {card.permalink && (
        <a className="mt-2 inline-block text-[13px] text-[#8faf86] underline" href={card.permalink}>
          Open original thread
        </a>
      )}
      {card.clarifying_question && (
        <div className="mt-3 text-[13px] text-[#e8e4db]">{card.clarifying_question}</div>
      )}
      <div className="mt-4 flex gap-2">
        <button className="text-[12px] px-3 py-1.5 rounded-md border border-[#2a2e38]" onClick={onDismiss}>
          Not the same decision
        </button>
      </div>
    </div>
  );
}

function PersonPane({ person }: { person: PersonCheck }) {
  return (
    <div className="p-4 space-y-3">
      <div className="serif text-[22px] leading-tight">{person.name}&apos;s calls</div>
      <p className="text-[14px] leading-relaxed">{person.summary}</p>
      {person.reports.map((r, i) => (
        <div key={`${r.permalink}-${i}`} className="border border-[#2a2e38] rounded-lg p-3">
          <div className="text-[14px] font-medium">{r.gist || r.label || r.what}</div>
          {r.channel_name && (
            <div className="text-[12px] text-[#8b8790] mt-1">#{r.channel_name}</div>
          )}
          {r.agreed?.length > 0 && (
            <div className="text-[12px] mt-2 text-[#8faf86]">
              Supported · {r.agreed.map((n) => `@${n.replace(/^@/, "")}`).join(", ")}
            </div>
          )}
          {r.opposed?.length > 0 && (
            <div className="text-[12px] mt-1 text-[#d07255]">
              Opposed · {r.opposed.map((n) => `@${n.replace(/^@/, "")}`).join(", ")}
            </div>
          )}
          {r.permalink && (
            <a className="mt-2 inline-block text-[12px] text-[#8faf86] underline" href={r.permalink}>
              Open thread
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

function BriefingPane({ briefing }: { briefing: Briefing }) {
  return (
    <div className="p-4 space-y-3">
      <div className="serif text-[22px] leading-tight">{briefing.greeting}</div>
      <p className="text-[14px] leading-relaxed whitespace-pre-wrap">{briefing.happened}</p>
      {briefing.items?.map((it) => (
        <a
          key={it.item_id || it.permalink}
          href={it.permalink || "#"}
          className="block border border-[#2a2e38] rounded-lg p-3 hover:border-[#d4a574]"
        >
          <div className="text-[14px]">{it.title}</div>
          <div className="text-[12px] text-[#8b8790] mt-1">
            {it.detail}
            {it.channel_name ? ` · #${it.channel_name}` : ""}
          </div>
        </a>
      ))}
    </div>
  );
}
