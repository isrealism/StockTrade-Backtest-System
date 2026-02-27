"use client";

import { cn } from "@/lib/utils";
import { formatNumber, formatPercent } from "@/lib/utils";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Target,
  BarChart3,
  Info
} from "lucide-react";

interface ExcessReturnBreakdownProps {
  analysis: Record<string, Record<string, unknown>> | undefined;
  benchmark: string;
}

export function ExcessReturnBreakdown({
  analysis,
  benchmark
}: ExcessReturnBreakdownProps) {
  // Check if benchmark is selected
  if (benchmark === "none" || !benchmark) {
    return (
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h3 className="text-sm font-medium text-foreground">超额收益分析</h3>
          <p className="text-xs text-muted-foreground">
            相对于基准指数的超额收益表现
          </p>
        </div>
        <div className="p-8 text-center">
          <Info className="mx-auto h-12 w-12 text-muted-foreground/50" />
          <p className="mt-3 text-sm text-muted-foreground">
            请选择基准指数以查看超额收益分析
          </p>
        </div>
      </div>
    );
  }

  const benchmarkData = analysis?.benchmark as Record<string, unknown> | undefined;
  const returns = analysis?.returns as Record<string, unknown> | undefined;

  // Extract metrics
  const portfolioReturn = (returns?.total_return_pct as number) ?? 0;
  const portfolioAnnualizedReturn = (returns?.annualized_return_pct as number) ?? 0;

  const benchmarkReturn = (benchmarkData?.benchmark_total_return_pct as number) ?? 0;
  const benchmarkAnnualizedReturn = (benchmarkData?.benchmark_annualized_return_pct as number) ?? 0;

  const excessReturn = (benchmarkData?.excess_return_pct as number) ?? 0;
  const alpha = (benchmarkData?.alpha_pct as number) ?? 0;
  const beta = (benchmarkData?.beta as number) ?? 0;
  const trackingError = (benchmarkData?.tracking_error_pct as number) ?? 0;
  const informationRatio = (benchmarkData?.information_ratio as number) ?? 0;

  // Check if benchmark data is available
  const hasBenchmarkData = benchmarkData && Object.keys(benchmarkData).length > 0;

  if (!hasBenchmarkData) {
    return (
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h3 className="text-sm font-medium text-foreground">超额收益分析</h3>
          <p className="text-xs text-muted-foreground">
            相对于 {benchmark} 的超额收益表现
          </p>
        </div>
        <div className="p-8 text-center">
          <Info className="mx-auto h-12 w-12 text-muted-foreground/50" />
          <p className="mt-3 text-sm text-muted-foreground">
            暂无基准数据，请确保已下载对应的基准指数数据
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium text-foreground">超额收益分析</h3>
        <p className="text-xs text-muted-foreground">
          策略相对于 {benchmark} 的超额收益表现
        </p>
      </div>

      <div className="p-4">
        {/* Excess Return Highlight */}
        <div className="mb-4 rounded-lg bg-secondary/30 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">超额收益率</p>
                <p className="font-mono text-sm font-medium text-foreground">
                  策略 {formatPercent(portfolioReturn)} vs {benchmark} {formatPercent(benchmarkReturn)}
                </p>
              </div>
            </div>
            <div className="text-right">
              <p
                className={cn(
                  "font-mono text-2xl font-bold",
                  excessReturn >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {excessReturn >= 0 ? "+" : ""}
                {formatPercent(excessReturn)}
              </p>
              <p className="text-xs text-muted-foreground">
                {excessReturn >= 0 ? "跑赢基准" : "跑输基准"}
              </p>
            </div>
          </div>
        </div>

        {/* Return Comparison Grid */}
        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {/* Portfolio Return */}
          <div className="rounded-lg border border-border p-4">
            <div className="mb-2 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-[hsl(var(--chart-1))]" />
              <span className="text-xs font-medium text-foreground">策略收益</span>
            </div>
            <div className="mb-1">
              <p
                className={cn(
                  "font-mono text-xl font-semibold",
                  portfolioReturn >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {portfolioReturn >= 0 ? "+" : ""}
                {formatPercent(portfolioReturn)}
              </p>
            </div>
            <div className="flex items-baseline gap-2">
              <p className="text-xs text-muted-foreground">
                年化: {portfolioAnnualizedReturn >= 0 ? "+" : ""}
                {formatPercent(portfolioAnnualizedReturn)}
              </p>
            </div>
          </div>

          {/* Benchmark Return */}
          <div className="rounded-lg border border-border p-4">
            <div className="mb-2 flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
              <span className="text-xs font-medium text-foreground">基准收益</span>
            </div>
            <div className="mb-1">
              <p
                className={cn(
                  "font-mono text-xl font-semibold",
                  benchmarkReturn >= 0
                    ? "text-[hsl(var(--profit))]"
                    : "text-[hsl(var(--loss))]"
                )}
              >
                {benchmarkReturn >= 0 ? "+" : ""}
                {formatPercent(benchmarkReturn)}
              </p>
            </div>
            <div className="flex items-baseline gap-2">
              <p className="text-xs text-muted-foreground">
                年化: {benchmarkAnnualizedReturn >= 0 ? "+" : ""}
                {formatPercent(benchmarkAnnualizedReturn)}
              </p>
            </div>
          </div>
        </div>

        {/* Advanced Metrics */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {/* Alpha */}
          <div className="rounded-lg border border-border p-3">
            <div className="mb-1 flex items-center gap-1">
              <Target className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Alpha (α)</span>
            </div>
            <p
              className={cn(
                "font-mono text-base font-semibold",
                alpha >= 0
                  ? "text-[hsl(var(--profit))]"
                  : "text-[hsl(var(--loss))]"
              )}
            >
              {alpha >= 0 ? "+" : ""}
              {formatPercent(alpha)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Jensen's Alpha
            </p>
          </div>

          {/* Beta */}
          <div className="rounded-lg border border-border p-3">
            <div className="mb-1 flex items-center gap-1">
              <Activity className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Beta (β)</span>
            </div>
            <p className="font-mono text-base font-semibold text-foreground">
              {beta.toFixed(2)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {beta > 1 ? "高波动性" : beta < 1 ? "低波动性" : "同步市场"}
            </p>
          </div>

          {/* Tracking Error */}
          <div className="rounded-lg border border-border p-3">
            <div className="mb-1 flex items-center gap-1">
              <TrendingDown className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">跟踪误差</span>
            </div>
            <p className="font-mono text-base font-semibold text-foreground">
              {formatPercent(trackingError)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              年化标准差
            </p>
          </div>

          {/* Information Ratio */}
          <div className="rounded-lg border border-border p-3">
            <div className="mb-1 flex items-center gap-1">
              <BarChart3 className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">信息比率</span>
            </div>
            <p
              className={cn(
                "font-mono text-base font-semibold",
                informationRatio >= 0
                  ? "text-[hsl(var(--profit))]"
                  : "text-[hsl(var(--loss))]"
              )}
            >
              {informationRatio.toFixed(2)}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {informationRatio > 0.5 ? "优秀" : informationRatio > 0 ? "良好" : "待改进"}
            </p>
          </div>
        </div>

        {/* Explanation */}
        <div className="mt-4 rounded-lg border border-border bg-secondary/20 p-3">
          <div className="flex items-start gap-2">
            <Info className="mt-0.5 h-4 w-4 text-muted-foreground" />
            <div className="flex-1 text-xs text-muted-foreground">
              <p className="mb-1 font-medium">指标说明：</p>
              <ul className="space-y-0.5 pl-4 list-disc">
                <li>
                  <strong>超额收益</strong>: 策略收益 - 基准收益，为正表示跑赢基准
                </li>
                <li>
                  <strong>Alpha (α)</strong>: 扣除风险后的超额收益，衡量策略的主动管理能力
                </li>
                <li>
                  <strong>Beta (β)</strong>: 策略相对基准的波动性，&gt;1 表示比基准波动更大
                </li>
                <li>
                  <strong>信息比率</strong>: 超额收益/跟踪误差，衡量单位风险的超额收益
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Visual Comparison Bar */}
        <div className="mt-4 pt-4 border-t border-border">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
            <span>收益对比</span>
            <span>
              策略 {formatPercent(portfolioReturn)} |
              基准 {formatPercent(benchmarkReturn)} |
              超额 {excessReturn >= 0 ? "+" : ""}{formatPercent(excessReturn)}
            </span>
          </div>
          <div className="relative h-8 w-full rounded-lg overflow-hidden bg-secondary">
            {/* Benchmark bar */}
            <div className="absolute inset-0 flex items-center">
              <div
                className={cn(
                  "h-full transition-all",
                  benchmarkReturn >= 0
                    ? "bg-muted-foreground/30"
                    : "bg-[hsl(var(--loss))]/30"
                )}
                style={{
                  width: `${Math.min(Math.abs(benchmarkReturn), 100)}%`,
                }}
              />
            </div>
            {/* Portfolio bar */}
            <div className="absolute inset-0 flex items-center">
              <div
                className={cn(
                  "h-full transition-all border-2",
                  portfolioReturn >= 0
                    ? "bg-[hsl(var(--profit))]/60 border-[hsl(var(--profit))]"
                    : "bg-[hsl(var(--loss))]/60 border-[hsl(var(--loss))]"
                )}
                style={{
                  width: `${Math.min(Math.abs(portfolioReturn), 100)}%`,
                }}
              />
            </div>
            {/* Labels */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-xs font-mono font-semibold text-foreground mix-blend-difference">
                {excessReturn >= 0 ? "跑赢" : "跑输"} {formatPercent(Math.abs(excessReturn))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
