"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
  Legend,
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

const COLORS = [
  "hsl(210, 100%, 52%)",
  "hsl(142, 76%, 46%)",
  "hsl(38, 92%, 50%)",
  "hsl(280, 65%, 60%)",
  "hsl(0, 84%, 60%)",
  "hsl(180, 70%, 45%)",
];

interface EventChartsProps {
  chartType: string;
  equityCurve: Array<Record<string, unknown>>;
  trades: Array<Record<string, unknown>>;
}

function getStrategy(t: Record<string, unknown>): string {
  return (t.buy_strategy as string) || "未知";
}

export function EventCharts({
  chartType,
  equityCurve,
  trades,
}: EventChartsProps) {
  // Event trigger distribution (by strategy and month)
  const triggerDistData = useMemo(() => {
    const monthMap = new Map<string, number>();
    trades.forEach((t) => {
      const month = (t.entry_date as string).substring(0, 7);
      monthMap.set(month, (monthMap.get(month) || 0) + 1);
    });
    return Array.from(monthMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, count]) => ({ month, count }));
  }, [trades]);

  // Event return scatter
  const scatterData = useMemo(() => {
    return trades.map((t) => ({
      date: t.entry_date as string,
      pnl: t.net_pnl_pct as number,
      code: t.code as string,
      strategy: getStrategy(t),
    }));
  }, [trades]);

  // Holding period distribution
  const holdingDistData = useMemo(() => {
    const bins = [
      { label: "0-5天", min: 0, max: 5, count: 0 },
      { label: "6-10天", min: 6, max: 10, count: 0 },
      { label: "11-20天", min: 11, max: 20, count: 0 },
      { label: "21-30天", min: 21, max: 30, count: 0 },
      { label: "31-60天", min: 31, max: 60, count: 0 },
      { label: ">60天", min: 61, max: Infinity, count: 0 },
    ];
    trades.forEach((t) => {
      const days = t.holding_days as number;
      const bin = bins.find((b) => days >= b.min && days <= b.max);
      if (bin) bin.count += 1;
    });
    return bins;
  }, [trades]);

  // Event win rate by strategy
  const winRateData = useMemo(() => {
    const strategyMap = new Map<
      string,
      { total: number; wins: number }
    >();
    trades.forEach((t) => {
      const strategy = getStrategy(t);
      const entry = strategyMap.get(strategy) || { total: 0, wins: 0 };
      entry.total += 1;
      if ((t.net_pnl as number) > 0) entry.wins += 1;
      strategyMap.set(strategy, entry);
    });
    return Array.from(strategyMap.entries()).map(
      ([strategy, { total, wins }]) => ({
        strategy,
        winRate: total > 0 ? +((wins / total) * 100).toFixed(1) : 0,
        total,
      })
    );
  }, [trades]);

  // Equity curve + positions dual axis
  const equityPositionsData = useMemo(() => {
    if (!equityCurve.length) return [];
    return equityCurve.map((point) => ({
      date: (point.date as string).split("T")[0],
      totalValue: +(((point.total_value as number) / 1e4).toFixed(2)),
      positions: (point.num_positions as number) || 0,
    }));
  }, [equityCurve]);

  if (chartType === "trigger_dist") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={triggerDistData}
          margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis dataKey="month" tick={CHART_STYLES.tick} />
          <YAxis tick={CHART_STYLES.tick} />
          <Tooltip
            contentStyle={CHART_STYLES.tooltip}
            formatter={(value: number) => [value, "触发次数"]}
          />
          <Bar
            dataKey="count"
            fill="hsl(210, 100%, 52%)"
            radius={[3, 3, 0, 0]}
            name="触发次数"
          />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "event_scatter") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis
            dataKey="date"
            tick={CHART_STYLES.tick}
            name="日期"
            type="category"
          />
          <YAxis
            dataKey="pnl"
            tick={CHART_STYLES.tick}
            name="收益(%)"
          />
          <Tooltip
            contentStyle={CHART_STYLES.tooltip}
            formatter={(value: number, name: string) => {
              if (name === "pnl") return [`${value.toFixed(2)}%`, "收益"];
              return [value, name];
            }}
            labelFormatter={(label) => `日期: ${label}`}
          />
          <ReferenceLine y={0} stroke="hsl(215, 14%, 30%)" strokeDasharray="3 3" />
          <Scatter data={scatterData} name="交易">
            {scatterData.map((entry, idx) => (
              <Cell
                key={idx}
                fill={
                  entry.pnl >= 0
                    ? "hsl(142, 76%, 46%)"
                    : "hsl(0, 84%, 60%)"
                }
                fillOpacity={0.7}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "holding_dist") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={holdingDistData}
          margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis dataKey="label" tick={CHART_STYLES.tick} />
          <YAxis tick={CHART_STYLES.tick} />
          <Tooltip
            contentStyle={CHART_STYLES.tooltip}
            formatter={(value: number) => [value, "笔数"]}
          />
          <Bar
            dataKey="count"
            fill="hsl(280, 65%, 60%)"
            radius={[3, 3, 0, 0]}
            name="笔数"
          />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "event_winrate") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={winRateData}
          layout="vertical"
          margin={{ top: 5, right: 10, left: 60, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
          <XAxis type="number" tick={CHART_STYLES.tick} domain={[0, 100]} />
          <YAxis
            type="category"
            dataKey="strategy"
            tick={CHART_STYLES.tick}
            width={60}
          />
          <Tooltip
            contentStyle={CHART_STYLES.tooltip}
            formatter={(value: number) => [`${value}%`, "胜率"]}
          />
          <ReferenceLine x={50} stroke="hsl(215, 14%, 30%)" strokeDasharray="3 3" />
          <Bar dataKey="winRate" name="胜率" radius={[0, 3, 3, 0]}>
            {winRateData.map((entry, idx) => (
              <Cell
                key={idx}
                fill={COLORS[idx % COLORS.length]}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // Equity curve + positions
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={equityPositionsData}
        margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_STYLES.grid} />
        <XAxis
          dataKey="date"
          tick={CHART_STYLES.tick}
          interval="preserveStartEnd"
        />
        <YAxis yAxisId="left" tick={CHART_STYLES.tick} />
        <YAxis yAxisId="right" orientation="right" tick={CHART_STYLES.tick} />
        <Tooltip contentStyle={CHART_STYLES.tooltip} />
        <Legend
          wrapperStyle={{ fontSize: 10, color: "hsl(215, 14%, 55%)" }}
        />
        <Line
          yAxisId="left"
          type="monotone"
          dataKey="totalValue"
          stroke="hsl(210, 100%, 52%)"
          strokeWidth={1.5}
          dot={false}
          name="资金(万)"
        />
        <Line
          yAxisId="right"
          type="stepAfter"
          dataKey="positions"
          stroke="hsl(38, 92%, 50%)"
          strokeWidth={1}
          dot={false}
          name="持仓数"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
