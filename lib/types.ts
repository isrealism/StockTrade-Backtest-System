/* ── Selector / Buy Config ── */
export interface SelectorParam {
  [key: string]: number | boolean | string | SelectorParam;
}

export interface SelectorConfig {
  class: string;
  alias: string;
  activate: boolean;
  params: SelectorParam;
}

export interface SelectorCombination {
  mode: "OR" | "AND";
  time_window_days: number;
  required_selectors: string[];
}

export interface BuyConfig {
  selector_combination: SelectorCombination;
  selectors: SelectorConfig[];
}

/* ── Sell Strategy ── */
export interface SellSubStrategy {
  class: string;
  params: Record<string, number | boolean | string>;
}

export interface SellStrategyConfig {
  description: string;
  name: string;
  combination_logic?: "ANY" | "ALL";
  strategies?: SellSubStrategy[];
  class?: string;
  params?: Record<string, number | boolean | string>;
}

/* ── API Config Response ── */
export interface ApiConfig {
  selectors: SelectorConfig[];
  sell_strategies: Record<string, SellStrategyConfig>;
}

/* ── Stock Pool ── */
export interface StockPool {
  type: "all" | "list";
  codes?: string[];
}

/* ── Backtest Payload ── */
export interface BacktestPayload {
  name: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  max_positions: number;
  position_sizing: string;
  commission_rate: number;
  stamp_tax_rate: number;
  slippage_rate: number;
  lookback_days: number;
  stock_pool: StockPool;
  buy_config: BuyConfig;
  sell_strategy_name: string;
  sell_strategy_config?: SellStrategyConfig;
}

/* ── Backtest Metrics ── */
export interface BacktestMetrics {
  total_return_pct: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  sharpe_ratio: number;
  final_value: number;
  score: number;
}

/* ── Backtest List Item ── */
export interface BacktestItem {
  id: string;
  name: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  progress: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  start_date: string;
  end_date: string;
  metrics: BacktestMetrics | null;
  error: string | null;
}

/* ── Log Entry ── */
export interface LogEntry {
  ts: string;
  message: string;
}

/* ── Trade Record ── */
export interface TradeRecord {
  code: string;
  name?: string;
  buy_date: string;
  sell_date: string;
  buy_price: number;
  sell_price: number;
  shares: number;
  net_pnl: number;
  net_pnl_pct: number;
  holding_days: number;
  exit_reason: string;
  selector_alias?: string;
  buy_selector?: string;
}

/* ── Equity Curve Point ── */
export interface EquityPoint {
  date: string;
  nav: number;
  total_value?: number;
  cash?: number;
  position_value?: number;
}

/* ── Benchmark Point ── */
export interface BenchmarkPoint {
  date: string;
  nav: number;
}

/* ── Performance Analysis ── */
export interface PerformanceAnalysis {
  returns: {
    total_return_pct: number;
    annual_return_pct: number;
    final_value: number;
    trading_days: number;
  };
  risk_adjusted: {
    sharpe_ratio: number;
    sortino_ratio: number;
    calmar_ratio: number;
  };
  drawdown: {
    max_drawdown_pct: number;
    max_drawdown_duration_days: number;
    avg_drawdown_pct: number;
  };
  trade_stats: {
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate_pct: number;
    avg_pnl_pct: number;
    avg_win_pct: number;
    avg_loss_pct: number;
    profit_factor: number;
    avg_holding_days: number;
    max_consecutive_wins: number;
    max_consecutive_losses: number;
  };
  monthly_returns?: Record<string, number>;
  exit_analysis?: Record<string, number>;
}

/* ── Strategy Score ── */
export interface StrategyScore {
  score: number;
  components: {
    total_return_pct: number;
    sharpe_ratio: number;
    max_drawdown_pct: number;
    win_rate_pct: number;
  };
}

/* ── Backtest Detail (full) ── */
export interface BacktestDetail {
  id: string;
  name: string;
  status: string;
  progress: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  start_date: string;
  end_date: string;
  payload: BacktestPayload;
  result: {
    equity_curve: EquityPoint[];
    trades: TradeRecord[];
    analysis: PerformanceAnalysis;
    strategy_score: StrategyScore;
    best_trade: TradeRecord | null;
    best_stock: { code: string; net_pnl: number } | null;
  } | null;
  metrics: BacktestMetrics | null;
  error: string | null;
  logs: LogEntry[];
}

/* ── Template ── */
export interface Template {
  id: string;
  name: string;
  created_at: string;
  payload: BacktestPayload;
}

/* ── Ranking Item ── */
export interface RankingItem {
  id: string;
  name: string;
  created_at: string;
  metrics: BacktestMetrics;
  rank_value: number;
}
