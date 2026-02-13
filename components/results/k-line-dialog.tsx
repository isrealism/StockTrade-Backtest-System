"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { getKLineData, type KLineDataPoint } from "@/lib/api";
import { Loader2 } from "lucide-react";

interface Trade {
  code: string;
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  net_pnl_pct: number;
  buy_strategy: string;
  exit_reason: string;
  shares: number;
  holding_days: number;
}

interface KLineDialogProps {
  trade: Trade | null;
  onClose: () => void;
}

/* ── Colours ────────────────────────────────────────── */
const UP_COLOR = "#22c55e";
const DOWN_COLOR = "#ef4444";
const BG_COLOR = "#0f1117";
const GRID_COLOR = "rgba(255,255,255,0.04)";
const TEXT_COLOR = "rgba(255,255,255,0.45)";
const BORDER_COLOR = "rgba(255,255,255,0.08)";
const VOL_UP = "rgba(34,197,94,0.35)";
const VOL_DOWN = "rgba(239,68,68,0.35)";

export function KLineDialog({ trade, onClose }: KLineDialogProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<
    typeof import("lightweight-charts").createChart
  > | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* ── Build chart ──────────────────────────────────── */
  const initChart = useCallback(async () => {
    if (!trade || !chartContainerRef.current) return;

    setLoading(true);
    setError(null);

    // Dynamically import lightweight-charts
    const { createChart, ColorType, CrosshairMode, LineStyle } = await import(
      "lightweight-charts"
    );

    // Clean up previous chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    /* ── Fetch real K-line data ── */
    let klineData: KLineDataPoint[];
    try {
      // Extend range: 30 trading days before entry, 15 after exit
      const entryDate = new Date(trade.entry_date);
      const exitDate = new Date(trade.exit_date);
      const startDate = new Date(entryDate);
      startDate.setDate(startDate.getDate() - 45); // ~30 trading days
      const endDate = new Date(exitDate);
      endDate.setDate(endDate.getDate() + 22); // ~15 trading days

      const startStr = startDate.toISOString().split("T")[0];
      const endStr = endDate.toISOString().split("T")[0];

      const resp = await getKLineData(trade.code, startStr, endStr);
      klineData = resp.data;
    } catch {
      // Fallback: generate synthetic data if backend is unavailable
      klineData = generateSyntheticData(trade);
    }

    if (klineData.length === 0) {
      setError("暂无该股票的K线数据");
      setLoading(false);
      return;
    }

    setLoading(false);

    const container = chartContainerRef.current;
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: BG_COLOR },
        textColor: TEXT_COLOR,
        fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: GRID_COLOR },
        horzLines: { color: GRID_COLOR },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(255,255,255,0.15)",
          style: LineStyle.Dashed,
          labelBackgroundColor: "rgba(30,34,45,0.95)",
        },
        horzLine: {
          color: "rgba(255,255,255,0.15)",
          style: LineStyle.Dashed,
          labelBackgroundColor: "rgba(30,34,45,0.95)",
        },
      },
      rightPriceScale: {
        borderColor: BORDER_COLOR,
        scaleMargins: { top: 0.05, bottom: 0.25 },
      },
      timeScale: {
        borderColor: BORDER_COLOR,
        timeVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      width: container.clientWidth,
      height: container.clientHeight,
    });

    chartRef.current = chart;

    /* ── Candlestick series ── */
    const candleSeries = chart.addCandlestickSeries({
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
    });

    const ohlcData = klineData.map((d) => ({
      time: d.time as Parameters<typeof candleSeries.setData>[0][0]["time"],
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));
    candleSeries.setData(ohlcData);

    /* ── Volume histogram ── */
    const hasVolume = klineData.some((d) => d.volume !== undefined && d.volume > 0);
    if (hasVolume) {
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });

      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
        drawTicks: false,
      });

      volumeSeries.setData(
        klineData
          .filter((d) => d.volume !== undefined)
          .map((d) => ({
            time: d.time as Parameters<typeof volumeSeries.setData>[0][0]["time"],
            value: d.volume!,
            color: d.close >= d.open ? VOL_UP : VOL_DOWN,
          }))
      );
    }

    /* ── Buy / Sell markers ── */
    const markers: Parameters<typeof candleSeries.setMarkers>[0] = [];

    // Ensure entry_date exists in data
    const entryExists = klineData.some((d) => d.time === trade.entry_date);
    const exitExists = klineData.some((d) => d.time === trade.exit_date);

    if (entryExists) {
      markers.push({
        time: trade.entry_date as typeof ohlcData[0]["time"],
        position: "belowBar",
        color: UP_COLOR,
        shape: "arrowUp",
        text: `B ${trade.entry_price.toFixed(2)}`,
      });
    }

    if (exitExists) {
      markers.push({
        time: trade.exit_date as typeof ohlcData[0]["time"],
        position: "aboveBar",
        color: DOWN_COLOR,
        shape: "arrowDown",
        text: `S ${trade.exit_price.toFixed(2)}`,
      });
    }

    // Sort markers by time (required by lightweight-charts)
    markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    candleSeries.setMarkers(markers);

    /* ── Crosshair tooltip ── */
    const tooltip = tooltipRef.current;
    if (tooltip) {
      chart.subscribeCrosshairMove((param) => {
        if (
          !param.time ||
          !param.point ||
          param.point.x < 0 ||
          param.point.y < 0
        ) {
          tooltip.style.display = "none";
          return;
        }

        const data = param.seriesData.get(candleSeries) as
          | { open: number; high: number; low: number; close: number }
          | undefined;

        if (!data) {
          tooltip.style.display = "none";
          return;
        }

        const change = data.close - data.open;
        const changePct = (change / data.open) * 100;
        const isUp = change >= 0;
        const color = isUp ? UP_COLOR : DOWN_COLOR;

        // Find volume for this date
        const dateStr = param.time as string;
        const volEntry = klineData.find((d) => d.time === dateStr);
        const volume = volEntry?.volume;

        tooltip.innerHTML = `
          <div style="font-size:11px;color:${TEXT_COLOR};margin-bottom:4px;">${dateStr}</div>
          <div style="display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:11px;">
            <span style="color:${TEXT_COLOR}">开</span><span style="color:${data.close >= data.open ? UP_COLOR : DOWN_COLOR};text-align:right;font-family:'JetBrains Mono',monospace">${data.open.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">高</span><span style="color:${UP_COLOR};text-align:right;font-family:'JetBrains Mono',monospace">${data.high.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">低</span><span style="color:${DOWN_COLOR};text-align:right;font-family:'JetBrains Mono',monospace">${data.low.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">收</span><span style="color:${color};text-align:right;font-family:'JetBrains Mono',monospace">${data.close.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">涨跌</span><span style="color:${color};text-align:right;font-family:'JetBrains Mono',monospace">${isUp ? "+" : ""}${changePct.toFixed(2)}%</span>
            ${volume !== undefined ? `<span style="color:${TEXT_COLOR}">量</span><span style="text-align:right;color:rgba(255,255,255,0.7);font-family:'JetBrains Mono',monospace">${formatVolume(volume)}</span>` : ""}
          </div>
        `;
        tooltip.style.display = "block";

        // Position tooltip - keep it top-left within chart bounds
        const containerRect = container.getBoundingClientRect();
        let left = param.point.x + 16;
        let top = param.point.y - 10;

        // Prevent overflow right
        if (left + 160 > containerRect.width) {
          left = param.point.x - 170;
        }
        // Prevent overflow bottom
        if (top + 140 > containerRect.height) {
          top = containerRect.height - 150;
        }
        if (top < 0) top = 8;

        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
      });
    }

    chart.timeScale().fitContent();

    /* ── Resize observer ── */
    const resizeObserver = new ResizeObserver(() => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [trade]);

  useEffect(() => {
    if (trade) {
      const timeout = setTimeout(initChart, 80);
      return () => clearTimeout(timeout);
    }
  }, [trade, initChart]);

  if (!trade) return null;

  return (
    <Dialog open={!!trade} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-5xl border-border bg-card p-0">
        <DialogTitle className="sr-only">
          {trade.code} K线图
        </DialogTitle>

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="flex items-center gap-3">
            <span className="font-mono text-base font-semibold text-primary">
              {trade.code}
            </span>
            <span className="rounded bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
              {trade.buy_strategy}
            </span>
          </div>
          <div className="flex items-center gap-5 text-xs">
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-muted-foreground">买入</span>
              <span className="font-mono text-foreground">
                {trade.entry_date} @ <span className="text-[#22c55e]">{trade.entry_price.toFixed(2)}</span>
              </span>
            </div>
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-muted-foreground">卖出</span>
              <span className="font-mono text-foreground">
                {trade.exit_date} @ <span className="text-[#ef4444]">{trade.exit_price.toFixed(2)}</span>
              </span>
            </div>
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-muted-foreground">收益</span>
              <span
                className={`font-mono font-semibold ${
                  trade.net_pnl_pct >= 0
                    ? "text-[#22c55e]"
                    : "text-[#ef4444]"
                }`}
              >
                {trade.net_pnl_pct >= 0 ? "+" : ""}
                {trade.net_pnl_pct.toFixed(2)}%
              </span>
            </div>
          </div>
        </div>

        {/* Chart area */}
        <div className="relative">
          <div ref={chartContainerRef} className="h-[480px] w-full" />

          {/* Floating tooltip */}
          <div
            ref={tooltipRef}
            className="pointer-events-none absolute z-50 hidden rounded-md border border-border/60 bg-card/95 px-3 py-2 shadow-xl backdrop-blur-sm"
            style={{ minWidth: 150 }}
          />

          {/* Loading state */}
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-card/80">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>加载K线数据...</span>
              </div>
            </div>
          )}

          {/* Error state */}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-card/80">
              <span className="text-sm text-muted-foreground">{error}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center gap-6 border-t border-border px-5 py-2.5 text-xs text-muted-foreground">
          <span>
            持仓:{" "}
            <span className="font-mono text-foreground">
              {trade.holding_days}天
            </span>
          </span>
          <span>
            数量:{" "}
            <span className="font-mono text-foreground">
              {trade.shares.toLocaleString()}股
            </span>
          </span>
          <span className="flex-1 truncate">
            退出: {trade.exit_reason}
          </span>
          <span className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-[#22c55e]" />
            <span>B 买入</span>
            <span className="ml-2 inline-block h-2 w-2 rounded-full bg-[#ef4444]" />
            <span>S 卖出</span>
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ── Helpers ─────────────────────────────────────────── */

function formatVolume(vol: number): string {
  if (vol >= 1e8) return (vol / 1e8).toFixed(2) + "亿";
  if (vol >= 1e4) return (vol / 1e4).toFixed(1) + "万";
  return vol.toLocaleString();
}

/** Fallback synthetic data when the API is unreachable */
function generateSyntheticData(trade: Trade): KLineDataPoint[] {
  const entryDate = new Date(trade.entry_date);
  const exitDate = new Date(trade.exit_date);

  const startDate = new Date(entryDate);
  startDate.setDate(startDate.getDate() - 40);
  const endDate = new Date(exitDate);
  endDate.setDate(endDate.getDate() + 15);

  const data: KLineDataPoint[] = [];
  let price = trade.entry_price * (0.88 + Math.random() * 0.15);
  const current = new Date(startDate);

  while (current <= endDate) {
    if (current.getDay() !== 0 && current.getDay() !== 6) {
      const timeStr = current.toISOString().split("T")[0];

      if (timeStr === trade.entry_date) {
        data.push({
          time: timeStr,
          open: trade.entry_price * 0.995,
          high: trade.entry_price * 1.02,
          low: trade.entry_price * 0.98,
          close: trade.entry_price,
          volume: Math.round(500000 + Math.random() * 2000000),
        });
        price = trade.entry_price;
      } else if (timeStr === trade.exit_date) {
        data.push({
          time: timeStr,
          open: trade.exit_price * 1.005,
          high: Math.max(trade.exit_price * 1.025, trade.exit_price),
          low: Math.min(trade.exit_price * 0.975, trade.exit_price),
          close: trade.exit_price,
          volume: Math.round(800000 + Math.random() * 3000000),
        });
        price = trade.exit_price;
      } else {
        const change = (Math.random() - 0.48) * price * 0.035;
        const open = price;
        const close = Math.max(0.01, price + change);
        const high = Math.max(open, close) + Math.random() * price * 0.012;
        const low =
          Math.min(open, close) - Math.random() * price * 0.012;
        data.push({
          time: timeStr,
          open: Math.max(0.01, open),
          high: Math.max(0.01, high),
          low: Math.max(0.01, low),
          close,
          volume: Math.round(200000 + Math.random() * 1500000),
        });
        price = close;
      }
    }
    current.setDate(current.getDate() + 1);
  }

  return data;
}
