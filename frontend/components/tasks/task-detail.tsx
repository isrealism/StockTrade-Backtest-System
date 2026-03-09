"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { useBacktest } from "@/lib/hooks";
import { cancelBacktest } from "@/lib/api";
import { PayloadViewerDialog } from "@/components/shared/payload-viewer-dialog";
import { BacktestVisualization } from "@/components/tasks/backtest-visualization";
import { cn, formatDate, formatPercent, formatNumber } from "@/lib/utils";
import {
  Square,
  Loader2,
  BarChart3,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

interface TaskDetailProps {
  backtestId: string;
}

export function TaskDetail({ backtestId }: TaskDetailProps) {
  const { data, isLoading, mutate } = useBacktest(backtestId);
  const [cancelling, setCancelling] = useState(false);

  async function handleCancel() {
    setCancelling(true);
    try {
      await cancelBacktest(backtestId);
      if (data) {
        mutate({ ...data, status: "CANCELLED" as const }, false);
      }
    } catch (error) {
      console.error("Failed to cancel backtest:", error);
    } finally {
      setCancelling(false);
    }
  }

  if (isLoading || !data) {
    return (
      <div className="flex h-60 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  const isRunning = data.status === "RUNNING" || data.status === "PENDING";
  const isCompleted = data.status === "COMPLETED";
  const isFailed = data.status === "FAILED";
  const isCancelled = data.status === "CANCELLED";

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold text-foreground">{data.name}</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            ID: {data.id.slice(0, 8)}... | 创建于 {formatDate(data.created_at)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* ✅ 任务配置按键 */}
          <PayloadViewerDialog payload={data.payload} />

          {isRunning && (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleCancel}
              disabled={cancelling}
            >
              {cancelling ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Square className="mr-1.5 h-3.5 w-3.5" />
              )}
              中止回测
            </Button>
          )}
          {isCompleted && (
            <Button asChild size="sm">
              <Link href={`/results?id=${backtestId}`}>
                <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
                查看结果
              </Link>
            </Button>
          )}
        </div>
      </div>

      {/* Progress */}
      {isRunning && (
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">回测进度</span>
              <span className="font-mono text-primary">
                {data.progress.toFixed(1)}%
              </span>
            </div>
            <Progress value={data.progress} className="mt-2" />
          </CardContent>
        </Card>
      )}

      {/* Error */}
      {isFailed && data.error && (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="py-4">
            <p className="text-sm text-[hsl(var(--loss))]">
              Error: {data.error}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Cancelled */}
      {isCancelled && (
        <Card className="border-muted bg-muted/20">
          <CardContent className="py-4">
            <p className="text-sm text-muted-foreground">回测任务已取消</p>
          </CardContent>
        </Card>
      )}

      {/* Quick Metrics */}
      {isCompleted && data.metrics && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            {
              label: "总收益率",
              value: formatPercent(data.metrics.total_return_pct ?? 0),
              isPositive: (data.metrics.total_return_pct ?? 0) >= 0,
            },
            {
              label: "最大回撤",
              value: formatPercent(data.metrics.max_drawdown_pct ?? 0),
              isPositive: false,
            },
            {
              label: "胜率",
              value: formatPercent(data.metrics.win_rate_pct ?? 0),
              isPositive: (data.metrics.win_rate_pct ?? 0) >= 50,
            },
            {
              label: "策略评分",
              value: (data.metrics.score ?? 0).toFixed(2),
              isPositive: (data.metrics.score ?? 0) >= 5,
            },
          ].map((metric) => (
            <Card key={metric.label}>
              <CardContent className="py-3">
                <p className="text-xs text-muted-foreground">{metric.label}</p>
                <p
                  className={cn(
                    "mt-1 text-lg font-semibold font-mono",
                    metric.label === "最大回撤"
                      ? "text-[hsl(var(--loss))]"
                      : metric.isPositive
                      ? "text-[hsl(var(--profit))]"
                      : "text-[hsl(var(--loss))]"
                  )}
                >
                  {metric.value}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Backtest Visualization - Real-time Asset Curve + Trade Records */}
      <BacktestVisualization
        logs={data.logs || []}
        initialCapital={data.payload?.initial_capital || 1000000}
        isRunning={isRunning}
      />
    </div>
  );
}
