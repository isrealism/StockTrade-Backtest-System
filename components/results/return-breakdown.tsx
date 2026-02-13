"use client";

import { cn } from "@/lib/utils";
import { formatNumber, formatPercent } from "@/lib/utils";
import { TrendingUp, TrendingDown, DollarSign, CheckCircle, Clock } from "lucide-react";

interface ReturnBreakdownProps {
  analysis: Record<string, Record<string, unknown>> | undefined;
  initialCapital?: number;
}

export function ReturnBreakdown({ analysis, initialCapital = 1000000 }: ReturnBreakdownProps) {
  const returns = analysis?.returns as Record<string, unknown> | undefined;

  const totalProfit = (returns?.total_profit as number) ?? 0;
  const totalReturnPct = (returns?.total_return_pct as number) ?? 0;
  const realizedPnl = (returns?.realized_pnl as number) ?? 0;
  const realizedPnlPct = (returns?.realized_pnl_pct as number) ?? 0;
  const unrealizedPnl = (returns?.unrealized_pnl as number) ?? 0;
  const unrealizedPnlPct = (returns?.unrealized_pnl_pct as number) ?? 0;
  const finalValue = (returns?.final_value as number) ?? 0;

  // Check if there are open positions
  const hasOpenPositions = Math.abs(unrealizedPnl) > 1; // Allow for small rounding errors

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium text-foreground">收益分解</h3>
        <p className="text-xs text-muted-foreground">
          已实现收益 vs 未实现收益明细
        </p>
      </div>

      <div className="p-4">
        {/* Total Return */}
        <div className="mb-4 rounded-lg bg-secondary/30 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <DollarSign className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">总收益</p>
                <p className="font-mono text-sm font-medium text-foreground">
                  初始资金 {formatNumber(initialCapital)} → 最终资产 {formatNumber(finalValue)}
                </p>
              </div>
            </div>
            <div className="text-right">
              <p
                className={cn(
                  "font-mono text-2xl font-bold",
                  totalProfit >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {totalProfit >= 0 ? "+" : ""}
                {formatNumber(totalProfit)}
              </p>
              <p
                className={cn(
                  "font-mono text-sm",
                  totalReturnPct >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {totalReturnPct >= 0 ? "+" : ""}
                {formatPercent(totalReturnPct)}
              </p>
            </div>
          </div>
        </div>

        {/* Breakdown Grid */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {/* Realized PnL */}
          <div className="rounded-lg border border-border p-4">
            <div className="mb-2 flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-[hsl(var(--profit))]" />
              <span className="text-xs font-medium text-foreground">已实现收益</span>
            </div>
            <div className="mb-1">
              <p
                className={cn(
                  "font-mono text-xl font-semibold",
                  realizedPnl >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {realizedPnl >= 0 ? "+" : ""}
                {formatNumber(realizedPnl)}
              </p>
            </div>
            <div className="flex items-baseline gap-2">
              <p
                className={cn(
                  "font-mono text-sm",
                  realizedPnlPct >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {realizedPnlPct >= 0 ? "+" : ""}
                {formatPercent(realizedPnlPct)}
              </p>
              <p className="text-xs text-muted-foreground">来自已平仓交易</p>
            </div>
          </div>

          {/* Unrealized PnL */}
          <div className="rounded-lg border border-border p-4">
            <div className="mb-2 flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="text-xs font-medium text-foreground">未实现收益</span>
            </div>
            <div className="mb-1">
              <p
                className={cn(
                  "font-mono text-xl font-semibold",
                  unrealizedPnl >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {unrealizedPnl >= 0 ? "+" : ""}
                {formatNumber(unrealizedPnl)}
              </p>
            </div>
            <div className="flex items-baseline gap-2">
              <p
                className={cn(
                  "font-mono text-sm",
                  unrealizedPnlPct >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {unrealizedPnlPct >= 0 ? "+" : ""}
                {formatPercent(unrealizedPnlPct)}
              </p>
              <p className="text-xs text-muted-foreground">来自未平仓持仓</p>
            </div>
          </div>
        </div>

        {/* Warning for open positions */}
        {hasOpenPositions && (
          <div className="mt-4 rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3">
            <div className="flex items-start gap-2">
              <Clock className="mt-0.5 h-4 w-4 text-yellow-600" />
              <div className="flex-1">
                <p className="text-xs font-medium text-yellow-600">
                  注意：回测结束时存在未平仓持仓
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  未实现收益为{unrealizedPnl >= 0 ? "浮盈" : "浮亏"}，实际收益取决于平仓时的价格。
                  建议：回测引擎已在结束时强制平仓所有持仓，最新回测结果中未实现收益应接近0。
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Composition */}
        <div className="mt-4 pt-4 border-t border-border">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>收益构成</span>
            <span>
              已实现 {((realizedPnl / Math.abs(totalProfit)) * 100 || 0).toFixed(1)}% |
              未实现 {((unrealizedPnl / Math.abs(totalProfit)) * 100 || 0).toFixed(1)}%
            </span>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-secondary">
            <div className="flex h-full">
              {totalProfit !== 0 && (
                <>
                  <div
                    className={cn(
                      "h-full transition-all",
                      realizedPnl >= 0 ? "bg-[hsl(var(--profit))]" : "bg-[hsl(var(--loss))]"
                    )}
                    style={{
                      width: `${Math.abs((realizedPnl / totalProfit) * 100)}%`,
                    }}
                  />
                  <div
                    className={cn(
                      "h-full transition-all",
                      unrealizedPnl >= 0 ? "bg-[hsl(var(--profit))]/50" : "bg-[hsl(var(--loss))]/50"
                    )}
                    style={{
                      width: `${Math.abs((unrealizedPnl / totalProfit) * 100)}%`,
                    }}
                  />
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
