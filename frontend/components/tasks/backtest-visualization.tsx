"use client";

import { useMemo, useRef, useEffect } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn, formatDate } from "@/lib/utils";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Calendar,
  DollarSign,
} from "lucide-react";

const CHART_STYLES = {
  grid: "hsl(220, 14%, 16%)",
  tick: { fill: "hsl(215, 14%, 55%)", fontSize: 10 },
  tooltip: {
    backgroundColor: "hsl(220, 18%, 9%)",
    border: "1px solid hsl(220, 14%, 16%)",
    borderRadius: "8px",
    color: "hsl(210, 20%, 92%)",
    fontSize: 11,
    padding: "8px 12px",
  },
};

interface LogEntry {
  ts: string;
  message: string;
}

interface EquityPoint {
  date: string;
  value: number;
  cash?: number;
  positions_value?: number;
}

interface TradeRecord {
  date: string;
  action: "BUY" | "SELL" | "HOLD";
  code?: string;
  price?: number;
  shares?: number;
  amount?: number;
  asset: number;
  change?: number;
  reason?: string;
}

interface BacktestVisualizationProps {
  logs: LogEntry[];
  initialCapital?: number;
  isRunning?: boolean;
}

function formatMoney(val: number): string {
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
  if (val >= 1_000) return `${(val / 1_000).toFixed(0)}K`;
  return val.toFixed(0);
}

function formatFullMoney(val: number): string {
  return `¥${val.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Parse logs to extract equity curve and trade records
// Backend log formats:
// - Date header: "--- 2024-01-01 ---"
// - Portfolio: "Portfolio: X positions, Cash: XXX, Total: XXX"
// - Executed: "EXECUTED BUY: CODE x SHARES @ PRICE" or "EXECUTED SELL: ..."
// - Buy signal: "BUY SIGNAL #N: CODE (STRATEGY) SHARES shares @ ~PRICE"
function parseLogsToData(logs: LogEntry[], initialCapital: number) {
  const equityCurve: EquityPoint[] = [];
  const tradeRecords: TradeRecord[] = [];
  const seenDates = new Set<string>();

  // Add initial point
  if (initialCapital > 0) {
    equityCurve.push({
      date: "起始",
      value: initialCapital,
    });
  }

  let currentDate = "";
  let currentAsset = initialCapital;

  for (const log of logs) {
    const msg = log.message;

    // Parse date header: "--- 2024-01-01 ---"
    const dateHeaderMatch = msg.match(/^---\s*(\d{4}-\d{2}-\d{2})\s*---$/);
    if (dateHeaderMatch) {
      currentDate = dateHeaderMatch[1];
      continue;
    }

    // Parse portfolio summary: "Portfolio: X positions, Cash: XXX, Total: XXX"
    const portfolioMatch = msg.match(/Portfolio:\s*\d+\s*positions?,\s*Cash:\s*([\d,.]+),\s*Total:\s*([\d,.]+)/i);
    if (portfolioMatch && currentDate) {
      const total = parseFloat(portfolioMatch[2].replace(/,/g, ""));
      if (!isNaN(total) && !seenDates.has(currentDate)) {
        seenDates.add(currentDate);
        currentAsset = total;
        equityCurve.push({
          date: currentDate.slice(5), // MM-DD format
          value: total,
          cash: parseFloat(portfolioMatch[1].replace(/,/g, "")),
        });
      }
    }

    // Parse executed trades: "EXECUTED BUY: CODE x SHARES @ PRICE"
    const executedBuyMatch = msg.match(/EXECUTED\s+BUY:\s*([A-Za-z0-9.]+)\s*x\s*([\d,]+)\s*@\s*([\d.]+)/i);
    if (executedBuyMatch) {
      const code = executedBuyMatch[1];
      const shares = parseInt(executedBuyMatch[2].replace(/,/g, ""));
      const price = parseFloat(executedBuyMatch[3]);
      tradeRecords.push({
        date: currentDate ? currentDate.slice(5) : "",
        action: "BUY",
        code,
        price,
        shares,
        amount: price * shares,
        asset: currentAsset,
      });
    }

    // Parse executed sell: "EXECUTED SELL: CODE x SHARES @ PRICE"
    const executedSellMatch = msg.match(/EXECUTED\s+SELL:\s*([A-Za-z0-9.]+)\s*x\s*([\d,]+)\s*@\s*([\d.]+)/i);
    if (executedSellMatch) {
      const code = executedSellMatch[1];
      const shares = parseInt(executedSellMatch[2].replace(/,/g, ""));
      const price = parseFloat(executedSellMatch[3]);
      // Try to find P&L info from nearby logs
      const pnlMatch = msg.match(/P&L:\s*([-+]?[\d.]+)%/);
      const change = pnlMatch ? parseFloat(pnlMatch[1]) : undefined;
      tradeRecords.push({
        date: currentDate ? currentDate.slice(5) : "",
        action: "SELL",
        code,
        price,
        shares,
        amount: price * shares,
        asset: currentAsset,
        change,
      });
    }

    // Also support Chinese format: "买入/卖出 CODE @ PRICE, 数量: SHARES"
    const buyMatchCN = msg.match(/买入\s*([A-Za-z0-9.]+)\s*[@＠]\s*([\d.]+).*(?:数量|股数)[：:]\s*([\d,]+)/);
    const sellMatchCN = msg.match(/卖出\s*([A-Za-z0-9.]+)\s*[@＠]\s*([\d.]+).*(?:数量|股数)[：:]\s*([\d,]+)/);

    if (buyMatchCN) {
      const code = buyMatchCN[1];
      const price = parseFloat(buyMatchCN[2]);
      const shares = parseInt(buyMatchCN[3].replace(/,/g, ""));
      tradeRecords.push({
        date: currentDate ? currentDate.slice(5) : "",
        action: "BUY",
        code,
        price,
        shares,
        amount: price * shares,
        asset: currentAsset,
      });
    }

    if (sellMatchCN) {
      const code = sellMatchCN[1];
      const price = parseFloat(sellMatchCN[2]);
      const shares = parseInt(sellMatchCN[3].replace(/,/g, ""));
      const profitMatch = msg.match(/(?:盈亏|收益)[：:]\s*([-+]?[\d,.]+)/);
      const change = profitMatch ? parseFloat(profitMatch[1].replace(/,/g, "")) : undefined;
      tradeRecords.push({
        date: currentDate ? currentDate.slice(5) : "",
        action: "SELL",
        code,
        price,
        shares,
        amount: price * shares,
        asset: currentAsset,
        change,
      });
    }

    // Fallback: "日期: YYYY-MM-DD, 资产: XXX" or "Total: XXX"
    const dateAssetMatch = msg.match(/日期[：:]\s*(\d{4}-\d{2}-\d{2}).*资产[：:]\s*([\d,.]+)/);
    if (dateAssetMatch) {
      const date = dateAssetMatch[1];
      const asset = parseFloat(dateAssetMatch[2].replace(/,/g, ""));
      if (!isNaN(asset) && !seenDates.has(date)) {
        seenDates.add(date);
        currentAsset = asset;
        equityCurve.push({
          date: date.slice(5),
          value: asset,
        });
      }
    }
  }

  return { equityCurve, tradeRecords };
}

// Custom Tooltip Component
function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number }[]; label?: string }) {
  if (!active || !payload || !payload.length) return null;

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold text-foreground">
        {formatFullMoney(payload[0].value)}
      </p>
    </div>
  );
}

export function BacktestVisualization({
  logs,
  initialCapital = 1000000,
  isRunning = false,
}: BacktestVisualizationProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const { equityCurve, tradeRecords } = useMemo(
    () => parseLogsToData(logs, initialCapital),
    [logs, initialCapital]
  );

  // Calculate stats
  const stats = useMemo(() => {
    if (equityCurve.length < 2) {
      return { currentValue: initialCapital, change: 0, changePercent: 0, isProfit: true };
    }
    const currentValue = equityCurve[equityCurve.length - 1].value;
    const change = currentValue - initialCapital;
    const changePercent = ((change / initialCapital) * 100);
    return {
      currentValue,
      change,
      changePercent,
      isProfit: change >= 0,
    };
  }, [equityCurve, initialCapital]);

  // Get min/max for chart
  const { minValue, maxValue } = useMemo(() => {
    if (equityCurve.length === 0) {
      return { minValue: initialCapital * 0.9, maxValue: initialCapital * 1.1 };
    }
    const values = equityCurve.map((p) => p.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = (max - min) * 0.1 || initialCapital * 0.05;
    return {
      minValue: Math.floor((min - padding) / 1000) * 1000,
      maxValue: Math.ceil((max + padding) / 1000) * 1000,
    };
  }, [equityCurve, initialCapital]);

  // Auto scroll to bottom for trade records
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [tradeRecords.length]);

  const xAxisInterval = Math.max(1, Math.floor(equityCurve.length / 10));

  return (
    <div className="space-y-4">
      {/* Asset Curve Card */}
      <Card className="overflow-hidden">
        <CardHeader className="border-b border-border bg-gradient-to-r from-card to-secondary/20 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                <Activity className="h-5 w-5 text-primary" />
              </div>
              <div>
                <CardTitle className="text-sm font-medium">实时资产曲线</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {isRunning ? "回测进行中..." : "回测数据"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              {/* Current Value */}
              <div className="text-right">
                <p className="text-xs text-muted-foreground">当前资产</p>
                <p className="text-lg font-bold tabular-nums text-foreground">
                  {formatFullMoney(stats.currentValue)}
                </p>
              </div>
              {/* Change Badge */}
              <div
                className={cn(
                  "flex items-center gap-1 rounded-full px-3 py-1.5",
                  stats.isProfit
                    ? "bg-[hsl(var(--profit))]/10 text-[hsl(var(--profit))]"
                    : "bg-[hsl(var(--loss))]/10 text-[hsl(var(--loss))]"
                )}
              >
                {stats.isProfit ? (
                  <TrendingUp className="h-4 w-4" />
                ) : (
                  <TrendingDown className="h-4 w-4" />
                )}
                <span className="text-sm font-semibold tabular-nums">
                  {stats.isProfit ? "+" : ""}
                  {stats.changePercent.toFixed(2)}%
                </span>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div style={{ height: 280 }} className="px-2 py-4">
            {equityCurve.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={equityCurve}
                  margin={{ top: 10, right: 20, left: 10, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="assetGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="5%"
                        stopColor={stats.isProfit ? "hsl(142, 76%, 46%)" : "hsl(0, 84%, 60%)"}
                        stopOpacity={0.3}
                      />
                      <stop
                        offset="95%"
                        stopColor={stats.isProfit ? "hsl(142, 76%, 46%)" : "hsl(0, 84%, 60%)"}
                        stopOpacity={0}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={CHART_STYLES.grid}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="date"
                    tick={CHART_STYLES.tick}
                    interval={xAxisInterval}
                    tickLine={false}
                    axisLine={{ stroke: CHART_STYLES.grid }}
                  />
                  <YAxis
                    tick={CHART_STYLES.tick}
                    tickFormatter={formatMoney}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                    domain={[minValue, maxValue]}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine
                    y={initialCapital}
                    stroke="hsl(215, 14%, 35%)"
                    strokeDasharray="5 5"
                    strokeWidth={1}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke={stats.isProfit ? "hsl(142, 76%, 46%)" : "hsl(0, 84%, 60%)"}
                    strokeWidth={2}
                    fill="url(#assetGradient)"
                    dot={false}
                    activeDot={{
                      r: 4,
                      fill: stats.isProfit ? "hsl(142, 76%, 46%)" : "hsl(0, 84%, 60%)",
                      stroke: "hsl(var(--background))",
                      strokeWidth: 2,
                    }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
                <Activity className="mb-2 h-8 w-8 animate-pulse" />
                <p className="text-sm">等待回测数据...</p>
                <p className="mt-1 text-xs">资产曲线将在回测开始后��示</p>
              </div>
            )}
          </div>
          {/* Legend */}
          <div className="flex items-center justify-center gap-6 border-t border-border px-4 py-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <span
                className={cn(
                  "inline-block h-[2px] w-5",
                  stats.isProfit ? "bg-[hsl(var(--profit))]" : "bg-[hsl(var(--loss))]"
                )}
              />
              <span>资产曲线</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className="inline-block w-5 border-t-2 border-dashed"
                style={{ borderColor: "hsl(215, 14%, 35%)" }}
              />
              <span>初始资金 ({formatMoney(initialCapital)})</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Trade Records Card */}
      <Card>
        <CardHeader className="py-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Calendar className="h-4 w-4 text-primary" />
              交易记录
              {tradeRecords.length > 0 && (
                <Badge variant="secondary" className="text-[10px]">
                  {tradeRecords.length} 笔
                </Badge>
              )}
            </CardTitle>
            {isRunning && (
              <Badge variant="outline" className="animate-pulse text-[10px]">
                实时更新中
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-52">
            <div ref={scrollRef} className="space-y-1 pr-4">
              {tradeRecords.length > 0 ? (
                tradeRecords.map((record, idx) => (
                  <div
                    key={idx}
                    className={cn(
                      "group flex items-center gap-3 rounded-lg border px-3 py-2 transition-colors",
                      record.action === "BUY"
                        ? "border-[hsl(var(--loss))]/20 bg-[hsl(var(--loss))]/5 hover:bg-[hsl(var(--loss))]/10"
                        : record.action === "SELL"
                        ? "border-[hsl(var(--profit))]/20 bg-[hsl(var(--profit))]/5 hover:bg-[hsl(var(--profit))]/10"
                        : "border-border bg-card hover:bg-secondary/50"
                    )}
                  >
                    {/* Action Icon */}
                    <div
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                        record.action === "BUY"
                          ? "bg-[hsl(var(--loss))]/20 text-[hsl(var(--loss))]"
                          : record.action === "SELL"
                          ? "bg-[hsl(var(--profit))]/20 text-[hsl(var(--profit))]"
                          : "bg-muted text-muted-foreground"
                      )}
                    >
                      {record.action === "BUY" ? (
                        <ArrowDownRight className="h-4 w-4" />
                      ) : record.action === "SELL" ? (
                        <ArrowUpRight className="h-4 w-4" />
                      ) : (
                        <Minus className="h-4 w-4" />
                      )}
                    </div>

                    {/* Trade Info */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-foreground">
                          {record.action === "BUY"
                            ? "买入"
                            : record.action === "SELL"
                            ? "卖出"
                            : "持有"}
                        </span>
                        {record.code && (
                          <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-foreground">
                            {record.code}
                          </span>
                        )}
                        {record.shares && (
                          <span className="text-[10px] text-muted-foreground">
                            {record.shares.toLocaleString()} 股
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                        <span>{record.date}</span>
                        {record.price && <span>@ ¥{record.price.toFixed(2)}</span>}
                        {record.amount && (
                          <span>金额: {formatFullMoney(record.amount)}</span>
                        )}
                      </div>
                    </div>

                    {/* Asset & Change */}
                    <div className="shrink-0 text-right">
                      <div className="flex items-center justify-end gap-1 text-xs text-foreground">
                        <DollarSign className="h-3 w-3 text-muted-foreground" />
                        <span className="font-mono">{formatMoney(record.asset)}</span>
                      </div>
                      {record.change !== undefined && (
                        <span
                          className={cn(
                            "text-[10px] font-medium",
                            record.change >= 0
                              ? "text-[hsl(var(--profit))]"
                              : "text-[hsl(var(--loss))]"
                          )}
                        >
                          {record.change >= 0 ? "+" : ""}
                          {formatFullMoney(record.change)}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex h-40 flex-col items-center justify-center text-muted-foreground">
                  <Calendar className="mb-2 h-6 w-6" />
                  <p className="text-xs">暂无交易记录</p>
                  <p className="mt-1 text-[10px]">交易记录将在回测开始后显示</p>
                </div>
              )}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Daily Log Summary - condensed version */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-chart-3" />
            运行日志
            {logs.length > 0 && (
              <Badge variant="secondary" className="text-[10px]">
                {logs.length} 条
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-32 rounded-md bg-background p-3">
            {logs.length > 0 ? (
              <div className="space-y-0.5 font-mono text-xs">
                {logs.slice(-50).map((log, idx) => (
                  <div key={idx} className="flex gap-2">
                    <span className="shrink-0 text-muted-foreground">
                      {formatDate(log.ts).slice(11, 19) || log.ts.slice(11, 19)}
                    </span>
                    <span className="text-foreground">{log.message}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-muted-foreground">
                <p className="text-xs">
                  {isRunning ? "等待日志输出..." : "暂无日志"}
                </p>
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
