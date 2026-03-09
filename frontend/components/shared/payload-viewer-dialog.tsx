"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SlidersHorizontal, CheckCircle2, Circle } from "lucide-react";
import type { BacktestPayload } from "@/lib/api";

// ── 选股器中文名映射 ──────────────────────────────────────────────────────
const SELECTOR_NAMES: Record<string, string> = {
  BBIKDJSelector: "少妇战法",
  SuperB1Selector: "SuperB1战法",
  BBIShortLongSelector: "补票战法",
  PeakKDJSelector: "填坑战法",
  MA60CrossVolumeWaveSelector: "上穿60放量战法",
  BigBullishVolumeSelector: "暴力K战法",
};

// ── 参数中文名映射 ────────────────────────────────────────────────────────
const PARAM_LABELS: Record<string, string> = {
  j_threshold: "J值阈值",
  j_q_threshold: "J分位阈值",
  bbi_min_window: "BBI最小窗口",
  max_window: "最大窗口",
  price_range_pct: "价格波动幅度",
  bbi_q_threshold: "BBI回撤比例",
  lookback_n: "回溯天数",
  close_vol_pct: "收盘波动率",
  price_drop_pct: "跌幅阈值",
  n_short: "短RSV周期",
  n_long: "长RSV周期",
  m: "RSV检测天数",
  upper_rsv_threshold: "RSV上阈值",
  lower_rsv_threshold: "RSV下阈值",
  fluc_threshold: "偏离度阈值",
  gap_threshold: "峰谷落差阈值",
  up_pct_threshold: "涨幅门槛",
  upper_wick_pct_max: "上影线限制",
  vol_lookback_n: "均量计算天数",
  vol_multiple: "放量倍数",
  require_bullish_close: "要求阳线",
  close_lt_zxdq_mult: "知行线乖离率",
  ma60_slope_days: "MA60斜率天数",
  // ── 卖出策略参数 ──
  trailing_pct: "移动止损比例",
  activate_after_profit_pct: "激活盈利阈值",
  target_pct: "止盈目标",
  stop_pct: "止损比例",
  max_holding_days: "最大持仓天数",
  atr_period: "ATR周期",
  atr_multiplier: "ATR倍数",
  lookback_period: "回溯周期",
  volume_threshold_pct: "成交量阈值",
  consecutive_days: "连续震荡天数",
  daily_upper: "震荡上限",
  r_multiple: "R倍数",
  stop_multiplier: "止损倍数",
  wait_for_turndown: "等待掉头确认",
  use_percentile: "使用分位数模式",
  consecutive_declines: "连续下跌天数",
  fast_period: "快线周期",
  slow_period: "慢线周期",
  volatility_period: "波动率计算周期",
  low_vol_percentile: "低波动分位",
  high_vol_percentile: "高波动分位",
  low_vol_stop_pct: "低波动止损",
  normal_vol_stop_pct: "正常波动止损",
  high_vol_stop_pct: "高波动止损",
};

const SELL_CLASS_LABELS: Record<string, string> = {
  // 移动止损
  PercentageTrailingStopStrategy: "百分比移动止损",
  ATRTrailingStopStrategy: "ATR移动止损",
  ChandelierStopStrategy: "吊灯止损",
  // 止盈
  FixedProfitTargetStrategy: "固定止盈",
  MultipleRExitStrategy: "R倍数止盈",
  // 时间平仓
  TimedExitStrategy: "强制时间平仓",
  // 指标退场
  KDJOverboughtExitStrategy: "KDJ超买退场",
  BBIReversalExitStrategy: "BBI反转退场",
  ZXLinesCrossDownExitStrategy: "知行线死叉",
  MADeathCrossExitStrategy: "均线死叉",
  VolumeDryUpExitStrategy: "成交量枯竭退场",
  AdaptiveVolatilityExitStrategy: "自适应波动率止损",
  // 早期退出
  EarlyExitStrategy: "早期震荡退出",
  // 永不卖出
  SimpleHoldStrategy: "永不卖出 (买入持有)",
};

// ── 小工具组件 ────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h4>
      <div className="rounded-lg border border-border bg-secondary/30 p-3">
        {children}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground text-right">{value}</span>
    </div>
  );
}

function Divider() {
  return <div className="my-1 border-t border-border/50" />;
}

// ── 主组件 ────────────────────────────────────────────────────────────────

interface PayloadViewerDialogProps {
  payload: BacktestPayload | null;
  /** 按钮尺寸，默认 sm */
  size?: "sm" | "default";
}

export function PayloadViewerDialog({ payload, size = "sm" }: PayloadViewerDialogProps) {
  const [open, setOpen] = useState(false);

  if (!payload) return null;

  // ── 解析 buy_config ────────────────────────────────────────────────
  const buyConfig = payload.buy_config as {
    selectors?: Array<{ class: string; alias: string; activate: boolean; params: Record<string, unknown> }>;
    selector_combination?: {
      mode: string;
      time_window_days?: number;
      trigger_selectors?: string[];
      trigger_logic?: string;
      confirm_selectors?: string[];
      confirm_logic?: string;
      buy_timing?: string;
    };
  } | undefined;

  const selectors = buyConfig?.selectors ?? [];
  const activeSelectors = selectors.filter((s) => s.activate);
  const combination = buyConfig?.selector_combination;

  // ── 解析 sell_strategy_name ────────────────────────────────────────
  const sellStrategyName = payload.sell_strategy_name ?? "—";

  const combinationModeLabel: Record<string, string> = {
    OR: "任一满足 (OR)",
    AND: "全部满足 (AND)",
    SEQUENTIAL_CONFIRMATION: "信号组合（先触发后确认）",
    TIME_WINDOW: "时间窗口",
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size={size} className="gap-1.5">
          <SlidersHorizontal className="h-3.5 w-3.5" />
          任务配置
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            回测配置参数
          </DialogTitle>
        </DialogHeader>

        <ScrollArea className="max-h-[70vh] pr-3">
          <div className="space-y-4 pb-2">

            {/* ── 基础配置 ─────────────────────────────────────── */}
            <Section title="基础配置">
              <Row label="回测区间" value={`${payload.start_date} ~ ${payload.end_date}`} />
              <Divider />
              <Row label="初始资金" value={`¥ ${(payload.initial_capital ?? 0).toLocaleString()}`} />
              <Row label="最大持仓数" value={payload.max_positions ?? "—"} />
              <Row
                label="仓位分配方式"
                value={payload.position_sizing === "equal_weight" ? "等权分配" : "基于风险 (ATR)"}
              />
              <Row label="股票池" value={
                payload.stock_pool?.type === "all"
                  ? "全量股票"
                  : `自定义（${payload.stock_pool?.codes?.length ?? 0} 只）`
              } />
              <Divider />
              <Row label="佣金费率" value={`${((payload.commission_rate ?? 0) * 100).toFixed(4)}%`} />
              <Row label="印花税率" value={`${((payload.stamp_tax_rate ?? 0) * 100).toFixed(4)}%`} />
              <Row label="滑点费率" value={`${((payload.slippage_rate ?? 0) * 100).toFixed(4)}%`} />
              <Row label="数据回溯天数" value={payload.lookback_days ?? "—"} />
            </Section>

            {/* ── 选股策略 ─────────────────────────────────────── */}
            <Section title="选股策略">
              <Row
                label="信号组合方式"
                value={combinationModeLabel[combination?.mode ?? "OR"] ?? combination?.mode ?? "OR"}
              />
              {combination?.mode === "SEQUENTIAL_CONFIRMATION" && (
                <>
                  <Row label="时间窗口" value={`${combination.time_window_days ?? 5} 天`} />
                  <Row label="触发逻辑" value={combination.trigger_logic ?? "OR"} />
                  <Row label="确认逻辑" value={combination.confirm_logic ?? "OR"} />
                  <Row label="买入时机" value={
                    combination.buy_timing === "trigger_day" ? "触发信号当天" : "确认信号当天"
                  } />
                </>
              )}
              {combination?.mode === "TIME_WINDOW" && (
                <Row label="时间窗口" value={`${combination.time_window_days ?? 5} 天`} />
              )}

              <Divider />

              {selectors.length === 0 ? (
                <p className="text-xs text-muted-foreground">无选股器配置</p>
              ) : (
                <div className="space-y-3">
                  {selectors.map((sel) => (
                    <div key={sel.class}>
                      <div className="flex items-center gap-2 mb-1.5">
                        {sel.activate ? (
                          <CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--profit))] shrink-0" />
                        ) : (
                          <Circle className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        )}
                        <span className={`text-sm font-medium ${sel.activate ? "text-foreground" : "text-muted-foreground line-through"}`}>
                          {SELECTOR_NAMES[sel.class] ?? sel.alias}
                        </span>
                        <Badge variant="secondary" className="text-[10px] ml-auto">
                          {sel.class}
                        </Badge>
                      </div>
                      {sel.activate && Object.keys(sel.params).length > 0 && (
                        <div className="ml-5 grid grid-cols-2 gap-x-4 gap-y-0.5">
                          {Object.entries(sel.params)
                            .filter(([k]) => k !== "B1_params")
                            .map(([k, v]) => (
                              <div key={k} className="flex items-center justify-between text-xs py-0.5">
                                <span className="text-muted-foreground">{PARAM_LABELS[k] ?? k}</span>
                                <span className="font-mono text-foreground">{String(v)}</span>
                              </div>
                            ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Section>

            {/* ── 卖出策略 ─────────────────────────────────────── */}
            <Section title="卖出策略">
              <Row label="策略名称" value={sellStrategyName} />
              {/* sell_strategy_config 如果有结构化内容则展示子策略 */}
              {(() => {
                const cfg = payload.sell_strategy_config as {
                  combination_logic?: string;
                  strategies?: Array<{ class: string; params: Record<string, unknown> }>;
                  class?: string;
                  params?: Record<string, unknown>;
                } | undefined;
                if (!cfg) return (
                  <p className="mt-1 text-xs text-muted-foreground italic">
                    详细参数未记录（此任务创建于旧版本）
                  </p>
                );
                if (cfg.strategies) {
                  return (
                    <div className="mt-2 space-y-2">
                      <p className="text-xs text-muted-foreground">
                        组合逻辑：{cfg.combination_logic === "ANY" ? "任一触发 (OR)" : "全部触发 (AND)"}
                      </p>
                      {cfg.strategies.map((sub, i) => (
                        <div key={i} className="rounded-md bg-background p-2 border border-border">
                          <p className="text-xs font-medium mb-1">
                            {SELL_CLASS_LABELS[sub.class] ?? sub.class}
                          </p>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                            {Object.entries(sub.params ?? {}).map(([k, v]) => (
                              <div key={k} className="flex items-center justify-between text-xs py-0.5">
                                <span className="text-muted-foreground">{PARAM_LABELS[k] ?? k}</span>
                                <span className="font-mono text-foreground">{String(v)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  );
                }
                if (cfg.class) {
                  return (
                    <div className="mt-2 rounded-md bg-background p-2 border border-border">
                      <p className="text-xs font-medium mb-1">
                        {SELL_CLASS_LABELS[cfg.class] ?? cfg.class}
                      </p>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                        {Object.entries(cfg.params ?? {}).map(([k, v]) => (
                          <div key={k} className="flex items-center justify-between text-xs py-0.5">
                            <span className="text-muted-foreground">{PARAM_LABELS[k] ?? k}</span>
                            <span className="font-mono text-foreground">{String(v)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                }
                return null;
              })()}
            </Section>

            {/* ── Score 过滤 ────────────────────────────────────── */}
            <Section title="信号质量过滤 (Score Filter)">
              <Row
                label="状态"
                value={
                  <span className={payload.score_filter_enabled ? "text-[hsl(var(--profit))] font-semibold" : "text-muted-foreground"}>
                    {payload.score_filter_enabled ? "已启用" : "未启用"}
                  </span>
                }
              />
              {payload.score_filter_enabled && (
                <>
                  <Divider />
                  <Row label="百分位阈值" value={`${payload.score_percentile_threshold ?? 60}%`} />
                  <Row label="最低样本数" value={payload.score_min_history ?? 20} />
                  <Row label="预热天数" value={payload.score_warmup_lookback_days ?? 20} />
                </>
              )}
            </Section>

            {/* ── 换仓 ─────────────────────────────────────────── */}
            <Section title="主动换仓 (Rotation)">
              <Row
                label="状态"
                value={
                  <span className={payload.rotation_enabled ? "text-[hsl(var(--profit))] font-semibold" : "text-muted-foreground"}>
                    {payload.rotation_enabled ? "已启用" : "未启用"}
                  </span>
                }
              />
              {payload.rotation_enabled && (
                <>
                  <Divider />
                  <Row label="触发最低亏损" value={`${((payload.rotation_min_loss ?? 0.05) * 100).toFixed(1)}%`} />
                  <Row label="每日最大换仓数" value={payload.rotation_max_per_day ?? 2} />
                  <Row label="Score 倍数门槛" value={`${payload.rotation_score_ratio ?? 1.2}×`} />
                  <Row label="最低 Score 提升" value={`${payload.rotation_min_score_improvement ?? 10} pts`} />
                  <Row label="无评分仓位策略" value={payload.rotation_no_score_policy ?? "skip"} />
                </>
              )}
            </Section>

          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}