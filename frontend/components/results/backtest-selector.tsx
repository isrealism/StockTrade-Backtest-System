"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDate } from "@/lib/utils";
import type { BacktestSummary } from "@/lib/api";

interface BacktestSelectorProps {
  backtests: BacktestSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
}

export function BacktestSelector({
  backtests,
  selectedId,
  onSelect,
  loading,
}: BacktestSelectorProps) {
  return (
    <Select value={selectedId || ""} onValueChange={onSelect}>
      <SelectTrigger className="w-[260px] bg-card">
        <SelectValue placeholder={loading ? "加载中..." : "选择回测任务"} />
      </SelectTrigger>
      <SelectContent>
        {backtests.map((bt) => (
          <SelectItem key={bt.id} value={bt.id}>
            <span className="font-medium">{bt.name}</span>
            <span className="ml-2 text-xs text-muted-foreground">
              {formatDate(bt.created_at)}
            </span>
          </SelectItem>
        ))}
        {backtests.length === 0 && (
          <div className="px-3 py-2 text-sm text-muted-foreground">
            暂无已完成的回测
          </div>
        )}
      </SelectContent>
    </Select>
  );
}
