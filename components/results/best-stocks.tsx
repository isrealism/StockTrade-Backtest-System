"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { formatNumber, formatPercent } from "@/lib/utils";
import { TrendingUp, TrendingDown } from "lucide-react";

interface BestStocksProps {
  trades: Array<Record<string, unknown>>;
}

interface StockSummary {
  code: string;
  totalPnl: number;
  avgPnlPct: number;
  tradeCount: number;
  winRate: number;
  bestTradePct: number;
}

export function BestStocks({ trades }: BestStocksProps) {
  const stockRanking = useMemo(() => {
    const stockMap = new Map<
      string,
      { totalPnl: number; totalPnlPct: number[]; wins: number; count: number }
    >();

    trades.forEach((t) => {
      const code = t.code as string;
      const entry = stockMap.get(code) || {
        totalPnl: 0,
        totalPnlPct: [],
        wins: 0,
        count: 0,
      };
      entry.totalPnl += (t.net_pnl as number) || 0;
      entry.totalPnlPct.push((t.net_pnl_pct as number) || 0);
      if ((t.net_pnl as number) > 0) entry.wins += 1;
      entry.count += 1;
      stockMap.set(code, entry);
    });

    return Array.from(stockMap.entries())
      .map(([code, data]): StockSummary => ({
        code,
        totalPnl: data.totalPnl,
        avgPnlPct:
          data.totalPnlPct.length > 0
            ? data.totalPnlPct.reduce((a, b) => a + b, 0) /
              data.totalPnlPct.length
            : 0,
        tradeCount: data.count,
        winRate: data.count > 0 ? (data.wins / data.count) * 100 : 0,
        bestTradePct: Math.max(...data.totalPnlPct),
      }))
      .sort((a, b) => b.totalPnl - a.totalPnl);
  }, [trades]);

  const topStocks = stockRanking.slice(0, 10);
  const worstStocks = stockRanking.slice(-5).reverse();

  if (topStocks.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium text-foreground">
          表现最好的股票
        </h3>
      </div>

      <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
        {/* Top performers */}
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-xs font-medium text-[hsl(var(--profit))]">
            <TrendingUp className="h-3.5 w-3.5" />
            收益最高
          </h4>
          <div className="flex flex-col gap-2">
            {topStocks.map((stock, idx) => (
              <StockRow key={stock.code} stock={stock} rank={idx + 1} />
            ))}
          </div>
        </div>

        {/* Worst performers */}
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-xs font-medium text-[hsl(var(--loss))]">
            <TrendingDown className="h-3.5 w-3.5" />
            亏损最多
          </h4>
          <div className="flex flex-col gap-2">
            {worstStocks.map((stock, idx) => (
              <StockRow
                key={stock.code}
                stock={stock}
                rank={stockRanking.length - idx}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function StockRow({ stock, rank }: { stock: StockSummary; rank: number }) {
  const isProfit = stock.totalPnl >= 0;
  return (
    <div className="flex items-center justify-between rounded-md bg-secondary/50 px-3 py-2">
      <div className="flex items-center gap-3">
        <span className="w-5 text-center font-mono text-xs text-muted-foreground">
          {rank}
        </span>
        <span className="font-mono text-sm font-medium text-primary">
          {stock.code}
        </span>
        <span className="text-xs text-muted-foreground">
          {stock.tradeCount}笔
        </span>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-xs text-muted-foreground">
          胜率 {stock.winRate.toFixed(0)}%
        </span>
        <span className="text-xs text-muted-foreground">
          均收益 {formatPercent(stock.avgPnlPct)}
        </span>
        <span
          className={cn(
            "font-mono text-sm font-medium",
            isProfit
              ? "text-[hsl(var(--profit))]"
              : "text-[hsl(var(--loss))]"
          )}
        >
          {isProfit ? "+" : ""}
          {formatNumber(stock.totalPnl)}
        </span>
      </div>
    </div>
  );
}
