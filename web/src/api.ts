export type Channel = { id: string; name: string; purpose: string };
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
  workspace: (channelId?: string) =>
    j(`/api/workspace${channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ""}`),
  run: (body: { text: string; channel_id: string; path: string; post?: boolean }) =>
    j("/api/run", { method: "POST", body: JSON.stringify(body) }),
  graph: () => j("/api/graph"),
  cost: () => j("/api/cost"),
  architecture: () => j("/api/architecture"),
  reset: () => j("/api/reset", { method: "POST" }),
  feedback: (decision_id: string) =>
    j("/api/feedback", { method: "POST", body: JSON.stringify({ decision_id, note: "not_same" }) }),
};
