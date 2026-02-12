import useSWR from "swr";
import {
  getConfig,
  listBacktests,
  getBacktest,
  getRankings,
  listTemplates,
} from "./api";

export function useConfig() {
  return useSWR("config", getConfig, {
    revalidateOnFocus: false,
    dedupingInterval: 60000,
    onErrorRetry: (error, _key, _config, revalidate, { retryCount }) => {
      // Only retry 2 times if backend is unavailable
      if (retryCount >= 2) return;
      setTimeout(() => revalidate({ retryCount }), 5000);
    },
  });
}

export function useBacktests() {
  return useSWR("backtests", listBacktests, {
    refreshInterval: 3000,
  });
}

export function useBacktest(id: string | null) {
  return useSWR(id ? `backtest-${id}` : null, () =>
    id ? getBacktest(id) : null,
    {
      refreshInterval: (data) =>
        data?.status === "RUNNING" || data?.status === "PENDING" ? 1500 : 0,
    }
  );
}

export function useRankings(metric: string) {
  return useSWR(`rankings-${metric}`, () => getRankings(metric));
}

export function useTemplates() {
  return useSWR("templates", listTemplates, {
    revalidateOnFocus: false,
  });
}
