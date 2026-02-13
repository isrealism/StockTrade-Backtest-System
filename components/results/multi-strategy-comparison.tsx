"use client";

import { useState, useMemo } from "react";
import { useMultipleBacktests } from "@/lib/hooks";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from "recharts";
import type { BacktestSummary } from "@/lib/api";

interface MultiStrategyComparisonProps {
  backtests: BacktestSummary[];
  currentId: string;
}

const MULTI_COLORS = [
  "hsl(210, 100%, 52%)",
  "hsl(142, 76%, 46%)",
  "hsl(38, 92%, 50%)",
  "hsl(280, 65%, 60%)",
  "hsl(0, 84%, 60%)",
  "hsl(180, 70%, 45%)",
  "hsl(330, 70%, 55%)",
  "hsl(60, 80%, 50%)",
];

const TOOLTIP_STYLE = {
  backgroundColor: "hsl(220, 18%, 9%)",
  border: "1px solid hsl(220, 14%, 16%)",
  borderRadius: "6px",
  color: "hsl(210, 20%, 92%)",
  fontSize: 11,
};

export function MultiStrategyComparison({
  backtests,
  currentId,
}: MultiStrategyComparisonProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([currentId]);

  // Fetch all selected backtests
  const { data: detailResults } = useMultipleBacktests(selectedIds);

  function toggleBacktest(id: string) {
    setSelectedIds((prev) =>
      prev.includes(id)
        ? prev.filter((i) => i !== id)
        : [...prev, id]
    );
  }

  // Merge equity curves
  const chartData = useMemo(() => {
    if (!detailResults || detailResults.length === 0) return [];

    // Collect all dates and nav series
    const dateMap = new Map<string, Record<string, number>>();

    detailResults.forEach((bt) => {
      if (!bt?.result?.equity_curve?.length) return;
      const curve = bt.result.equity_curve;
      const initial = (curve[0] as Record<string, unknown>).total_value as number;

      curve.forEach((point: Record<string, unknown>) => {
        const date = (point.date as string).split("T")[0];
        const nav = initial !== 0 ? (point.total_value as number) / initial : 1;
        const existing = dateMap.get(date) || {};
        existing[bt.id] = +nav.toFixed(4);
        dateMap.set(date, existing);
      });
    });

    return Array.from(dateMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, values]) => ({ date, ...values }));
  }, [detailResults]);

  // Name map
  const nameMap = useMemo(() => {
    const map = new Map<string, string>();
    backtests.forEach((bt) => map.set(bt.id, bt.name));
    return map;
  }, [backtests]);

  if (backtests.length < 2) return null;

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium text-foreground">
          多策略对比
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          选择多个策略叠加净值曲线进行比较
        </p>
      </div>

      {/* Backtest chips */}
      <div className="flex flex-wrap gap-2 border-b border-border px-4 py-3">
        {backtests.map((bt, idx) => {
          const isSelected = selectedIds.includes(bt.id);
          const color = MULTI_COLORS[idx % MULTI_COLORS.length];
          return (
            <button
              key={bt.id}
              onClick={() => toggleBacktest(bt.id)}
              className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                isSelected
                  ? "border-primary/50 bg-primary/10 text-foreground"
                  : "border-border bg-secondary text-muted-foreground hover:bg-secondary/80"
              }`}
            >
              {isSelected && (
                <div
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: color }}
                />
              )}
              {bt.name}
            </button>
          );
        })}
      </div>

      {/* Chart */}
      <div className="h-[320px] p-4">
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(220, 14%, 16%)"
              />
              <XAxis
                dataKey="date"
                tick={{ fill: "hsl(215, 14%, 55%)", fontSize: 10 }}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: "hsl(215, 14%, 55%)", fontSize: 10 }}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend
                wrapperStyle={{
                  fontSize: 11,
                  color: "hsl(215, 14%, 55%)",
                }}
              />
              <ReferenceLine
                y={1}
                stroke="hsl(215, 14%, 30%)"
                strokeDasharray="3 3"
              />
              {selectedIds.map((id, idx) => (
                <Line
                  key={id}
                  type="monotone"
                  dataKey={id}
                  stroke={MULTI_COLORS[backtests.findIndex((bt) => bt.id === id) % MULTI_COLORS.length]}
                  strokeWidth={1.5}
                  dot={false}
                  name={nameMap.get(id) || id.substring(0, 8)}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            请选择至少一个策略
          </div>
        )}
      </div>
    </div>
  );
}
