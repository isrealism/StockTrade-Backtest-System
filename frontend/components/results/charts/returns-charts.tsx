"use client";

import { useMemo } from "react";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
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

interface ReturnsChartsProps {
  chartType: string;
  equityCurve: Array<Record<string, unknown>>;
  benchmark: string;
  startDate: string;
  endDate: string;
}

export function ReturnsCharts({
  chartType,
  equityCurve,
  benchmark,
  startDate,
  endDate,
}: ReturnsChartsProps) {
  const { data: benchmarkData } = useBenchmark(
    benchmark !== "none" ? benchmark : null,
    startDate || null,
    endDate || null
  );

  // Cumulative Return curve data
  const cumulativeData = useMemo(() => {
    if (!equityCurve.length) return [];
    const initialValue = equityCurve[0].total_value as number;
    const benchmarkSeries = benchmarkData?.series || [];
    const benchmarkMap = new Map(
      benchmarkSeries.map((b) => [b.date, b.nav])
    );

    return equityCurve.map((point) => {
      const date = (point.date as string).split("T")[0];
      const nav = (point.total_value as number) / initialValue;
      const benchNav = benchmarkMap.get(date) ?? null;
      return { date, nav: +nav.toFixed(4), benchmark: benchNav };
    });
  }, [equityCurve, benchmarkData]);

  // Drawdown curve data
  const drawdownData = useMemo(() => {
    if (!equityCurve.length) return [];
    let peak = equityCurve[0].total_value as number;
    return equityCurve.map((point) => {
      const val = point.total_value as number;
      if (val > peak) peak = val;
      const dd = peak > 0 ? ((val - peak) / peak) * 100 : 0;
      return {
        date: (point.date as string).split("T")[0],
        drawdown: +dd.toFixed(2),
      };
    });
  }, [equityCurve]);

  // Rolling returns (monthly)
  const rollingData = useMemo(() => {
    if (equityCurve.length < 2) return [];
    const monthly: Record<string, { first: number; last: number }> = {};
    equityCurve.forEach((point) => {
      const date = (point.date as string).split("T")[0];
      const month = date.substring(0, 7);
      const val = point.total_value as number;
      if (!monthly[month]) {
        monthly[month] = { first: val, last: val };
      } else {
        monthly[month].last = val;
      }
    });
    return Object.entries(monthly).map(([month, { first, last }]) => ({
      month,
      return_pct: first > 0 ? +((last / first - 1) * 100).toFixed(2) : 0,
    }));
  }, [equityCurve]);

  if (chartType === "cumulative") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={cumulativeData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis dataKey="date" tick={CHART_STYLES.tick} interval="preserveStartEnd" />
          <YAxis tick={CHART_STYLES.tick} />
          <Tooltip contentStyle={CHART_STYLES.tooltip} />
          <ReferenceLine y={1} stroke="hsl(215, 14%, 30%)" strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="nav"
            stroke="hsl(210, 100%, 52%)"
            strokeWidth={1.5}
            dot={false}
            name="策略净值"
          />
          {benchmark !== "none" && (
            <Line
              type="monotone"
              dataKey="benchmark"
              stroke="hsl(38, 92%, 50%)"
              strokeWidth={1.5}
              dot={false}
              name={benchmark}
              connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "drawdown") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={drawdownData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis dataKey="date" tick={CHART_STYLES.tick} interval="preserveStartEnd" />
          <YAxis tick={CHART_STYLES.tick} />
          <Tooltip
            contentStyle={CHART_STYLES.tooltip}
            formatter={(value: number) => [`${value.toFixed(2)}%`, "回撤"]}
          />
          <ReferenceLine y={0} stroke="hsl(215, 14%, 30%)" />
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="hsl(0, 84%, 60%)"
            fill="hsl(0, 84%, 60%)"
            fillOpacity={0.2}
            strokeWidth={1.5}
            name="回撤"
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // Rolling returns
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rollingData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
        <XAxis dataKey="month" tick={CHART_STYLES.tick} />
        <YAxis tick={CHART_STYLES.tick} />
        <Tooltip
          contentStyle={CHART_STYLES.tooltip}
          formatter={(value: number) => [`${value.toFixed(2)}%`, "月度收益"]}
        />
        <ReferenceLine y={0} stroke="hsl(215, 14%, 30%)" />
        <Bar dataKey="return_pct" name="月度收益" radius={[2, 2, 0, 0]}>
          {rollingData.map((entry, idx) => (
            <Cell
              key={idx}
              fill={
                entry.return_pct >= 0
                  ? "hsl(142, 76%, 46%)"
                  : "hsl(0, 84%, 60%)"
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
