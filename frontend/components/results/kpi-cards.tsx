"use client";

import { cn } from "@/lib/utils";
import { formatNumber, formatPercent } from "@/lib/utils";
import {
  BarChart3,
  TrendingUp,
  TrendingDown,
  Target,
  DollarSign,
  Activity,
} from "lucide-react";

interface KpiCardsProps {
  metrics: Record<string, number> | null | undefined;
  analysis: Record<string, Record<string, unknown>> | undefined;
  trades: Array<Record<string, unknown>>;
  benchmark: string;
}

interface KpiItem {
  label: string;
  value: string;
  subValue?: string;
  icon: React.ElementType;
  color: "default" | "profit" | "loss" | "warning";
}

export function KpiCards({ metrics, analysis, trades, benchmark }: KpiCardsProps) {
  const totalTrades = trades.length;
  const winningTrades = trades.filter(
    (t) => (t.net_pnl as number) > 0
  ).length;
  const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
  const totalReturnPct = metrics?.total_return_pct ?? 0;
  const maxDrawdownPct = metrics?.max_drawdown_pct ?? 0;
  const finalValue = metrics?.final_value ?? 0;
  const sharpRatio = metrics?.sharpe_ratio ?? 0;

  // Excess return from analysis benchmark data
  const benchmarkData = analysis?.benchmark as
    | Record<string, unknown>
    | undefined;
  const excessReturnPct =
    benchmark !== "none" && benchmarkData
      ? (benchmarkData.excess_return_pct as number) ?? 0
      : 0;

  const kpis: KpiItem[] = [
    {
      label: "总交易数",
      value: totalTrades.toString(),
      icon: BarChart3,
      color: "default",
    },
    {
      label: "胜率",
      value: formatPercent(winRate),
      subValue: `${winningTrades}/${totalTrades}`,
      icon: Target,
      color: winRate >= 50 ? "profit" : "loss",
    },
    {
      label: "总收益率",
      value: formatPercent(totalReturnPct),
      icon: totalReturnPct >= 0 ? TrendingUp : TrendingDown,
      color: totalReturnPct >= 0 ? "profit" : "loss",
    },
    {
      label: "超额收益率",
      value:
        benchmark !== "none"
          ? formatPercent(excessReturnPct)
          : "--",
      subValue: benchmark !== "none" ? `vs ${benchmark}` : undefined,
      icon: Activity,
      color:
        benchmark === "none"
          ? "default"
          : excessReturnPct >= 0
            ? "profit"
            : "loss",
    },
    {
      label: "最大回撤",
      value: formatPercent(Math.abs(maxDrawdownPct)),
      icon: TrendingDown,
      color: "loss",
    },
    {
      label: "总资产",
      value: formatNumber(finalValue),
      subValue: `夏普 ${sharpRatio.toFixed(2)}`,
      icon: DollarSign,
      color: finalValue >= 1000000 ? "profit" : "loss",
    },
  ];

  const colorMap = {
    default: "text-foreground",
    profit: "text-[hsl(var(--profit))]",
    loss: "text-[hsl(var(--loss))]",
    warning: "text-[hsl(var(--chart-3))]",
  };

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      {kpis.map((kpi) => (
        <div
          key={kpi.label}
          className="flex flex-col gap-1 rounded-lg border border-border bg-card p-4"
        >
          <div className="flex items-center gap-2">
            <kpi.icon className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">{kpi.label}</span>
          </div>
          <span
            className={cn("font-mono text-lg font-semibold", colorMap[kpi.color])}
          >
            {kpi.value}
          </span>
          {kpi.subValue && (
            <span className="font-mono text-xs text-muted-foreground">
              {kpi.subValue}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
