import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Architecture from "./Architecture";
import Tour, { type TourStep } from "./Tour";
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
type Clock = { away: boolean; awayAt: number | null; inAt: number | null };

const ACCOUNTS = ["you", "priya", "marcus", "aisha"] as const;

function tabFromHash(): Tab {
  const h = window.location.hash.replace("#", "");
  if (h === "graph" || h === "cost" || h === "architecture") return h;
  return "replay";
}

const LOOKUP_SAMPLES = [
  { label: "Nightly rotation", text: "Let's rotate tokens every night." },
  { label: "Remember the 401s", text: "We shouldn't do a global rotation job, remember the 401s." },
  { label: "Kill switch in env", text: "Can we just put the checkout kill switch in an env var on Cloud Run?" },
  { label: "Move APM", text: "Grafana Cloud looks cheaper, should we move APM off the current vendor?" },
  { label: "Company-wide queue", text: "We should pick one company-wide queue. Everything on Postgres." },
  { label: "Chatter", text: "thanks!" },
];

const CHECK_SAMPLES = [
  { label: "@priya", text: "priya" },
  { label: "@marcus", text: "marcus" },
  { label: "@aisha", text: "aisha" },
];

const TOUR: TourStep[] = [
  {
    id: "brand",
    title: "Fixture Replay",
    body: "This is a sandbox of Slack threads. Nothing here is live Slack. Use it to try every Ikigai call before you use the bot at work.",
  },
  {
    id: "accounts",
    title: "Who you are",
    body: "Switch @you, @priya, @marcus, or @aisha. Login and logout belong to that account only — so you can log Priya out, speak as Marcus, then log Priya back in.",
  },
  {
    id: "chats",
    title: "Where you are",
    body: "Channels, private groups, and DMs. The ikigai DM is message-only. Login, logout, @Ikigai, and /ikigai live on channels and 1:1s.",
  },
  {
    id: "thread",
    title: "The thread",
    body: "This is the fixture history for the chat you picked. New messages you send as Message or @Ikigai appear here.",
  },
  {
    id: "commands",
    title: "The Slack calls",
    body: "Message posts quietly. @Ikigai looks up in this channel, in public. /ikigai is the same lookup, private. /check-ikigai is a person. Logout marks this account away. Login is only what they missed since then.",
  },
  {
    id: "samples",
    title: "Chips are examples",
    body: "Those chips are sample questions — not a menu. For Message, @Ikigai, /ikigai, /check-ikigai, and the Ikigai DM, type anything you want. The same is true for every call, not only /ikigai.",
  },
  {
    id: "reply",
    title: "Private replies",
    body: "Cards, check reports, and login catch-up land here. @Ikigai would post in the thread instead. Watcher messages stay quiet unless a past call is reopened.",
  },
  {
    id: "nav",
    title: "The rest of the house",
    body: "Graph is what is stored (labels, not message text). Cost is today's meter. Architecture is how Gemini is wired. Press Tour anytime to hear this again.",
  },
];

function sampleHint(call: Call, dmBot: boolean) {
  if (call === "check") return "Example usernames. Type any Slack username you want — not only these.";
  if (dmBot) return "Example questions. Ask Ikigai anything; these chips are not a limit.";
  if (call === "mention") return "Example questions. @Ikigai can be asked anything in this channel.";
  if (call === "slash") return "Example questions. /ikigai can look up anything you type — not only these.";
  return "Example messages. Send anything as this account; these chips are not a limit.";
}

function kindOf(ch?: Channel) {
  return ch?.kind || "channel";
}

function isIkigaiDm(ch?: Channel) {
  return kindOf(ch) === "dm" && ch?.id === "D-IKIGAI";
}

function callsFor(ch?: Channel): { id: Call; label: string; hint: string }[] {
  if (isIkigaiDm(ch)) {
    return [{ id: "dm", label: "Message", hint: "Private DM with Ikigai. Searches every chat it can see." }];
  }
  if (kindOf(ch) === "dm") {
    return [
      { id: "watcher", label: "Message", hint: "Send as the selected account in this 1:1." },
      { id: "slash", label: "/ikigai", hint: "Private lookup. Only you would see this in Slack." },
      { id: "check", label: "/check-ikigai", hint: "That person's calls in this chat." },
      { id: "logout", label: "/ikigai logout", hint: "Private goodbye for this account." },
      { id: "login", label: "/ikigai login", hint: "What this account missed here since logout." },
    ];
  }
  return [
    { id: "watcher", label: "Message", hint: "Post in the channel as the selected account. Quiet unless a past call is reopened." },
    { id: "mention", label: "@Ikigai", hint: "Public lookup in this channel." },
    { id: "slash", label: "/ikigai", hint: "Private lookup. Only you would see this in Slack." },
    { id: "check", label: "/check-ikigai", hint: "That person's calls in this channel, plus who supported or opposed." },
    { id: "logout", label: "/ikigai logout", hint: "Private goodbye. Marks this account away." },
    { id: "login", label: "/ikigai login", hint: "Catch-up since this account logged out — not the whole history." },
  ];
}

function clockLabel(ts?: number | null) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function prettyTime(at: string) {
  if (!at || at === "now") return "Just now";
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return at;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("C-PLATFORM");
  const [messages, setMessages] = useState<Message[]>([]);
  const [account, setAccount] = useState<string>("you");
  const [clocks, setClocks] = useState<Record<string, Clock>>({});
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
  const wsGen = useRef(0);
  const tourStarted = useRef(false);
  const [tour, setTour] = useState(false);
  const [tourI, setTourI] = useState(0);

  const channel = useMemo(
    () => channels.find((c) => c.id === channelId),
    [channels, channelId],
  );
  const publics = channels.filter((c) => kindOf(c) === "channel");
  const groups = channels.filter((c) => kindOf(c) === "group");
  const dms = channels.filter((c) => kindOf(c) === "dm");
  const available = callsFor(channel);
  const callMeta = available.find((c) => c.id === call) || available[0];
  const chips = call === "check" ? CHECK_SAMPLES : LOOKUP_SAMPLES;
  const needsText = call !== "login" && call !== "logout";
  const dmBot = isIkigaiDm(channel);
  const me = clocks[account] || { away: false, awayAt: null, inAt: null };
  const simpleComposer = available.length === 1;
  const spent = Number(cost?.spent_usd || 0);
  const budget = Number(cost?.daily_budget_usd || 10);
  const used = budget > 0 ? Math.min(100, (spent / budget) * 100) : 0;

  function stampClock(name: string, patch: Partial<Clock>) {
    setClocks((prev) => ({
      ...prev,
      [name]: { away: false, awayAt: null, inAt: null, ...prev[name], ...patch },
    }));
  }

  function applyWorkspace(
    w: { channels: Channel[]; channel_id: string; messages: Message[]; away?: boolean; away_at?: number | null },
    who: string,
  ) {
    setChannels(w.channels);
    setChannelId(w.channel_id);
    setMessages(w.messages);
    const away = Boolean(w.away);
    setClocks((prev) => {
      const cur = prev[who] || { away: false, awayAt: null, inAt: null };
      return {
        ...prev,
        [who]: {
          away,
          awayAt: away ? Number(w.away_at) || cur.awayAt : null,
          inAt: away ? null : cur.inAt,
        },
      };
    });
  }

  async function loadWorkspace(id?: string, who?: string) {
    const n = ++wsGen.current;
    const label = who || account;
    const w = await api.workspace(id || channelId, label);
    if (n !== wsGen.current) return;
    applyWorkspace(w, label);
  }

  async function openChat(c: Channel) {
    clearReply();
    try {
      await loadWorkspace(c.id, account);
      if (c.id === "D-IKIGAI") setCall("dm");
      else if (kindOf(c) === "dm") setCall("watcher");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    loadWorkspace("C-PLATFORM", "you").catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    if (tourStarted.current || !channels.length) return;
    tourStarted.current = true;
    setTab("replay");
    setTourI(0);
    setTour(true);
  }, [channels.length]);

  useEffect(() => {
    if (tour) setTab("replay");
  }, [tour]);

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

  useEffect(() => {
    const ids = callsFor(channel).map((c) => c.id);
    if (!ids.includes(call)) setCall(ids[0]);
  }, [channelId, channel, call]);

  function clearReply() {
    setResult(null);
    setPerson(null);
    setBriefing(null);
    setNote("");
  }

  async function switchAccount(next: string) {
    setAccount(next);
    clearReply();
    try {
      await loadWorkspace(channelId, next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function run() {
    if (needsText && !draft.trim()) return;
    setBusy(true);
    setError("");
    clearReply();
    try {
      if (call === "logout") {
        const data = await api.logout({ channel_id: channelId, user_label: account });
        const at = Number(data.away_at || data.logged_out_at) || Date.now() / 1000;
        stampClock(account, { away: true, awayAt: at, inAt: null });
        setNote(data.text);
        await loadWorkspace(channelId, account);
        return;
      }
      if (call === "login") {
        const data = await api.login({ channel_id: channelId, user_label: account });
        const inAt = Number(data.logged_in_at) || Date.now() / 1000;
        stampClock(account, {
          away: false,
          awayAt: data.logged_out_at ? Number(data.logged_out_at) : null,
          inAt,
        });
        setBriefing(data);
        await loadWorkspace(channelId, account);
        stampClock(account, {
          away: false,
          inAt,
          awayAt: data.logged_out_at ? Number(data.logged_out_at) : null,
        });
        return;
      }
      if (call === "check") {
        const data = await api.check({
          text: draft,
          channel_id: channelId,
          all_channels: dmBot,
        });
        if (data.reports) setPerson(data as PersonCheck);
        else setResult(data as PipelineResult);
        return;
      }
      const posts = call === "watcher" || call === "mention" || call === "dm";
      const data = await api.run({
        text: draft,
        channel_id: channelId,
        path: call === "watcher" ? "watcher" : "search",
        post: posts,
        all_channels: call === "dm" || dmBot,
        user_label: account,
      });
      setResult(data.result);
      if (posts) await loadWorkspace(channelId, account);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const card: Card | null = result?.card ?? null;
  const gemini = Boolean(health?.gemini);
  const hasReply = Boolean(card || person || briefing || note || (result?.silenced && call === "watcher"));
  const title = kindOf(channel) === "channel" ? `#${channel?.name || "…"}` : channel?.name || "…";

  function startTour() {
    setTab("replay");
    setTourI(0);
    setTour(true);
  }

  return (
    <div className="stage">
      <div className="shell">
        <header className="shell-head">
          <div data-tour="brand" className="min-w-[148px]">
            <div className="kicker">Ikigai</div>
            <div className="display text-[26px] leading-none mt-0.5">Memory</div>
          </div>
          <nav data-tour="nav" className="flex gap-1 ml-2">
            {(
              [
                ["replay", "Workspace"],
                ["graph", "Graph"],
                ["cost", "Cost"],
                ["architecture", "Architecture"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`px-3.5 py-1.5 rounded-full text-[13px] ${
                  tab === id ? "glass-active" : "text-[var(--muted)] hover:bg-white/10"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2.5 text-[11px] text-[var(--muted)]">
            <Row ok={gemini} label="Gemini 3.5" />
            <span className="opacity-40">·</span>
            <span>Build {String(health?.build || "—")}</span>
            <button type="button" className="ml-1 px-3 py-1.5 rounded-full glass-c text-[12px] text-[var(--ink)]" onClick={startTour}>
              Tour
            </button>
            {tab === "replay" && <PresencePill account={account} clock={me} />}
          </div>
        </header>

        {tab === "replay" && (
          <div className="shell-body">
            <div className="rail">
              <div data-tour="accounts">
                <div className="kicker px-3 mb-2">Account</div>
                <div className="space-y-1 mb-6">
                  {ACCOUNTS.map((name) => {
                    const c = clocks[name];
                    const on = account === name;
                    return (
                      <button
                        key={name}
                        onClick={() => switchAccount(name)}
                        className={`w-full text-left rounded-[16px] px-3 py-2 ${
                          on ? "glass-active" : "text-[var(--ink)] hover:bg-white/10"
                        }`}
                      >
                        <div className="text-[13px] font-medium">@{name}</div>
                        <div className={`text-[10.5px] mt-0.5 ${on ? "opacity-80" : "text-[var(--muted)]"}`}>
                          {c?.away
                            ? `Logged out${c.awayAt ? ` · ${clockLabel(c.awayAt)}` : ""}`
                            : c?.inAt
                              ? `Logged in · ${clockLabel(c.inAt)}`
                              : on
                                ? "Signed in"
                                : "Present"}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
              <div data-tour="chats">
                <Section label="Channels">
                  {publics.map((c) => (
                    <ChatBtn
                      key={c.id}
                      label={`#${c.name}`}
                      active={c.id === channelId}
                      onClick={() => openChat(c)}
                    />
                  ))}
                </Section>
                <Section label="Private groups">
                  {groups.map((c) => (
                    <ChatBtn
                      key={c.id}
                      label={c.name}
                      active={c.id === channelId}
                      onClick={() => openChat(c)}
                    />
                  ))}
                </Section>
                <Section label="Direct messages">
                  {dms.map((c) => (
                    <ChatBtn
                      key={c.id}
                      label={c.name}
                      active={c.id === channelId}
                      onClick={() => openChat(c)}
                    />
                  ))}
                </Section>
              </div>
            </div>

            <section className="thread">
              <header className="px-7 py-5 flex items-end justify-between gap-4" data-tour="thread">
                <div>
                  <div className="display text-[28px] leading-none">{title}</div>
                  <div className="text-[12.5px] text-[var(--muted)] mt-2">{channel?.purpose}</div>
                </div>
              </header>
              <div className="flex-1 overflow-auto px-7 py-1 space-y-5">
                {messages.map((m) => (
                  <div key={m.ts} className="flex gap-3.5">
                    <div className="h-9 w-9 shrink-0 rounded-2xl glass-c grid place-items-center text-[10px] uppercase tracking-wide text-[var(--accent)]">
                      {m.user_label.slice(0, 2)}
                    </div>
                    <div className="min-w-0 pt-0.5">
                      <div className="flex items-baseline gap-2">
                        <span className="text-[13.5px] font-medium">@{m.user_label}</span>
                        <span className="text-[11px] text-[var(--muted)] tabular-nums">{prettyTime(m.at)}</span>
                      </div>
                      <div className="text-[14.5px] font-light leading-[1.6] text-[var(--ink)]/90 whitespace-pre-wrap mt-1 max-w-[44rem]">
                        {m.text}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <form
                className="px-5 pb-5 pt-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  run();
                }}
              >
                <div className="space-y-3" data-tour="commands">
                  {!simpleComposer && (
                    <div className="flex gap-1.5 flex-wrap" data-tour="commands">
                      {available.map((c) => (
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
                          className={`text-[11.5px] px-3 py-1.5 rounded-full ${
                            call === c.id ? "glass-active" : "glass-c text-[var(--muted)]"
                          }`}
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="text-[12px] text-[var(--muted)] px-1">{callMeta.hint}</div>
                  {needsText && (
                    <div data-tour="samples">
                      <div className="text-[11px] text-[var(--accent)] px-1 mb-1.5">{sampleHint(call, dmBot)}</div>
                      <div className="flex gap-1.5 flex-wrap">
                        {(simpleComposer ? LOOKUP_SAMPLES.slice(0, 4) : chips).map((s) => (
                          <button
                            key={s.label}
                            type="button"
                            onClick={() => setDraft(s.text)}
                            className="text-[11px] px-2.5 py-1 rounded-full glass-c text-[var(--muted)] hover:text-[var(--ink)]"
                          >
                            {s.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex gap-2.5">
                    {needsText ? (
                      <textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        rows={2}
                        className="flex-1 glass-c rounded-[20px] px-3.5 py-2.5 text-[14px] outline-none"
                        placeholder={
                          dmBot
                            ? "Anything you want to ask Ikigai as @" + account
                            : call === "check"
                              ? "Any Slack username"
                              : "Anything you want as @" + account
                        }
                      />
                    ) : (
                      <div className="flex-1 text-[13px] text-[var(--muted)] self-center px-1.5 leading-relaxed">
                        {call === "logout"
                          ? me.away && me.awayAt
                            ? `@${account} is already logged out · ${clockLabel(me.awayAt)}`
                            : `Marks @${account} logged out. Switch accounts, post, then login as @${account}.`
                          : me.inAt
                            ? `@${account} last logged in · ${clockLabel(me.inAt)}`
                            : `Only messages after @${account} logged out.`}
                      </div>
                    )}
                    <button
                      disabled={busy || (needsText && !draft.trim())}
                      className="self-stretch min-w-[92px] px-5 rounded-[20px] glass-active text-[13px] font-medium disabled:opacity-40"
                    >
                      {busy ? "Working…" : actionLabel(call)}
                    </button>
                  </div>
                </div>
                {error && (
                  <div className="mt-3 text-[13px] text-[var(--rose)] glass-c rounded-2xl px-3.5 py-2">{error}</div>
                )}
              </form>
            </section>

            <aside className="reply" data-tour="reply">
              <div className="kicker mb-3">
                {call === "mention" ? "Public thread" : dmBot ? "Ikigai · private" : "Private · only you"}
              </div>
              {!hasReply && (
                <div className="text-[13px] text-[var(--muted)] leading-relaxed space-y-4">
                  <p>
                    Logout and login live on channels and 1:1s. The <span className="text-[var(--ink)]">ikigai</span> DM
                    is message-only.
                  </p>
                  <p>
                    1. As @priya, /ikigai logout.
                    <br />
                    2. Switch to @marcus and send a message.
                    <br />
                    3. Switch back to @priya and /ikigai login.
                  </p>
                </div>
              )}
              {result?.silenced && call === "watcher" && !error && (
                <div className="text-[13px] text-[var(--muted)]">
                  Ikigai stayed quiet ({result.silence_reason || "no costly match"}).
                </div>
              )}
              {note && (
                <div className="pb-2">
                  {me.away && me.awayAt ? (
                    <div className="text-[12px] text-[var(--muted)] mb-2">Logged out · {clockLabel(me.awayAt)}</div>
                  ) : null}
                  <div className="text-[14.5px] font-light leading-relaxed whitespace-pre-wrap">{note}</div>
                </div>
              )}
              {briefing && <BriefingPane briefing={briefing} inAt={me.inAt} />}
              {person && <PersonPane person={person} />}
              {card && (
                <div>
                  <DecisionCard
                    card={card}
                    onDismiss={() => {
                      if (card.decision_id) api.feedback(card.decision_id).catch(() => {});
                      clearReply();
                    }}
                  />
                  {result && <div className="mt-3 text-[11px] text-[var(--muted)]">This call ${result.cost_usd.toFixed(4)}</div>}
                </div>
              )}
            </aside>
          </div>
        )}

        {tab === "graph" && (
          <div className="page">
            <p className="kicker">Privacy</p>
            <h1 className="display text-[40px] mt-2">What is stored</h1>
            <p className="text-[14.5px] font-light text-[var(--muted)] max-w-2xl mt-3 mb-8 leading-relaxed">
              Labels, status, confidence, permalinks, edges. No message text.
            </p>
            {graph?.ok && <div className="text-[var(--sage)] mb-2 text-[13px]">Inspector clean</div>}
            <div className="max-w-3xl">
              {(graph?.records as Record<string, unknown>[] | undefined)?.map((r) => (
                <div key={String(r.decision_id)} className="row">
                  <div className="kicker">{String(r.status)}</div>
                  <div className="text-[15px] mt-1">{String(r.label)}</div>
                  <div className="text-[12px] text-[var(--muted)] mt-1.5 break-all">{String(r.permalink)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "cost" && (
          <div className="page">
            <p className="kicker">Meter</p>
            <h1 className="display text-[40px] mt-2">Budget</h1>
            <div className="display text-[64px] mt-10 tracking-tight leading-none tabular-nums text-[var(--accent)]">
              ${spent.toFixed(4)}
            </div>
            <div className="text-[13px] text-[var(--muted)] mt-3 mb-6">
              of ${budget} today · pause $10 · hard stop $40
            </div>
            <div className="track max-w-md mb-10">
              <span style={{ width: `${used}%` }} />
            </div>
            <pre className="text-[12px] leading-relaxed max-w-2xl text-[var(--muted)]">{JSON.stringify(cost, null, 2)}</pre>
          </div>
        )}

        {tab === "architecture" && (
          <div className="page !p-0">
            <Architecture health={health} arch={arch} />
          </div>
        )}
      </div>

      {tour && (
        <Tour steps={TOUR} index={tourI} onIndex={setTourI} onDone={() => setTour(false)} />
      )}
    </div>
  );
}

function PresencePill({ account, clock }: { account: string; clock: Clock }) {
  const body = clock.away
    ? `@${account} logged out${clock.awayAt ? ` · ${clockLabel(clock.awayAt)}` : ""}`
    : clock.inAt
      ? `@${account} logged in · ${clockLabel(clock.inAt)}`
      : `@${account} signed in`;
  return <div className="shrink-0 glass-c rounded-full px-3.5 py-1.5 text-[11.5px] text-[var(--ink)]">{body}</div>;
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-5">
      <div className="kicker px-3 mb-1.5">{label}</div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function ChatBtn({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-1.5 rounded-[14px] text-[13px] ${
        active ? "glass-c text-[var(--ink)]" : "text-[var(--muted)] hover:bg-white/15"
      }`}
    >
      {label}
    </button>
  );
}

function actionLabel(call: Call): string {
  if (call === "logout") return "Logout";
  if (call === "login") return "Login";
  if (call === "check") return "Check";
  if (call === "slash" || call === "mention") return "Search";
  return "Send";
}

function Row({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-[var(--accent)]" : "bg-white/20"}`} />
      {label}
    </div>
  );
}

function Field({ label, body }: { label: string; body: string }) {
  if (!body) return null;
  return (
    <div className="mt-3">
      <div className="kicker">{label}</div>
      <div className="text-[14px] font-light leading-relaxed mt-1">{body}</div>
    </div>
  );
}

function DecisionCard({ card, onDismiss }: { card: Card; onDismiss: () => void }) {
  return (
    <div className="glass-c rounded-[24px] p-5">
      {card.warning === "warning" && (
        <div className="text-[10px] uppercase tracking-wide text-[var(--rose)] mb-2">Later reversed</div>
      )}
      {card.warning === "info" && (
        <div className="text-[10px] uppercase tracking-wide text-[var(--lavender)] mb-2">Two live approaches</div>
      )}
      <div className="display text-[24px] leading-tight">{card.title}</div>
      {card.summary && <div className="text-[14px] font-light leading-snug mt-2">{card.summary}</div>}
      <Field label="Status" body={card.status} />
      {card.confidence > 0 ? (
        <Field label="Confidence" body={`${Math.round(card.confidence * 100)}%`} />
      ) : null}
      {card.who ? <Field label="Who" body={`@${card.who.replace(/^@/, "")}`} /> : null}
      {card.aftermath || card.why ? <Field label="Now" body={card.aftermath || card.why} /> : null}
      {card.permalink && (
        <a className="mt-3 inline-block text-[13px] text-[var(--lavender)]" href={card.permalink}>
          Open thread
        </a>
      )}
      <button className="mt-4 text-[12px] px-3 py-1.5 rounded-full glass-c" onClick={onDismiss}>
        Not the same decision
      </button>
    </div>
  );
}

function PersonPane({ person }: { person: PersonCheck }) {
  return (
    <div className="space-y-3">
      <div className="display text-[24px] leading-tight">{person.name}&apos;s calls</div>
      <p className="text-[14px] font-light leading-relaxed">{person.summary}</p>
      {person.reports.map((r, i) => (
        <div key={`${r.permalink}-${i}`} className="glass-c rounded-3xl p-3.5">
          <div className="text-[14px] font-medium">{r.gist || r.label || r.what}</div>
          {r.channel_name && <div className="text-[12px] text-[var(--muted)] mt-1">#{r.channel_name}</div>}
          {r.agreed?.length > 0 && (
            <div className="text-[12px] mt-2 text-[var(--sage)]">
              Supported · {r.agreed.map((n) => `@${n.replace(/^@/, "")}`).join(", ")}
            </div>
          )}
          {r.opposed?.length > 0 && (
            <div className="text-[12px] mt-1 text-[var(--rose)]">
              Opposed · {r.opposed.map((n) => `@${n.replace(/^@/, "")}`).join(", ")}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function BriefingPane({ briefing, inAt }: { briefing: Briefing; inAt: number | null }) {
  const whenIn = briefing.logged_in_at ? clockLabel(briefing.logged_in_at) : inAt ? clockLabel(inAt) : "";
  const whenOut = briefing.logged_out_at ? clockLabel(briefing.logged_out_at) : "";
  return (
    <div className="space-y-3">
      <div className="display text-[24px] leading-tight">{briefing.greeting}</div>
      <p className="text-[12.5px] text-[var(--muted)] leading-relaxed">
        {whenIn ? `Logged in · ${whenIn}` : "Logged in"}
        {whenOut ? ` · was away from ${whenOut}` : ""}
        {briefing.since_logout && briefing.missed != null ? ` · ${briefing.missed} messages` : ""}
        {!briefing.since_logout ? " · you were not marked away" : ""}
      </p>
      <p className="text-[14.5px] font-light leading-relaxed whitespace-pre-wrap">{briefing.happened}</p>
      {briefing.items?.map((it) => (
        <a
          key={it.item_id || it.permalink}
          href={it.permalink || "#"}
          className="block glass-c rounded-3xl p-3.5 hover:bg-white/30"
        >
          <div className="text-[14px]">{it.title}</div>
          <div className="text-[12px] text-[var(--muted)] mt-1">
            {it.detail}
            {it.channel_name ? ` · #${it.channel_name}` : ""}
          </div>
        </a>
      ))}
    </div>
  );
}
