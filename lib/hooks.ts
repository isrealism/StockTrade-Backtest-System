import useSWR from "swr";
import {
  getConfig,
  listBacktests,
  getBacktest,
  getRankings,
  listTemplates,
  getBenchmark,
} from "./api";

export function useConfig() {
  const { data, error, isLoading } = useSWR("config", getConfig, {
    revalidateOnFocus: false,
    dedupingInterval: 60000,
    onErrorRetry: (error, _key, _config, revalidate, { retryCount }) => {
      // Only retry 2 times if backend is unavailable
      if (retryCount >= 2) return;
      setTimeout(() => revalidate({ retryCount }), 5000);
    },
  });
  return { data, error, isLoading };
}

export function useBacktests() {
  const { data, error, isLoading } = useSWR("backtests", listBacktests, {
    refreshInterval: 3000,
  });
  return { data, error, isLoading };
}

export function useBacktest(id: string | null) {
  const { data, error, isLoading } = useSWR(id ? `backtest-${id}` : null, () =>
    id ? getBacktest(id) : null,
    {
      refreshInterval: (data) =>
        data?.status === "RUNNING" || data?.status === "PENDING" ? 1500 : 0,
    }
  );
  return { data, error, isLoading };
}

export function useRankings(metric: string) {
  const { data, error, isLoading } = useSWR(`rankings-${metric}`, () => getRankings(metric));
  return { data, error, isLoading };
}

export function useTemplates() {
  const { data, error, isLoading } = useSWR("templates", listTemplates, {
    revalidateOnFocus: false,
  });
  return { data, error, isLoading };
}

export function useBenchmark(
  name: string | null,
  start: string | null,
  end: string | null
) {
  const key =
    name && start && end ? `benchmark-${name}-${start}-${end}` : null;
  const { data, error, isLoading } = useSWR(
    key,
    () => (name && start && end ? getBenchmark(name, start, end) : null),
    { revalidateOnFocus: false }
  );
  return { data, error, isLoading };
}

export function useMultipleBacktests(ids: string[]) {
  const { data, error, isLoading } = useSWR(
    ids.length > 0 ? `multi-backtests-${ids.join(",")}` : null,
    async () => {
      const results = await Promise.all(ids.map((id) => getBacktest(id)));
      return results;
    },
    { revalidateOnFocus: false }
  );
  return { data, error, isLoading };
}
