export type Mode = "DEMO" | "PAPER" | "LIVE";
export type JobName = "nightly" | "submit" | "reconcile" | "scan" | "protect";
export type AssetClass = "stocks" | "crypto" | "forex";

/** One book the server runs: stocks at /api, crypto at /api/crypto and forex at /api/forex when it runs them. */
export interface Book {
  id: string;
  label: string;
  path: string;
  account_label: string;
  mode: Mode;
  pending_proposals: number;
}

export interface KillSwitchState {
  engaged: boolean;
  reason: string | null;
  at: string | null;
  by: string | null;
}

export interface Violation {
  code: string;
  message: string;
}

export interface Reconciliation {
  id: number;
  ts: string;
  ok: boolean;
  mismatches: { type: string; message: string }[];
}

export interface Account {
  equity: number;
  cash: number;
  buying_power: number;
  day_pnl_pct: number;
  drawdown_pct: number;
  peak_equity: number;
  open_positions: number;
}

export interface Status {
  mode: Mode;
  book: string;
  asset_class: AssetClass;
  broker: string;
  trading_mode: string;
  dry_run: boolean;
  account_label: string;
  strategy: { name: string } & Record<string, unknown>;
  universe: string[];
  benchmark: string;
  ai_mode: string;
  auto_approve: boolean;
  kill_switch: KillSwitchState;
  account: Account | null;
  clock: { is_open: boolean; next_open: string; next_close: string } | null;
  broker_error: string | null;
  pending_proposals: number;
  scheduler_running: boolean;
  last_runs: Record<string, ({ at: string } & Record<string, unknown>) | null>;
  last_reconciliation: Reconciliation | null;
}

export interface Proposal {
  id: number;
  created_at: string;
  as_of: string;
  symbol: string;
  side: "buy" | "sell";
  kind: "entry" | "exit";
  qty: number;
  est_price: number;
  limit_price: number;
  stop_price: number | null;
  reason: string;
  source: string;
  status: string;
  violations: Violation[];
  ai_rating: string | null;
  ai_summary: string | null;
  client_order_id: string;
  decided_at: string | null;
  decided_by: string | null;
  submitted_at: string | null;
  broker_order_id: string | null;
  error: string | null;
}

export interface Position {
  symbol: string;
  side?: "long" | "short"; // forex can hold shorts (qty below zero) once short selling is on
  qty: number;
  avg_entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_pl_pct: number;
  weight_pct: number;
  stop_price: number | null;
  stop_limit_price?: number | null;
  protected: boolean;
}

export interface Order {
  id: number;
  client_order_id: string;
  broker_order_id: string | null;
  proposal_id: number | null;
  symbol: string;
  side: string;
  action?: "buy" | "sell" | "short" | "cover" | "stop_sell" | "stop_buy" | null;
  qty: number;
  filled_qty: number;
  filled_avg_price: number | null;
  status: string;
  order_class: string;
  limit_price: number | null;
  stop_price: number | null;
  submitted_at: string | null;
  updated_at: string;
}

export interface Signal {
  id: number;
  as_of: string;
  strategy: string;
  symbol: string;
  target_weight: number;
  price: number | null;
}

export interface EquityPoint {
  as_of: string;
  equity: number;
  benchmark: number | null;
}

export interface RiskLimits {
  risk_per_trade_pct: number;
  stop_loss_pct: number;
  max_position_pct: number;
  max_open_positions: number;
  daily_loss_limit_pct: number;
  max_drawdown_pct: number;
  max_orders_per_day: number;
  no_trade_after_open_min: number;
  no_trade_before_close_min: number;
  entry_limit_buffer_pct: number;
  max_entry_fraction: number;
  stop_limit_band_pct?: number;
  allow_shorts?: boolean;
}

export interface Risk {
  limits: RiskLimits;
  usage: {
    orders_today: number;
    open_positions: number | null;
    drawdown_pct: number | null;
    day_pnl_pct: number | null;
  };
  max_gap_pct: number;
  auto_approve: boolean;
}

export interface AIDecision {
  id: number;
  created_at: string;
  as_of: string;
  symbol: string;
  rating: string;
  summary: string;
  model: string;
  cost_usd: number | null;
}

export interface JobResult {
  job: JobName;
  result: Record<string, unknown> & { skipped_reason?: string | null };
}

export type Call = "buy" | "short" | "sell" | "cover" | "hold" | "hold_short" | "stay_out";

export interface RecProposal {
  id: number;
  as_of: string;
  status: string;
  side: "buy" | "sell";
  action?: "buy" | "sell" | "short" | "cover";
  qty: number;
  limit_price: number;
  stop_price: number | null;
  stop_limit_price?: number | null;
  notional: number;
  risk_dollars: number | null;
  risk_pct: number | null;
  violations: string[];
  ai_rating: string | null;
  ai_summary: string | null;
}

export interface RecPosition {
  side?: "long" | "short";
  qty: number;
  avg_entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_pct: number | null;
  stop_price: number | null;
  stop_limit_price?: number | null;
  at_risk: number | null;
}

export interface RecItem {
  symbol: string;
  call: Call;
  reason: string;
  detail: string | null;
  price: number | null;
  target_weight: number;
  proposal: RecProposal | null;
  position: RecPosition | null;
}

export interface TrackRecord {
  start: string;
  end: string;
  data_source: string;
  round_trips: number;
  win_rate: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  cagr: number | null;
  max_drawdown: number | null;
  benchmark: { symbol: string; cagr: number | null; max_drawdown: number | null };
}

export interface Recommendations {
  as_of: string | null;
  strategy: { name: string } & Record<string, unknown>;
  rule: string;
  lesson: string;
  data_source: string;
  benchmark: string;
  track_record: {
    backtest: TrackRecord | null;
    gate1: { passed: boolean; on: string; data_source: string } | null;
    account: { since: string; days: number; return: number; benchmark_return: number | null } | null;
  };
  items: RecItem[];
}

export type IdeaLabel = "buy_idea" | "watch" | "skip" | "no_data";

export interface ScanRow {
  symbol: string;
  rank: number | null;
  label: IdeaLabel;
  close: number | null;
  momentum?: number;
  trend_gap?: number;
  from_high?: number;
  reason: string;
  held?: boolean;
  entry?: number;
  stop?: number | null;
  qty?: number;
  risk_dollars?: number | null;
}

export interface ScanResult {
  as_of: string | null;
  watchlist: string[];
  top_n: number;
  rule: string;
  tested: boolean;
  how_to_test: string;
  rows: ScanRow[];
}

export interface LearnProgress {
  lessons: Record<string, string>;
  quizzes: Record<string, { score: number; total: number; best: number; at: string }>;
}

export interface DeskData {
  status: Status;
  recommendations: Recommendations | null;
  scan: ScanResult | null;
  progress: LearnProgress;
  pending: Proposal[];
  recent: Proposal[];
  positions: Position[];
  orders: Order[];
  equity: EquityPoint[];
  risk: Risk;
  ai: AIDecision[];
}

export type Tone = "good" | "bad" | "neutral";

export interface Notice {
  topic: "stop" | "pairs" | "shorts";
  level: "warning" | "info";
  title: string;
  lines: string[];
}

export interface PairSetInfo {
  pairs: string[];
  stop_loss_pct: number;
  max_position_pct: number;
  max_open_positions: number;
}

/** The dashboard's choices for one book: GET /preferences. */
export interface Preferences {
  book: string;
  stop_loss_pct: number;
  recommended_stop_loss_pct: number;
  stop_range: [number, number];
  stop_source: "dashboard" | "recommended" | "settings file";
  max_loss_per_position_pct: number;
  risk_per_trade_pct: number;
  notes: Notice[];
  forex: {
    pair_set: "standard" | "exotic" | "custom";
    pairs: string[];
    pair_sets: Record<"standard" | "exotic", PairSetInfo>;
    allow_shorts: boolean;
    shorts_available: boolean;
  } | null;
}

export interface PreferencesChange {
  stop_loss_pct?: number | null;
  pair_set?: "standard" | "exotic";
  allow_shorts?: boolean;
  confirm?: boolean;
}

export interface PreferencesResult {
  status: "applied" | "unchanged" | "needs_confirm" | "blocked" | "invalid";
  message: string;
  notices: Notice[];
  expired: number[];
  preferences?: Preferences;
}
