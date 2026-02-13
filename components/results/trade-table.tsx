"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { formatPercent } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { KLineDialog } from "./k-line-dialog";
import { ArrowUpDown, Search, Filter } from "lucide-react";

interface Trade {
  code: string;
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  shares: number;
  holding_days: number;
  net_pnl: number;
  net_pnl_pct: number;
  gross_pnl: number;
  gross_pnl_pct: number;
  max_unrealized_pnl_pct: number;
  exit_reason: string;
  buy_strategy: string;
}

type SortKey = keyof Trade;
type SortDir = "asc" | "desc";

function parseExitReasonCategory(raw: string): string {
  if (!raw) return "未知";
  if (raw.includes("FullProfitTarget") || raw.includes("Profit Target")) return "止盈";
  if (raw.includes("TrailingStop") || raw.includes("Trailing Stop")) return "追踪止损";
  if (raw.includes("TimedExit") || raw.includes("Holding Period")) return "超时退出";
  if (raw.includes("StopLoss") || raw.includes("Stop Loss")) return "止损";
  return "其他";
}

interface TradeTableProps {
  trades: Array<Record<string, unknown>>;
}

export function TradeTable({ trades: rawTrades }: TradeTableProps) {
  const [search, setSearch] = useState("");
  const [exitFilter, setExitFilter] = useState("all");
  const [strategyFilter, setStrategyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("entry_date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);

  const trades = rawTrades as unknown as Trade[];

  // Unique exit reasons and strategies for filters
  const exitReasons = useMemo(() => {
    const set = new Set<string>();
    trades.forEach((t) => set.add(parseExitReasonCategory(t.exit_reason)));
    return Array.from(set);
  }, [trades]);

  const strategies = useMemo(() => {
    const set = new Set<string>();
    trades.forEach((t) => {
      if (t.buy_strategy) set.add(t.buy_strategy);
    });
    return Array.from(set);
  }, [trades]);

  // Filter and sort
  const filtered = useMemo(() => {
    let result = [...trades];

    if (search) {
      result = result.filter((t) =>
        t.code.toLowerCase().includes(search.toLowerCase())
      );
    }

    if (exitFilter !== "all") {
      result = result.filter(
        (t) => parseExitReasonCategory(t.exit_reason) === exitFilter
      );
    }

    if (strategyFilter !== "all") {
      result = result.filter((t) => t.buy_strategy === strategyFilter);
    }

    result.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortDir === "asc" ? aVal - bVal : bVal - aVal;
      }
      return sortDir === "asc"
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal));
    });

    return result;
  }, [trades, search, exitFilter, strategyFilter, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const columns: { key: SortKey; label: string; mono?: boolean; align?: string }[] = [
    { key: "code", label: "股票代码", mono: true },
    { key: "entry_date", label: "建仓日期" },
    { key: "entry_price", label: "建仓价格", mono: true, align: "right" },
    { key: "shares", label: "仓位", mono: true, align: "right" },
    { key: "exit_date", label: "清仓日期" },
    { key: "exit_price", label: "清仓价格", mono: true, align: "right" },
    { key: "net_pnl_pct", label: "收益率", mono: true, align: "right" },
    { key: "holding_days", label: "持仓周期", mono: true, align: "right" },
    { key: "exit_reason", label: "清仓原因" },
    { key: "buy_strategy", label: "选股器" },
  ];

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="text-sm font-medium text-foreground">交易明细</h3>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="搜索股票代码..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 w-[160px] bg-secondary pl-8 text-xs"
            />
          </div>
          <Select value={exitFilter} onValueChange={setExitFilter}>
            <SelectTrigger className="h-8 w-[120px] bg-secondary text-xs">
              <Filter className="mr-1 h-3 w-3" />
              <SelectValue placeholder="清仓原因" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部原因</SelectItem>
              {exitReasons.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={strategyFilter} onValueChange={setStrategyFilter}>
            <SelectTrigger className="h-8 w-[140px] bg-secondary text-xs">
              <Filter className="mr-1 h-3 w-3" />
              <SelectValue placeholder="选股器" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部选股器</SelectItem>
              {strategies.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-xs text-muted-foreground">
            {filtered.length}/{trades.length} 笔
          </span>
        </div>
      </div>

      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    "cursor-pointer whitespace-nowrap px-3 py-2.5 text-left font-medium text-muted-foreground transition-colors hover:text-foreground",
                    col.align === "right" && "text-right"
                  )}
                  onClick={() => toggleSort(col.key)}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    {sortKey === col.key && (
                      <ArrowUpDown className="h-3 w-3 text-primary" />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((trade, idx) => (
              <tr
                key={`${trade.code}-${trade.entry_date}-${idx}`}
                className="cursor-pointer border-b border-border/50 transition-colors hover:bg-secondary/50"
                onClick={() => setSelectedTrade(trade)}
              >
                <td className="whitespace-nowrap px-3 py-2 font-mono font-medium text-primary">
                  {trade.code}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-foreground">
                  {trade.entry_date}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-foreground">
                  {trade.entry_price.toFixed(2)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-foreground">
                  {trade.shares.toLocaleString()}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-foreground">
                  {trade.exit_date}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-foreground">
                  {trade.exit_price.toFixed(2)}
                </td>
                <td
                  className={cn(
                    "whitespace-nowrap px-3 py-2 text-right font-mono font-medium",
                    trade.net_pnl_pct >= 0
                      ? "text-[hsl(var(--profit))]"
                      : "text-[hsl(var(--loss))]"
                  )}
                >
                  {trade.net_pnl_pct >= 0 ? "+" : ""}
                  {formatPercent(trade.net_pnl_pct)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-muted-foreground">
                  {trade.holding_days}天
                </td>
                <td className="max-w-[120px] truncate whitespace-nowrap px-3 py-2 text-muted-foreground">
                  {parseExitReasonCategory(trade.exit_reason)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                  {trade.buy_strategy}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="py-8 text-center text-sm text-muted-foreground">
            暂无匹配的交易记录
          </div>
        )}
      </div>

      {/* K-Line Dialog */}
      <KLineDialog
        trade={selectedTrade}
        onClose={() => setSelectedTrade(null)}
      />
    </div>
  );
}
