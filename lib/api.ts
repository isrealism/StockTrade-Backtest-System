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
  performance?: Record<string, unknown>;
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

export interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
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

export async function getStockCandles(code: string) {
  return fetchAPI<{ candles: CandleData[] }>(`/api/stocks/${code}/candles`);
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

export async function getBenchmark(name: string, start: string, end: string) {
  return fetchAPI<{ series: Array<{ date: string; nav: number }> }>(
    `/api/benchmark?name=${encodeURIComponent(name)}&start=${start}&end=${end}`
  );
}

export async function listCompletedBacktests() {
  const data = await listBacktests();
  return {
    items: data.items.filter((item) => item.status === "COMPLETED"),
  };
}
