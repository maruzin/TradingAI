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
  kind: "news" | "social" | "onchain" | "macro" | "influencer" | "whale" | "event";
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

export type WalletRow = {
  id: string;
  user_id: string | null;
  chain: string;
  address: string;
  label: string;
  category: string | null;
  weight: number;
  enabled: boolean;
  notes: string | null;
  created_at: string;
  last_polled_at: string | null;
};

export type WalletEvent = {
  id: string;
  wallet_id: string;
  chain: string;
  address: string;
  tx_hash: string;
  block_number: number | null;
  ts: string;
  direction: "in" | "out" | "contract";
  token_symbol: string | null;
  amount: number | null;
  amount_usd: number | null;
  counterparty: string | null;
  counterparty_label: string | null;
  wallet_label: string;
  wallet_category: string | null;
  wallet_weight: number;
};

export type RegimeSnapshot = {
  btc_phase: string | null;
  btc_phase_confidence: number | null;
  btc_dominance_state: string | null;
  btc_dominance_pct: number | null;
  eth_btc_state: string | null;
  eth_btc_ratio: number | null;
  dxy_state: string | null;
  dxy_value: number | null;
  liquidity_state: string | null;
  funding_state: string | null;
  funding_btc_pct: number | null;
  fear_greed: number | null;
  fear_greed_label: string | null;
  summary: string;
};

export type AdminHealth = {
  version: string;
  environment: string;
  llm_provider: string;
  process_uptime_seconds: number;
  sentry: boolean;
  breakers: Record<string, {
    state: "open" | "half_open" | "closed";
    consecutive_failures: number;
    open_until: number | null;
    failure_threshold: number;
    cool_down_seconds: number;
  }>;
  rate_limit_own: Record<string, { count: number; window_started: number }>;
  cron_last_runs: Record<string, string | null>;
  cron_last_errors: Record<string, string>;
};

export type CorrelationMatrix = {
  symbols: string[];
  matrix: number[][];
  window_days: number;
  notes?: string;
};

export type PortfolioRisk = {
  total_value_usd: number;
  concentration_pct: Record<string, number>;
  top_position_pct: number;
  btc_beta: number | null;
  avg_correlation_to_btc: number | null;
  largest_drawdown_30d_pct: number | null;
  notes: string[];
};

export type TokenForecast = {
  symbol: string;
  horizon: "swing" | "position" | "long";
  p_up: number;
  p_down: number;
  direction: "long" | "short" | "neutral";
  confidence: number;
  target_pct: number | null;
  invalidation_pct: number | null;
  model_version: string;
  as_of_utc: string;
  features_used: number;
  notes: string[];
};

export type CVDPoint = {
  ts: string;
  cvd: number;
  buy_qty: number;
  sell_qty: number;
  last_price: number;
};

export type CVDSnapshot = {
  symbol: string;
  bucket_seconds: number;
  points: CVDPoint[];
  total_buy: number;
  total_sell: number;
  delta: number;
  ratio_pct: number;
  notes: string[];
  source: string;
};

export type EVRow = {
  setup: string;
  direction: "long" | "short";
  sample_size: number;
  hit_rate: number;
  median_r: number;
  median_bars_to_target: number | null;
  notes: string;
};

export type EVTable = {
  pair: string;
  timeframe: string;
  years: number;
  rows: EVRow[];
  computed_at: string;
};

export type DetailedTrackEntry = {
  n_evaluated: number;
  n_correct: number;
  accuracy: number | null;
  avg_confidence: number | null;
  brier: number | null;
  log_loss: number | null;
  calibration_bins: { bucket: string; n: number; accuracy: number | null }[];
};

export type BriefDiff = {
  latest: TokenBrief & { id?: string };
  previous: (TokenBrief & { id?: string }) | null;
  changes: { field: string; from: unknown; to: unknown }[];
};

export type TokenProjection = {
  token_symbol: string;
  as_of_utc: string;
  markdown: string;
  structured: Record<string, unknown> & {
    stance?: string;
    confidence?: number;
    scenarios?: Array<{
      label: string;
      trigger: string;
      target: number | null;
      invalidation: string;
    }>;
    watch_24h?: string;
    quality_flags?: string[];
  };
  provider: string;
  model: string;
  prompt_id: string;
};

export const api = {
  // tokens
  snapshot: (symbol: string) => jsonFetch<TokenSnapshot>(`/tokens/${encodeURIComponent(symbol)}/snapshot`),
  markets: (page = 1, sort: "market_cap_desc" | "volume_desc" | "gain_desc" | "loss_desc" = "market_cap_desc") =>
    jsonFetch<{
      page: number;
      coins: Array<{
        id: string; symbol: string; name: string; image: string;
        market_cap_rank: number | null;
        price_usd: number | null;
        market_cap_usd: number | null;
        fdv_usd: number | null;
        volume_24h_usd: number | null;
        pct_24h: number | null;
        pct_7d: number | null;
        pct_30d: number | null;
      }>;
    }>(`/markets?page=${page}&sort=${sort}`),
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

  // wallets
  wallets: (params?: { q?: string; chain?: string; include_global?: boolean; enabled_only?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.q) qs.set("q", params.q);
    if (params?.chain) qs.set("chain", params.chain);
    if (params?.include_global != null) qs.set("include_global", String(params.include_global));
    if (params?.enabled_only) qs.set("enabled_only", "true");
    return jsonFetch<{ wallets: WalletRow[] }>(`/wallets${qs.toString() ? `?${qs}` : ""}`);
  },
  walletAdd: (body: {
    chain: string; address: string; label: string;
    category?: string; weight?: number; notes?: string;
  }) => jsonFetch<{ id: string }>("/wallets", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }),
  walletDelete: (id: string) => jsonFetch<{ ok: boolean }>(`/wallets/${id}`, { method: "DELETE" }),
  walletEvents: (params?: {
    wallet_id?: string; min_usd?: number;
    direction?: "in" | "out" | "contract"; since_hours?: number; limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.wallet_id) qs.set("wallet_id", params.wallet_id);
    if (params?.min_usd != null) qs.set("min_usd", String(params.min_usd));
    if (params?.direction) qs.set("direction", params.direction);
    if (params?.since_hours) qs.set("since_hours", String(params.since_hours));
    if (params?.limit) qs.set("limit", String(params.limit));
    return jsonFetch<{ events: WalletEvent[] }>(`/wallets/events${qs.toString() ? `?${qs}` : ""}`);
  },

  // regime + projection
  regime: () => jsonFetch<RegimeSnapshot>("/regime/snapshot"),
  projection: (symbol: string, timeframe: "1h" | "4h" | "1d" = "1d") =>
    jsonFetch<TokenProjection>(`/tokens/${encodeURIComponent(symbol)}/projection?timeframe=${timeframe}`),

  // admin
  adminHealth: () => jsonFetch<AdminHealth>("/admin/health/snapshot"),

  // correlation + portfolio + brief diff
  correlation: (symbols: string[], days = 30) =>
    jsonFetch<CorrelationMatrix>(`/correlation?symbols=${symbols.join(",")}&days=${days}`),
  portfolioAnalyze: (holdings: { symbol: string; quantity: number; cost_basis_usd?: number }[]) =>
    jsonFetch<PortfolioRisk>("/portfolio/analyze", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ holdings }),
    }),
  briefDiff: (symbol: string, horizon: "swing" | "position" | "long" = "position") =>
    jsonFetch<BriefDiff>(`/tokens/${encodeURIComponent(symbol)}/brief/diff?horizon=${horizon}`),

  // ML predictor + CVD + EV table + detailed track record
  forecast: (symbol: string, horizon: "swing" | "position" | "long" = "position") =>
    jsonFetch<TokenForecast>(`/tokens/${encodeURIComponent(symbol)}/forecast?horizon=${horizon}`),
  cvd: (symbol: string, opts?: { bucket_seconds?: number; lookback_minutes?: number }) => {
    const qs = new URLSearchParams();
    if (opts?.bucket_seconds) qs.set("bucket_seconds", String(opts.bucket_seconds));
    if (opts?.lookback_minutes) qs.set("lookback_minutes", String(opts.lookback_minutes));
    return jsonFetch<CVDSnapshot>(`/tokens/${encodeURIComponent(symbol)}/cvd${qs.toString() ? `?${qs}` : ""}`);
  },
  evTable: (pair = "BTC/USDT", years = 4) =>
    jsonFetch<EVTable>(`/ev?pair=${encodeURIComponent(pair)}&years=${years}`),
  trackRecordDetailed: (since_days = 90) =>
    jsonFetch<{ since_days: number; by_call_type: Record<string, DetailedTrackEntry> }>(
      `/track-record/detailed?since_days=${since_days}`,
    ),

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
        buy_pct?: number;
        sell_pct?: number;
        suggested_holding_days_min?: number;
        suggested_holding_days_max?: number;
        suggested_entry?: number;
        suggested_stop?: number;
        suggested_target?: number;
        risk_reward?: number;
        atr_pct?: number;
        error?: string;
      }>;
    }>(`/signals${qs.toString() ? `?${qs}` : ""}`);
  },
};
