"use client";

import { useState } from "react";
import { useBacktests, useBacktest } from "@/lib/hooks";
import { BacktestSelector } from "@/components/results/backtest-selector";
import { BenchmarkSelector } from "@/components/results/benchmark-selector";
import { KpiCards } from "@/components/results/kpi-cards";
import { ReturnBreakdown } from "@/components/results/return-breakdown";
import { ExitReasonStats } from "@/components/results/exit-reason-stats";
import { TradeTable } from "@/components/results/trade-table";
import { PerformanceCharts } from "@/components/results/performance-charts";
import { MultiStrategyComparison } from "@/components/results/multi-strategy-comparison";
import { BestStocks } from "@/components/results/best-stocks";
import { Loader2 } from "lucide-react";

export default function ResultsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [benchmark, setBenchmark] = useState<string>("上证指数");
  const { data: backtestList, isLoading: listLoading } = useBacktests();
  const { data: backtestDetail, isLoading: detailLoading } =
    useBacktest(selectedId);

  const completedBacktests =
    backtestList?.items?.filter((b) => b.status === "COMPLETED") || [];

  const result = backtestDetail?.result;
  const metrics = backtestDetail?.metrics;
  const equityCurve = result?.equity_curve || [];
  const trades = result?.trades || [];
  const analysis = result?.analysis as Record<string, Record<string, unknown>> | undefined;

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header Row */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">
            结果分析
          </h1>
          <p className="text-sm text-muted-foreground">
            回测结果仪表盘 - 策略表现分析与交易明细
          </p>
        </div>
        <div className="flex items-center gap-3">
          <BacktestSelector
            backtests={completedBacktests}
            selectedId={selectedId}
            onSelect={setSelectedId}
            loading={listLoading}
          />
          <BenchmarkSelector value={benchmark} onChange={setBenchmark} />
        </div>
      </div>

      {/* Loading State */}
      {!selectedId && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-card py-20">
          <p className="text-muted-foreground">
            请选择一个已完成的回测任务查看结果
          </p>
        </div>
      )}

      {selectedId && detailLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span className="ml-2 text-muted-foreground">加载中...</span>
        </div>
      )}

      {selectedId && !detailLoading && result && (
        <>
          {/* KPI Cards */}
          <KpiCards
            metrics={metrics}
            analysis={analysis}
            trades={trades}
            benchmark={benchmark}
          />

          {/* Return Breakdown */}
          <ReturnBreakdown
            analysis={analysis}
            initialCapital={backtestDetail?.payload?.initial_capital ?? 1000000}
          />

          {/* Exit Reason Stats */}
          <ExitReasonStats trades={trades} />

          {/* Performance Charts (Single Strategy) */}
          <PerformanceCharts
            equityCurve={equityCurve}
            trades={trades}
            analysis={analysis}
            benchmark={benchmark}
            startDate={backtestDetail?.start_date || ""}
            endDate={backtestDetail?.end_date || ""}
          />

          {/* Trade Details Table */}
          <TradeTable trades={trades} />

          {/* Multi-Strategy Comparison */}
          <MultiStrategyComparison
            backtests={completedBacktests}
            currentId={selectedId}
          />

          {/* Best Stocks */}
          <BestStocks trades={trades} />
        </>
      )}
    </div>
  );
}
