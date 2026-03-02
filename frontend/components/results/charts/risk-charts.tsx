"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";

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

interface RiskChartsProps {
  chartType: string;
  equityCurve: Array<Record<string, unknown>>;
  trades: Array<Record<string, unknown>>;
}

export function RiskCharts({ chartType, equityCurve, trades }: RiskChartsProps) {
  // Return distribution histogram
  const distributionData = useMemo(() => {
    const bins = [
      { label: "<-20%", min: -Infinity, max: -20, count: 0 },
      { label: "-20~-10%", min: -20, max: -10, count: 0 },
      { label: "-10~-5%", min: -10, max: -5, count: 0 },
      { label: "-5~0%", min: -5, max: 0, count: 0 },
      { label: "0~5%", min: 0, max: 5, count: 0 },
      { label: "5~10%", min: 5, max: 10, count: 0 },
      { label: "10~20%", min: 10, max: 20, count: 0 },
      { label: ">20%", min: 20, max: Infinity, count: 0 },
    ];
    trades.forEach((t) => {
      const pct = t.net_pnl_pct as number;
      const bin = bins.find((b) => pct >= b.min && pct < b.max);
      if (bin) bin.count += 1;
    });
    return bins.map((b) => ({ label: b.label, count: b.count, isNeg: b.max <= 0 }));
  }, [trades]);

  // Rolling volatility (20-day)
  const volatilityData = useMemo(() => {
    if (equityCurve.length < 22) return [];
    const returns: number[] = [];
    for (let i = 1; i < equityCurve.length; i++) {
      const prev = equityCurve[i - 1].total_value as number;
      const curr = equityCurve[i].total_value as number;
      returns.push(prev !== 0 ? (curr - prev) / Math.abs(prev) : 0);
    }

    const window = 20;
    const result: Array<{ date: string; volatility: number }> = [];
    for (let i = window; i < returns.length; i++) {
      const slice = returns.slice(i - window, i);
      const mean = slice.reduce((a, b) => a + b, 0) / window;
      const variance =
        slice.reduce((a, b) => a + (b - mean) ** 2, 0) / (window - 1);
      const vol = Math.sqrt(variance) * Math.sqrt(252) * 100;
      result.push({
        date: (equityCurve[i + 1]?.date as string || "").split("T")[0],
        volatility: +vol.toFixed(2),
      });
    }
    return result;
  }, [equityCurve]);

  // Rolling Sharpe ratio (60-day)
  const sharpeData = useMemo(() => {
    if (equityCurve.length < 62) return [];
    const returns: number[] = [];
    for (let i = 1; i < equityCurve.length; i++) {
      const prev = equityCurve[i - 1].total_value as number;
      const curr = equityCurve[i].total_value as number;
      returns.push(prev !== 0 ? (curr - prev) / Math.abs(prev) : 0);
    }

    const window = 60;
    const dailyRf = 0.03 / 252;
    const result: Array<{ date: string; sharpe: number }> = [];
    for (let i = window; i < returns.length; i++) {
      const slice = returns.slice(i - window, i);
      const mean = slice.reduce((a, b) => a + b, 0) / window;
      const variance =
        slice.reduce((a, b) => a + (b - mean) ** 2, 0) / (window - 1);
      const std = Math.sqrt(variance);
      const sharpe = std > 0 ? ((mean - dailyRf) / std) * Math.sqrt(252) : 0;
      result.push({
        date: (equityCurve[i + 1]?.date as string || "").split("T")[0],
        sharpe: +sharpe.toFixed(3),
      });
    }
    return result;
  }, [equityCurve]);

  if (chartType === "distribution") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={distributionData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis dataKey="label" tick={CHART_STYLES.tick} />
          <YAxis tick={CHART_STYLES.tick} />
          <Tooltip
            contentStyle={CHART_STYLES.tooltip}
            formatter={(value: number) => [value, "笔数"]}
          />
          <Bar dataKey="count" radius={[3, 3, 0, 0]}>
            {distributionData.map((entry, idx) => (
              <Cell
                key={idx}
                fill={
                  entry.isNeg
                    ? "hsl(0, 84%, 60%)"
                    : "hsl(142, 76%, 46%)"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "volatility") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={volatilityData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis dataKey="date" tick={CHART_STYLES.tick} interval="preserveStartEnd" />
          <YAxis tick={CHART_STYLES.tick} />
          <Tooltip
            contentStyle={CHART_STYLES.tooltip}
            formatter={(value: number) => [`${value.toFixed(2)}%`, "年化波动率"]}
          />
          <Line
            type="monotone"
            dataKey="volatility"
            stroke="hsl(38, 92%, 50%)"
            strokeWidth={1.5}
            dot={false}
            name="年化波动率"
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // Sharpe ratio trend
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={sharpeData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
        <XAxis dataKey="date" tick={CHART_STYLES.tick} interval="preserveStartEnd" />
        <YAxis tick={CHART_STYLES.tick} />
        <Tooltip
          contentStyle={CHART_STYLES.tooltip}
          formatter={(value: number) => [value.toFixed(3), "滚动夏普"]}
        />
        <ReferenceLine y={0} stroke="hsl(215, 14%, 30%)" strokeDasharray="3 3" />
        <Line
          type="monotone"
          dataKey="sharpe"
          stroke="hsl(280, 65%, 60%)"
          strokeWidth={1.5}
          dot={false}
          name="滚动夏普比率"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
