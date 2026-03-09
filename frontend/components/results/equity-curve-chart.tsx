"use client";

import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useBenchmark } from "@/lib/hooks";

const CHART_STYLES = {
  grid: "hsl(220, 14%, 16%)",
  tick: { fill: "hsl(215, 14%, 55%)", fontSize: 10 },
  tooltip: {
    backgroundColor: "hsl(220, 18%, 9%)",
    border: "1px solid hsl(220, 14%, 16%)",
    borderRadius: "6px",
    color: "hsl(210, 20%, 92%)",
    fontSize: 11,
  },
};

interface EquityCurveChartProps {
  equityCurve: Array<Record<string, unknown>>;
  benchmark: string;
  startDate: string;
  endDate: string;
  initialCapital?: number;
}

function formatMoney(val: number): string {
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
  if (val >= 1_000) return `${(val / 1_000).toFixed(0)}K`;
  return val.toFixed(0);
}

export function EquityCurveChart({
  equityCurve,
  benchmark,
  startDate,
  endDate,
  initialCapital,
}: EquityCurveChartProps) {
  const hasBenchmark = benchmark && benchmark !== "none";

  const { data: benchmarkData } = useBenchmark(
    hasBenchmark ? benchmark : null,
    startDate || null,
    endDate || null
  );

  const chartData = useMemo(() => {
    if (!equityCurve.length) return [];

    const initValue =
      initialCapital ?? (equityCurve[0].total_value as number);

    const benchmarkSeries = benchmarkData?.series || [];
    const benchmarkMap = new Map(benchmarkSeries.map((b) => [b.date, b.nav]));
    console.log("benchmark date sample:", benchmarkSeries[0]?.date);
    console.log("equity date sample:", (equityCurve[0]?.date as string));

    return equityCurve.map((point) => {
      const date = (point.date as string).split("T")[0].split(" ")[0];
      const value = point.total_value as number;
      const benchNav = benchmarkMap.get(date);
      const benchValue =
        benchNav !== undefined ? +(benchNav * initValue).toFixed(2) : null;

      return { date, strategy: +value.toFixed(2), benchmark: benchValue };
    });
  }, [equityCurve, benchmarkData, initialCapital]);

  if (!equityCurve.length) return null;

  const xAxisInterval = Math.max(1, Math.floor(chartData.length / 8));

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h3 className="text-sm font-medium text-foreground">资产曲线</h3>
          <p className="text-xs text-muted-foreground">
            {hasBenchmark
              ? `策略资产 vs ${benchmark}（同起点）`
              : "策略资产走势"}
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-[2px] w-5 bg-[hsl(210,100%,52%)]" />
            <span>策略</span>
          </div>
          {hasBenchmark && (
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-[2px] w-5 bg-[hsl(38,92%,50%)]" style={{ borderTop: "2px dashed hsl(38,92%,50%)", height: 0 }} />
              <span>{benchmark}</span>
            </div>
          )}
        </div>
      </div>

      <div className="p-4" style={{ height: 450 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 5, right: 16, left: 8, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
            <XAxis
              dataKey="date"
              tick={CHART_STYLES.tick}
              interval={xAxisInterval}
              tickLine={false}
            />
            <YAxis
              tick={CHART_STYLES.tick}
              tickFormatter={formatMoney}
              tickLine={false}
              axisLine={false}
              width={56}
            />
            <Tooltip
              contentStyle={CHART_STYLES.tooltip}
              formatter={(value: number, name: string) => [
                `¥${value.toLocaleString()}`,
                name === "strategy" ? "策略资产" : benchmark,
              ]}
            />
            <Line
              type="monotone"
              dataKey="strategy"
              stroke="hsl(210, 100%, 52%)"
              strokeWidth={2}
              dot={false}
              name="strategy"
              activeDot={{ r: 4 }}
            />
            {hasBenchmark && (
              <Line
                type="monotone"
                dataKey="benchmark"
                stroke="hsl(38, 92%, 50%)"
                strokeWidth={1.5}
                dot={false}
                strokeDasharray="5 3"
                name="benchmark"
                connectNulls
                activeDot={{ r: 4 }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}