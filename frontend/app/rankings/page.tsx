"use client";

import { useState } from "react";
import { useRankings } from "@/lib/hooks";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn, formatPercent, formatNumber, formatDate } from "@/lib/utils";
import { Trophy, Medal, Loader2, BarChart3, ExternalLink } from "lucide-react";
import Link from "next/link";

const METRIC_OPTIONS = [
  { value: "score", label: "综合评分" },
  { value: "total_return_pct", label: "总收益率" },
  { value: "win_rate_pct", label: "胜率" },
  { value: "sharpe_ratio", label: "夏普比率" },
  { value: "max_drawdown_pct", label: "最大回撤 (升序)" },
];

function getRankIcon(rank: number) {
  if (rank === 0) return <Trophy className="h-5 w-5 text-chart-3" />;
  if (rank === 1) return <Medal className="h-5 w-5 text-muted-foreground" />;
  if (rank === 2) return <Medal className="h-5 w-5 text-chart-3/60" />;
  return (
    <span className="flex h-5 w-5 items-center justify-center text-xs font-medium text-muted-foreground">
      {rank + 1}
    </span>
  );
}

export default function RankingsPage() {
  const [metric, setMetric] = useState("score");
  const { data, isLoading } = useRankings(metric);

  const items = data?.items || [];

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-foreground">策略排名</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            历史回测策略排名对比
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">排序指标:</span>
          <Select value={metric} onValueChange={setMetric}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {METRIC_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {isLoading && (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      )}

      {!isLoading && items.length === 0 && (
        <div className="flex h-40 flex-col items-center justify-center text-muted-foreground">
          <Trophy className="mb-2 h-10 w-10" />
          <p className="text-sm">暂无排名数据</p>
          <p className="mt-1 text-xs">完成回测后即可查看策略排名</p>
        </div>
      )}

      {!isLoading && items.length > 0 && (
        <div className="space-y-2">
          {items.map((item, idx) => {
            const m = item.metrics || {};
            return (
              <Link
                key={item.id}
                href={`/results?id=${item.id}`}
                className="block"
              >
                <Card
                  className={cn(
                    "transition-all hover:border-primary/30 hover:bg-primary/5",
                    idx === 0 && "border-chart-3/30 bg-chart-3/5"
                  )}
                >
                  <CardContent className="flex items-center gap-4 py-4">
                    {/* Rank */}
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center">
                      {getRankIcon(idx)}
                    </div>

                    {/* Name & Date & ID */}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">
                        {item.name}
                        <span className="ml-1.5 font-mono text-[10px] text-muted-foreground">
                          #{item.id.slice(0, 6)}
                        </span>
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {formatDate(item.created_at)}
                      </p>
                    </div>

                    {/* Metrics Grid */}
                    <div className="hidden gap-6 sm:flex">
                      <div className="text-right">
                        <p className="text-[10px] text-muted-foreground">
                          评分
                        </p>
                        <p className="font-mono text-sm font-semibold text-foreground">
                          {(m.score ?? 0).toFixed(2)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-muted-foreground">
                          收益率
                        </p>
                        <p
                          className={cn(
                            "font-mono text-sm font-semibold",
                            (m.total_return_pct ?? 0) >= 0
                              ? "text-[hsl(var(--profit))]"
                              : "text-[hsl(var(--loss))]"
                          )}
                        >
                          {formatPercent(m.total_return_pct ?? 0)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-muted-foreground">
                          胜率
                        </p>
                        <p className="font-mono text-sm text-foreground">
                          {formatPercent(m.win_rate_pct ?? 0)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-muted-foreground">
                          夏普
                        </p>
                        <p className="font-mono text-sm text-foreground">
                          {(m.sharpe_ratio ?? 0).toFixed(2)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-muted-foreground">
                          回撤
                        </p>
                        <p className="font-mono text-sm text-[hsl(var(--loss))]">
                          {formatPercent(m.max_drawdown_pct ?? 0)}
                        </p>
                      </div>
                    </div>

                    {/* Rank Value Badge */}
                    <Badge
                      variant={idx === 0 ? "default" : "secondary"}
                      className="shrink-0"
                    >
                      {metric === "score"
                        ? (item.rank_value ?? 0).toFixed(2)
                        : metric.includes("pct")
                        ? formatPercent(item.rank_value ?? 0)
                        : (item.rank_value ?? 0).toFixed(3)}
                    </Badge>

                    <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
