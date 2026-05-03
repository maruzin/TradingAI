/** Typed backend client. Uses Next.js rewrite to /api/backend/* in dev, configurable in prod. */
const BASE = "/api/backend";

export type TokenSnapshot = {
  coingecko_id: string;
  symbol: string;
  name: string;
  chain: string | null;
  contract_address: string | null;
  price_usd: number | null;
  market_cap_usd: number | null;
  fdv_usd: number | null;
  volume_24h_usd: number | null;
  pct_change_24h: number | null;
  pct_change_7d: number | null;
  pct_change_30d: number | null;
  circulating_supply: number | null;
  total_supply: number | null;
  max_supply: number | null;
  market_cap_rank: number | null;
  description: string | null;
  homepage: string | null;
  fetched_at: number;
};

export type Source = { title: string; url: string; retrieved_at?: string | null };

export type TokenBrief = {
  token_symbol: string;
  token_name: string;
  chain: string;
  horizon: "swing" | "position" | "long";
  as_of_utc: string;
  markdown: string;
  structured: Record<string, unknown> & {
    stance?: string;
    tldr?: string[];
    red_flags?: string[];
  };
  sources: Source[];
  snapshot: TokenSnapshot;
  provider: string;
  model: string;
  prompt_id: string;
};

async function getAuthHeader(): Promise<Record<string, string>> {
  // Browser-side: attach the Supabase access token if present.
  if (typeof window === "undefined") return {};
  try {
    const { supabase } = await import("./supabase");
    const sb = supabase();
    if (!sb) return {};   // Tier-2 mode: no auth header, public routes only
    const { data } = await sb.auth.getSession();
    const token = data.session?.access_token;
    if (token) return { authorization: `Bearer ${token}` };
  } catch {
    // ignore — backend will reject if auth required
  }
  return {};
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = await getAuthHeader();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      accept: "application/json",
      ...auth,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${res.statusText} ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export type BacktestTrade = {
  symbol: string;
  direction: "long" | "short";
  entry_ts: string;
  entry_price: number;
  exit_ts: string | null;
  exit_price: number | null;
  pnl_pct: number | null;
  holding_hours: number | null;
  exit_reason: string | null;
  rationale: Record<string, unknown> | null;
};

export type BacktestSymbolResult = {
  strategy_name: string;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  bars: number;
  metrics: Record<string, number | string>;
  equity_curve: number[];
  trades: BacktestTrade[];
  report_markdown: string;
};

export type BacktestRun = {
  id: string;
  strategy: string;
  timeframe: string;
  exchange: string;
  years: number;
  started_at: string;
  results: BacktestSymbolResult[];
  matrix_markdown: string;
};

export type BacktestRequest = {
  strategy: string;
  symbols: string[];
  timeframe: "1h" | "4h" | "1d";
  years: number;
  exchange: "binance" | "kraken" | "coinbase";
  initial_capital: number;
  fee_bps: number;
  slippage_bps: number;
};

export type WatchlistItem = {
  id: string;
  symbol: string;
  name: string;
  chain: string | null;
  coingecko_id: string | null;
};
export type Watchlist = {
  id: string;
  name: string;
  sort_order: number;
  created_at: string;
  items: WatchlistItem[];
};

export type AlertRule = {
  id: string;
  token_id: string | null;
  rule_type: string;
  config: Record<string, unknown>;
  severity: "info" | "warn" | "critical";
  enabled: boolean;
  created_at: string;
};
export type AlertRow = {
  id: string;
  severity: "info" | "warn" | "critical";
  title: string;
  body: string | null;
  payload: Record<string, unknown> | null;
  status: "pending" | "sent" | "failed" | "snoozed";
  fired_at: string;
  delivered_at: string | null;
  read_at: string | null;
  token_symbol: string | null;
};

export type DailyPick = {
  rank: number;
  symbol: string;
  pair: string;
  direction: "long" | "short" | "neutral";
  composite_score: number;
  confidence: number | null;
  components: Record<string, number>;
  rationale: string[];
  suggested_stop: number | null;
  suggested_target: number | null;
  risk_reward: number | null;
  last_price: number | null;
  timeframe: string;
  brief_id: string | null;
};

export type DailyPicksRun = {
  id: string;
  run_date: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  n_scanned: number;
  n_picked: number;
  notes: string | null;
  picks: DailyPick[];
};

export type DailyPicksRunSummary = {
  run_date: string;
  status: string;
  n_scanned: number;
  n_picked: number;
  started_at: string;
  finished_at: string | null;
};

export type GossipEvent = {
  id: string;
  ts: string;
  kind: "news" | "social" | "onchain" | "macro" | "influencer";
  source: string;
  title: string;
  url: string;
  summary: string | null;
  tags: string[];
  impact: number;
  token_symbols: string[];
  payload?: Record<string, unknown>;
};

export type Thesis = {
  id: string;
  token_id: string;
  token_symbol: string;
  token_name: string;
  stance: "bullish" | "bearish";
  horizon: "swing" | "position" | "long";
  core_thesis: string;
  key_assumptions: string[];
  invalidation: string[];
  review_cadence: string;
  status: "open" | "closed" | "invalidated";
  opened_at: string;
  closed_at: string | null;
  latest_evaluation?: {
    overall: string;
    per_assumption: Array<{ text: string; status: string; current_reading?: string }>;
    per_invalidation: Array<{ text: string; triggered: boolean; current_reading?: string }>;
    notes?: string;
  };
};

export const api = {
  // tokens
  snapshot: (symbol: string) => jsonFetch<TokenSnapshot>(`/tokens/${encodeURIComponent(symbol)}/snapshot`),
  brief: (symbol: string, horizon: "swing" | "position" | "long" = "position") =>
    jsonFetch<TokenBrief>(`/tokens/${encodeURIComponent(symbol)}/brief?horizon=${horizon}`),

  // backtest
  backtestStrategies: () => jsonFetch<{ strategies: string[] }>("/backtest/strategies"),
  backtestRun: (req: BacktestRequest) =>
    jsonFetch<BacktestRun>("/backtest/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
    }),
  backtestRunGet: (runId: string) => jsonFetch<BacktestRun>(`/backtest/runs/${runId}`),

  // auth/me
  me: () => jsonFetch<{ id: string; email: string; is_admin: boolean }>("/auth/me"),
  listInvites: () => jsonFetch<{ invites: Array<{
    code: string; issued_by: string | null; note: string | null;
    expires_at: string | null; created_at: string;
  }> }>("/auth/invites"),
  mintInvite: (note: string | null, expires_days = 14) =>
    jsonFetch<{ code: string; expires_at: string; note: string | null }>(
      "/auth/invites", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ note, expires_days }),
      }),

  // watchlists
  watchlists: () => jsonFetch<{ watchlists: Watchlist[] }>("/watchlists"),
  createWatchlist: (name: string) =>
    jsonFetch<Watchlist>("/watchlists", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) }),
  addWatchlistItem: (wlId: string, token: string) =>
    jsonFetch<{ watchlist_id: string; token_id: string }>(`/watchlists/${wlId}/items`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token }),
    }),
  removeWatchlistItem: (wlId: string, tokenId: string) =>
    jsonFetch<{ ok: true }>(`/watchlists/${wlId}/items/${tokenId}`, { method: "DELETE" }),

  // alerts
  alertRules: () => jsonFetch<{ rules: AlertRule[] }>("/alerts/rules"),
  createAlertRule: (body: { rule_type: string; config: Record<string, unknown>; token_id?: string; severity?: "info" | "warn" | "critical" }) =>
    jsonFetch<AlertRule>("/alerts/rules", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  deleteAlertRule: (id: string) => jsonFetch<{ ok: true }>(`/alerts/rules/${id}`, { method: "DELETE" }),
  alerts: () => jsonFetch<{ alerts: AlertRow[] }>("/alerts"),
  markAlertRead: (id: string) => jsonFetch<{ ok: true }>(`/alerts/${id}/read`, { method: "POST" }),

  // theses
  theses: () => jsonFetch<{ theses: Thesis[] }>("/theses"),
  createThesis: (body: {
    token: string; stance: "bullish" | "bearish"; horizon: "swing" | "position" | "long";
    core_thesis: string; key_assumptions: string[]; invalidation: string[];
    review_cadence?: "daily" | "weekly" | "monthly";
  }) => jsonFetch<Thesis>("/theses", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  thesis: (id: string) => jsonFetch<Thesis>(`/theses/${id}`),
  evaluateThesis: (id: string) => jsonFetch<{ evaluation_id: string; overall: string; notes?: string }>(`/theses/${id}/evaluate`, { method: "POST" }),

  // system
  mintTelegramCode: () => jsonFetch<{ code: string; expires_minutes: number; instructions: string }>("/system/telegram/link-code", { method: "POST" }),

  // track record
  trackRecord: (sinceDays = 90) =>
    jsonFetch<{ since_days: number; by_call_type: Record<string, { n_evaluated: number; n_correct: number; accuracy: number | null; avg_confidence: number }> }>(`/track-record?since_days=${sinceDays}`),

  // daily picks
  picksToday: () => jsonFetch<DailyPicksRun>("/picks/today"),
  picksFor: (date: string) => jsonFetch<DailyPicksRun>(`/picks/${date}`),
  picksRecent: (limit = 14) => jsonFetch<{ runs: DailyPicksRunSummary[] }>(`/picks/recent?limit=${limit}`),
  picksRunNow: () => jsonFetch<{ status: string; scanned: number; picked: number; run_id: string }>("/picks/run-now", { method: "POST" }),

  // gossip room
  gossip: (params?: { kinds?: string[]; min_impact?: number; limit?: number; since?: string }) => {
    const qs = new URLSearchParams();
    if (params?.kinds?.length) qs.set("kinds", params.kinds.join(","));
    if (params?.min_impact != null) qs.set("min_impact", String(params.min_impact));
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.since) qs.set("since", params.since);
    return jsonFetch<{ events: GossipEvent[]; as_of: string }>(`/gossip${qs.toString() ? `?${qs}` : ""}`);
  },

  // signals
  signals: (params?: { symbols?: string[]; timeframe?: "1h" | "4h" | "1d"; years?: number }) => {
    const qs = new URLSearchParams();
    if (params?.symbols?.length) qs.set("symbols", params.symbols.join(","));
    if (params?.timeframe) qs.set("timeframe", params.timeframe);
    if (params?.years) qs.set("years", String(params.years));
    return jsonFetch<{
      as_of: string;
      timeframe: string;
      years: number;
      rows: Array<{
        symbol: string;
        last_price?: number;
        regime?: string;
        rsi_14?: number;
        above_sma_50?: boolean;
        above_sma_200?: boolean;
        is_squeeze?: boolean;
        natr_pct?: number;
        structure_trend?: string;
        last_break?: string;
        patterns: string[];
        divergences: string[];
        candle_pattern_hits: string[];
        triggers: Array<{
          strategy: string;
          kind: "enter_long" | "enter_short";
          confidence: number;
          stop_loss?: number;
          take_profit?: number;
        }>;
        long_count: number;
        short_count: number;
        verdict: "long_bias" | "short_bias" | "mixed" | "no_setup";
        error?: string;
      }>;
    }>(`/signals${qs.toString() ? `?${qs}` : ""}`);
  },
};
