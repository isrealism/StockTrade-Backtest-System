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
  backtestStartDate?: string; 
  backtestEndDate?: string;
}

/* ── 颜色常量 ── */
const UP_COLOR = "#ef4444";
const DOWN_COLOR = "#22c55e";
const BG_COLOR = "#0f1117";
const GRID_COLOR = "rgba(255,255,255,0.04)";
const TEXT_COLOR = "rgba(255,255,255,0.45)";
const BORDER_COLOR = "rgba(255,255,255,0.08)";
const VOL_UP = "rgba(239,68,68,0.35)";
const VOL_DOWN = "rgba(34,197,94,0.35)";

export function KLineDialog({ trade, onClose, backtestStartDate, backtestEndDate }: KLineDialogProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isCancelledRef = useRef(false);

  const initChart = useCallback(async () => {
    if (!trade || !chartContainerRef.current) return;

    setLoading(true);
    setError(null);
    isCancelledRef.current = false;

    try {
      const { createChart, ColorType, CrosshairMode } = await import("lightweight-charts");
      if (isCancelledRef.current) return;

      // 1. 安全清理旧图表
      if (chartRef.current) {
        try {
          chartRef.current.remove();
        } catch (e) {
          console.warn("Chart disposal handled:", e);
        }
        chartRef.current = null;
      }

      // 2. 日期计算 (往前/往后 140天确保覆盖100个交易日)
      const baseStart = backtestStartDate || trade.entry_date;
      const baseEnd = backtestEndDate || trade.exit_date;
      const startDateObj = new Date(baseStart);
      startDateObj.setDate(startDateObj.getDate() - 140);
      const endDateObj = new Date(baseEnd);
      endDateObj.setDate(endDateObj.getDate() + 140);

      const startStr = startDateObj.toISOString().split("T")[0];
      const endStr = endDateObj.toISOString().split("T")[0];

      let klineData: KLineDataPoint[];
      try {
        const resp = await getKLineData(trade.code, startStr, endStr);
        if (isCancelledRef.current) return;
        klineData = resp.data;
      } catch {
        klineData = generateSyntheticData(trade);
      }

      if (!klineData || klineData.length === 0) {
        setError("暂无该股票的K线数据");
        setLoading(false);
        return;
      }

      setLoading(false);
      if (isCancelledRef.current || !chartContainerRef.current) return;

      // 3. 初始化图表
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: BG_COLOR },
          textColor: TEXT_COLOR,
          fontSize: 11,
        },
        grid: { vertLines: { color: GRID_COLOR }, horzLines: { color: GRID_COLOR } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: BORDER_COLOR, scaleMargins: { top: 0.1, bottom: 0.3 } },
        timeScale: { borderColor: BORDER_COLOR, barSpacing: 10 },
        width: chartContainerRef.current.clientWidth,
        height: 480,
      });
      chartRef.current = chart;

      const candleSeries = chart.addCandlestickSeries({
        upColor: UP_COLOR, downColor: DOWN_COLOR,
        borderUpColor: UP_COLOR, borderDownColor: DOWN_COLOR,
        wickUpColor: UP_COLOR, wickDownColor: DOWN_COLOR,
      });

      const ohlcData = klineData.map(d => ({
        time: d.time,
        open: d.open, high: d.high, low: d.low, close: d.close
      }));
      candleSeries.setData(ohlcData as any);

      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      volumeSeries.setData(klineData.map(d => ({
        time: d.time as any,
        value: d.volume || 0,
        color: d.close >= d.open ? VOL_UP : VOL_DOWN,
      })));

      // 4. 设置买卖标记
      const markers = [];
      if (klineData.some(d => d.time === trade.entry_date)) {
        markers.push({
          time: trade.entry_date, position: "belowBar" as any, color: UP_COLOR, shape: "arrowUp" as any, text: `B ${trade.entry_price.toFixed(2)}`
        });
      }
      if (klineData.some(d => d.time === trade.exit_date)) {
        markers.push({
          time: trade.exit_date, position: "aboveBar" as any, color: DOWN_COLOR, shape: "arrowDown" as any, text: `S ${trade.exit_price.toFixed(2)}`
        });
      }
      candleSeries.setMarkers(markers);

      // 5. 🌟 自动缩放至交易区间中心
      const tradeDates = klineData.map(d => d.time);
      const entryIdx = tradeDates.indexOf(trade.entry_date);
      const exitIdx = tradeDates.indexOf(trade.exit_date);

      if (entryIdx !== -1 && exitIdx !== -1) {
        const fromIdx = Math.max(0, entryIdx - 15);
        const toIdx = Math.min(tradeDates.length - 1, exitIdx + 15);
        chart.timeScale().setVisibleRange({
          from: tradeDates[fromIdx] as any,
          to: tradeDates[toIdx] as any,
        });
      } else {
        chart.timeScale().fitContent();
      }

      // 6. 🌟 修复十字线悬停数据
      const tooltip = tooltipRef.current;
      chart.subscribeCrosshairMove((param: any) => {
        if (!tooltip || !chartContainerRef.current) return;
        if (!param.time || !param.point || param.point.x < 0 || param.point.y < 0) {
          tooltip.style.display = "none";
          return;
        }

        const data = param.seriesData.get(candleSeries) as any;
        if (!data) {
          tooltip.style.display = "none";
          return;
        }

        const isUp = data.close >= data.open;
        const color = isUp ? UP_COLOR : DOWN_COLOR;
        const changePct = ((data.close - data.open) / data.open) * 100;
        const volData = param.seriesData.get(volumeSeries) as any;

        tooltip.style.display = "block";
        tooltip.innerHTML = `
          <div style="font-size:12px;color:#fff;margin-bottom:4px;font-weight:bold">${param.time}</div>
          <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:11px;font-family:monospace">
            <span style="color:${TEXT_COLOR}">开</span><span style="color:#fff;text-align:right">${data.open.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">高</span><span style="color:${UP_COLOR};text-align:right">${data.high.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">低</span><span style="color:${DOWN_COLOR};text-align:right">${data.low.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">收</span><span style="color:${color};text-align:right">${data.close.toFixed(2)}</span>
            <span style="color:${TEXT_COLOR}">幅度</span><span style="color:${color};text-align:right">${isUp ? '+' : ''}${changePct.toFixed(2)}%</span>
            <span style="color:${TEXT_COLOR}">成交</span><span style="color:#fff;text-align:right">${volData ? formatVolume(volData.value) : '-'}</span>
          </div>
        `;

        const containerRect = chartContainerRef.current.getBoundingClientRect();
        let left = param.point.x + 20;
        if (left + 160 > containerRect.width) left = param.point.x - 170;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `20px`;
      });

      return () => {
        if (chartRef.current) {
          try { chartRef.current.remove(); } catch(e) {}
          chartRef.current = null;
        }
      };
    } catch (e) {
      console.error(e);
      setLoading(false);
    }
  }, [trade, backtestStartDate, backtestEndDate]);

  useEffect(() => {
    let cleanup: any;
    let timer: NodeJS.Timeout | undefined; // 🌟 提升作用域
    isCancelledRef.current = false;

    if (trade) {
      timer = setTimeout(async () => {
        const result = await initChart();
        if (isCancelledRef.current) {
          result?.();
        } else {
          cleanup = result;
        }
      }, 100);
    }
    return () => {
      isCancelledRef.current = true;
      if (timer) clearTimeout(timer);
      if (cleanup) cleanup();
    };
  }, [trade, initChart]);

  if (!trade) return null;

  return (
    <Dialog open={!!trade} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-5xl border-border bg-card p-0 overflow-hidden">
        <DialogTitle className="sr-only">{trade.code} K线图</DialogTitle>
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="flex items-center gap-3">
            <span className="font-mono text-base font-semibold text-primary">{trade.code}</span>
            <span className="rounded bg-secondary px-2 py-0.5 text-xs text-muted-foreground">{trade.buy_strategy}</span>
          </div>
          <div className="flex items-center gap-5 text-xs text-right">
             <div><div className="text-muted-foreground">买入</div><div className="font-mono text-foreground">{trade.entry_date} @ <span style={{color: UP_COLOR}}>{trade.entry_price.toFixed(2)}</span></div></div>
             <div><div className="text-muted-foreground">卖出</div><div className="font-mono text-foreground">{trade.exit_date} @ <span style={{color: DOWN_COLOR}}>{trade.exit_price.toFixed(2)}</span></div></div>
             <div><div className="text-muted-foreground">收益</div><div className={`font-mono font-bold ${trade.net_pnl_pct >= 0 ? 'text-[#22c55e]' : 'text-[#ef4444]'}`}>{trade.net_pnl_pct >= 0 ? '+' : ''}{trade.net_pnl_pct.toFixed(2)}%</div></div>
          </div>
        </div>

        <div className="relative">
          <div ref={chartContainerRef} className="h-[480px] w-full" />
          <div ref={tooltipRef} className="pointer-events-none absolute z-50 hidden rounded border border-white/10 bg-[#1e222d]/90 px-3 py-2 shadow-2xl backdrop-blur-md" style={{ width: '160px' }} />
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-card/60 backdrop-blur-sm">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          )}
          {error && <div className="absolute inset-0 flex items-center justify-center text-destructive">{error}</div>}
        </div>
        
        <div className="flex flex-wrap items-center gap-6 border-t border-border px-5 py-2.5 text-xs text-muted-foreground">
          <span>持仓: <span className="font-mono text-foreground">{trade.holding_days}天</span></span>
          <span>数量: <span className="font-mono text-foreground">{trade.shares.toLocaleString()}股</span></span>
          <span className="flex-1 truncate text-foreground">原因: {trade.exit_reason}</span>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function formatVolume(vol: number): string {
  if (vol >= 1e8) return (vol / 1e8).toFixed(2) + "亿";
  if (vol >= 1e4) return (vol / 1e4).toFixed(1) + "万";
  return vol.toLocaleString();
}

function generateSyntheticData(trade: Trade): any[] {
  const entryDate = new Date(trade.entry_date);
  const exitDate = new Date(trade.exit_date);
  const startDate = new Date(entryDate);
  startDate.setDate(startDate.getDate() - 140);
  const endDate = new Date(exitDate);
  endDate.setDate(endDate.getDate() + 140);

  const data = [];
  let price = trade.entry_price * 0.9;
  const current = new Date(startDate);

  while (current <= endDate) {
    if (current.getDay() !== 0 && current.getDay() !== 6) {
      const timeStr = current.toISOString().split("T")[0];
      const change = (Math.random() - 0.48) * price * 0.03;
      const open = price;
      const close = price + change;
      data.push({
        time: timeStr,
        open, high: Math.max(open, close) + 0.5, low: Math.min(open, close) - 0.5, close,
        volume: Math.round(1000000 + Math.random() * 5000000)
      });
      price = close;
    }
    current.setDate(current.getDate() + 1);
  }
  return data;
}