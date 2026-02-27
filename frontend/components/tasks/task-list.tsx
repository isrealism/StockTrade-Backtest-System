"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn, formatDate, formatPercent } from "@/lib/utils";
import type { BacktestSummary } from "@/lib/api";
import {
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Ban,
  ChevronRight,
} from "lucide-react";

const STATUS_CONFIG: Record<
  string,
  { label: string; icon: typeof Clock; color: string }
> = {
  PENDING: { label: "等待中", icon: Clock, color: "text-chart-3" },
  RUNNING: { label: "运行中", icon: Loader2, color: "text-primary" },
  COMPLETED: { label: "已完成", icon: CheckCircle2, color: "text-[hsl(var(--profit))]" },
  FAILED: { label: "失败", icon: XCircle, color: "text-[hsl(var(--loss))]" },
  CANCELLED: { label: "已取消", icon: Ban, color: "text-muted-foreground" },
};

interface TaskListProps {
  tasks: BacktestSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
}

export function TaskList({ tasks, activeId, onSelect }: TaskListProps) {
  if (tasks.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center text-muted-foreground">
        <Clock className="mb-2 h-8 w-8" />
        <p className="text-sm">暂无回测任务</p>
        <p className="mt-1 text-xs">在回测配置页面创建新任务</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {tasks.map((task) => {
        const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.PENDING;
        const Icon = config.icon;
        const isActive = task.id === activeId;

        return (
          <button
            key={task.id}
            onClick={() => onSelect(task.id)}
            className={cn(
              "flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all",
              isActive
                ? "border-primary/30 bg-primary/5"
                : "border-border bg-card hover:bg-secondary/50"
            )}
          >
            <Icon
              className={cn(
                "h-4 w-4 shrink-0",
                config.color,
                task.status === "RUNNING" && "animate-spin"
              )}
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-foreground">
                  {task.name}
                </span>
                <Badge
                  variant={
                    task.status === "COMPLETED"
                      ? "success"
                      : task.status === "FAILED"
                      ? "destructive"
                      : "secondary"
                  }
                  className="shrink-0 text-[10px]"
                >
                  {config.label}
                </Badge>
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                <span>
                  {task.start_date} ~ {task.end_date}
                </span>
                {task.status === "RUNNING" && (
                  <span className="text-primary">
                    {task.progress.toFixed(1)}%
                  </span>
                )}
                {task.metrics && (
                  <span
                    className={cn(
                      (task.metrics.total_return_pct ?? 0) >= 0
                        ? "text-[hsl(var(--profit))]"
                        : "text-[hsl(var(--loss))]"
                    )}
                  >
                    {formatPercent(task.metrics.total_return_pct ?? 0)}
                  </span>
                )}
              </div>
              {task.status === "RUNNING" && (
                <Progress value={task.progress} className="mt-2 h-1" />
              )}
            </div>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>
        );
      })}
    </div>
  );
}
