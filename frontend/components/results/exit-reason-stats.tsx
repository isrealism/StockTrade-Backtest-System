"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface ExitReasonStatsProps {
  trades: Array<Record<string, unknown>>;
}

function parseExitReason(raw: string): string {
  if (!raw) return "未知";
  if (raw.includes("FullProfitTarget") || raw.includes("Profit Target")) return "止盈";
  if (raw.includes("TrailingStop") || raw.includes("Trailing Stop")) return "追踪止损";
  if (raw.includes("TimedExit") || raw.includes("Holding Period")) return "超时退出";
  if (raw.includes("StopLoss") || raw.includes("Stop Loss")) return "止损";
  if (raw.includes("KDJ") || raw.includes("BBI") || raw.includes("MA")) return "指标信号";
  if (raw.includes("Chandelier")) return "吊灯止损";
  if (raw.includes("ATR")) return "ATR止损";
  if (raw.includes("ZXLines")) return "ZX线止损";
  if (raw.includes("Volatility")) return "波动率止损";
  return "其他";
}

const COLORS = [
  "hsl(142, 76%, 46%)",
  "hsl(0, 84%, 60%)",
  "hsl(38, 92%, 50%)",
  "hsl(210, 100%, 52%)",
  "hsl(280, 65%, 60%)",
  "hsl(180, 70%, 45%)",
  "hsl(330, 70%, 55%)",
];

export function ExitReasonStats({ trades }: ExitReasonStatsProps) {
  const data = useMemo(() => {
    const reasonMap = new Map<string, { count: number; wins: number; totalPnl: number }>();
    trades.forEach((t) => {
      const reason = parseExitReason(t.exit_reason as string);
      const entry = reasonMap.get(reason) || { count: 0, wins: 0, totalPnl: 0 };
      entry.count += 1;
      if ((t.net_pnl as number) > 0) entry.wins += 1;
      entry.totalPnl += (t.net_pnl as number) || 0;
      reasonMap.set(reason, entry);
    });

    return Array.from(reasonMap.entries())
      .map(([reason, { count, wins, totalPnl }]) => ({
        reason,
        count,
        winRate: count > 0 ? ((wins / count) * 100) : 0,
        avgPnl: count > 0 ? totalPnl / count : 0,
      }))
      .sort((a, b) => b.count - a.count);
  }, [trades]);

  if (data.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-medium text-foreground">清仓理由统计</h3>
      <div className="flex flex-col gap-4 lg:flex-row">
        {/* Chart */}
        <div className="h-[200px] flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ left: 60, right: 20, top: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 14%, 16%)" />
              <XAxis type="number" tick={{ fill: "hsl(215, 14%, 55%)", fontSize: 12 }} />
              <YAxis
                type="category"
                dataKey="reason"
                tick={{ fill: "hsl(215, 14%, 55%)", fontSize: 12 }}
                width={60}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(220, 18%, 9%)",
                  border: "1px solid hsl(220, 14%, 16%)",
                  borderRadius: "6px",
                  color: "hsl(210, 20%, 92%)",
                  fontSize: 12,
                }}
                formatter={(value: number) => [value, "笔数"]}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {data.map((_entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={COLORS[index % COLORS.length]}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Stats Table */}
        <div className="flex flex-col gap-2 lg:w-[320px]">
          {data.map((item, idx) => (
            <div
              key={item.reason}
              className="flex items-center justify-between rounded-md bg-secondary/50 px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <div
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: COLORS[idx % COLORS.length] }}
                />
                <span className="text-sm text-foreground">{item.reason}</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="font-mono text-xs text-muted-foreground">
                  {item.count}笔
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  胜率 {item.winRate.toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
