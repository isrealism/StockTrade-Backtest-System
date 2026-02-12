import type {
  ApiConfig,
  BacktestDetail,
  BacktestItem,
  BacktestPayload,
  BenchmarkPoint,
  RankingItem,
  Template,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

/* ── Config ── */
export function fetchConfig(): Promise<ApiConfig> {
  return request("/api/config");
}

/* ── Backtests ── */
export function createBacktest(
  payload: Partial<BacktestPayload>
): Promise<{ id: string; status: string }> {
  return request("/api/backtests", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchBacktests(): Promise<{ items: BacktestItem[] }> {
  return request("/api/backtests");
}

export function fetchBacktestDetail(id: string): Promise<BacktestDetail> {
  return request(`/api/backtests/${id}`);
}

export function cancelBacktest(
  id: string
): Promise<{ id: string; status: string }> {
  return request(`/api/backtests/${id}/cancel`, { method: "POST" });
}

/* ── Templates ── */
export function fetchTemplates(): Promise<{ items: Template[] }> {
  return request("/api/templates");
}

export function createTemplate(
  payload: Partial<BacktestPayload> & { name: string }
): Promise<{ id: string }> {
  return request("/api/templates", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteTemplate(id: string): Promise<{ id: string }> {
  return request(`/api/templates/${id}`, { method: "DELETE" });
}

/* ── Rankings ── */
export function fetchRankings(
  metric: string = "score"
): Promise<{ items: RankingItem[] }> {
  return request(`/api/rankings?metric=${metric}`);
}

/* ── Benchmark ── */
export function fetchBenchmark(
  name: string,
  start: string,
  end: string
): Promise<{ series: BenchmarkPoint[] }> {
  return request(
    `/api/benchmark?name=${encodeURIComponent(name)}&start=${start}&end=${end}`
  );
}

/* ── SWR fetchers ── */
export const swrFetcher = <T>(url: string): Promise<T> => request<T>(url);
