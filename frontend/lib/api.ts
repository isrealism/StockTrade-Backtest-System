const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "API request failed");
  }
  return res.json();
}

// Types
export interface SelectorConfig {
  class: string;
  alias: string;
  activate: boolean;
  params: Record<string, unknown>;
}

export interface SellStrategyConfig {
  description: string;
  name: string;
  combination_logic?: string;
  strategies?: Array<{
    class: string;
    params: Record<string, unknown>;
  }>;
  class?: string;
  params?: Record<string, unknown>;
}

export interface BacktestPayload {
  name?: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
  max_positions?: number;
  position_sizing?: string;
  commission_rate?: number;
  stamp_tax_rate?: number;
  slippage_rate?: number;
  sell_strategy_name?: string;
  sell_strategy_config?: unknown;
  buy_config?: unknown;
  stock_pool?: { type: string; codes?: string[] };
  lookback_days?: number;

  // ── Score 百分位过滤 ──────────────────────────────────────────────
  score_filter_enabled?: boolean;
  /** 百分位阈值，0–100，默认 60（只保留历史前 40% 强信号） */
  score_percentile_threshold?: number;
  /** 触发百分位计算的最低历史样本数，默认 20 */
  score_min_history?: number;
  /** 预热期天数，默认 20 */
  score_warmup_lookback_days?: number;

  // ── 换仓 (Rotation) ───────────────────────────────────────────────
  rotation_enabled?: boolean;
  /** 触发换仓考虑的最低未实现亏损比例，默认 0.05 (5%) */
  rotation_min_loss?: number;
  /** 每日最大换仓对数，默认 2 */
  rotation_max_per_day?: number;
  /** 新信号 score 须 >= 旧入场 score × 此倍数，默认 1.2 */
  rotation_score_ratio?: number;
  /** 新信号 score 须超过旧入场 score 的绝对值，默认 10.0 */
  rotation_min_score_improvement?: number;
  /** 无 entry_score 仓位的处理策略：skip / allow / mean，默认 skip */
  rotation_no_score_policy?: "skip" | "allow" | "mean";
}


export interface BacktestSummary {
  id: string;
  name: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  progress: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  start_date: string;
  end_date: string;
  metrics: Record<string, number> | null;
  error: string | null;
}

export interface BacktestDetail extends BacktestSummary {
  payload: BacktestPayload | null;
  result: BacktestResult | null;
  logs: Array<{ ts: string; message: string }>;
}

export interface BacktestResult {
  equity_curve: Array<Record<string, unknown>>;
  trades: Array<Record<string, unknown>>;
  analysis: Record<string, unknown>;
  strategy_score: { score: number; components: Record<string, number> };
  best_trade: Record<string, unknown> | null;
  best_stock: { code: string; net_pnl: number } | null;
}

export interface Template {
  id: string;
  name: string;
  created_at: string;
  payload: BacktestPayload;
}

// API Functions
export async function getConfig() {
  return fetchAPI<{
    selectors: SelectorConfig[];
    sell_strategies: Record<string, SellStrategyConfig>;
  }>("/api/config");
}

export async function listBacktests() {
  return fetchAPI<{ items: BacktestSummary[] }>("/api/backtests");
}

export async function createBacktest(payload: BacktestPayload) {
  return fetchAPI<{ id: string; status: string }>("/api/backtests", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getBacktest(id: string) {
  return fetchAPI<BacktestDetail>(`/api/backtests/${id}`);
}

export async function cancelBacktest(id: string) {
  return fetchAPI<{ id: string; status: string }>(
    `/api/backtests/${id}/cancel`,
    { method: "POST" }
  );
}

export async function listTemplates() {
  return fetchAPI<{ items: Template[] }>("/api/templates");
}

export async function createTemplate(payload: Record<string, unknown>) {
  return fetchAPI<{ id: string }>("/api/templates", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteTemplate(id: string) {
  return fetchAPI<{ id: string; status: string }>(`/api/templates/${id}`, {
    method: "DELETE",
  });
}

export async function getRankings(metric = "score") {
  return fetchAPI<{
    items: Array<{
      id: string;
      name: string;
      created_at: string;
      metrics: Record<string, number>;
      rank_value: number;
    }>;
  }>(`/api/rankings?metric=${metric}`);
}

export interface KLineDataPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export async function getKLineData(code: string, start?: string, end?: string) {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const qs = params.toString();
  return fetchAPI<{ code: string; data: KLineDataPoint[] }>(
    `/api/kline/${encodeURIComponent(code)}${qs ? `?${qs}` : ""}`
  );
}

export interface BenchmarkSeries {
  date: string;
  nav: number;
}

export async function getBenchmark(name: string, start: string, end: string) {
  return fetchAPI<{ series: BenchmarkSeries[] }>(
    `/api/benchmark?name=${encodeURIComponent(name)}&start=${start}&end=${end}`
  );
}

export async function getBacktestAnalysis(backtestId: string, benchmark: string = "none") {
  return fetchAPI<{
    backtest_id: string;
    benchmark: string;
    analysis: Record<string, unknown>;
  }>(
    `/api/backtests/${encodeURIComponent(backtestId)}/analysis?benchmark=${encodeURIComponent(benchmark)}`
  );
}
