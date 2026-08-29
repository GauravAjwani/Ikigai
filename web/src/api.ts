export type Channel = {
  id: string;
  name: string;
  purpose: string;
  kind?: "channel" | "dm" | "group";
};
export type Message = {
  channel_id: string;
  channel_name: string;
  ts: string;
  thread_ts: string;
  user_label: string;
  text: string;
  permalink: string;
  at: string;
};
export type Card = {
  warning: "none" | "info" | "warning";
  title: string;
  status: string;
  what: string;
  why: string;
  aftermath: string;
  permalink: string;
  related_permalinks: string[];
  clarifying_question: string;
  confidence: number;
  share_text: string;
  summary: string;
  who?: string;
  decision_id?: string;
};
export type PipelineResult = {
  silenced: boolean;
  silence_reason: string;
  probes: string[];
  candidates: { permalink: string; snippet: string; score: number; source: string; graph_status?: string }[];
  verdict: {
    same_decision: boolean;
    status: string;
    confidence: number;
    what: string;
    why: string;
    aftermath: string;
    permalink: string;
  } | null;
  card: Card | null;
  cost_usd: number;
  gemini_used: boolean;
  stages: { stage: string; ok: boolean; detail: string; usd: number; ms: number }[];
  path: string;
};
export type PersonReport = {
  label: string;
  gist: string;
  what: string;
  channel_name: string;
  permalink: string;
  agreed: string[];
  opposed: string[];
};
export type PersonCheck = {
  name: string;
  scope?: string;
  summary: string;
  happened?: string;
  reports: PersonReport[];
};
export type BriefItem = {
  item_id: string;
  title: string;
  detail: string;
  permalink: string;
  channel_name: string;
};
export type Briefing = {
  greeting: string;
  happened: string;
  items: BriefItem[];
  since_logout?: boolean;
  missed?: number;
  logged_in_at?: number | null;
  logged_out_at?: number | null;
};

const j = async (url: string, init?: RequestInit) => {
  const r = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = (data && (data.detail || data.message)) || r.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
};

export const api = {
  health: () => j("/api/health"),
  workspace: (channelId?: string, userLabel?: string) => {
    const q = new URLSearchParams();
    if (channelId) q.set("channel_id", channelId);
    if (userLabel) q.set("user_label", userLabel);
    const s = q.toString();
    return j(`/api/workspace${s ? `?${s}` : ""}`);
  },
  run: (body: {
    text: string;
    channel_id: string;
    path: string;
    post?: boolean;
    all_channels?: boolean;
    user_label?: string;
  }) => j("/api/run", { method: "POST", body: JSON.stringify(body) }),
  check: (body: { text: string; channel_id: string; all_channels?: boolean }) =>
    j("/api/check", { method: "POST", body: JSON.stringify({ ...body, path: "check" }) }),
  login: (body: { channel_id: string; user_label?: string }) =>
    j("/api/login", { method: "POST", body: JSON.stringify(body) }),
  logout: (body: { channel_id: string; user_label?: string }) =>
    j("/api/logout", { method: "POST", body: JSON.stringify(body) }),
  graph: () => j("/api/graph"),
  cost: () => j("/api/cost"),
  architecture: () => j("/api/architecture"),
  reset: () => j("/api/reset", { method: "POST" }),
  feedback: (decision_id: string) =>
    j("/api/feedback", { method: "POST", body: JSON.stringify({ decision_id, note: "not_same" }) }),
};
