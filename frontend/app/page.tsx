"use client";

import { BacktestForm } from "@/components/backtest/backtest-form";
import { useConfig } from "@/lib/hooks";
import { Loader2 } from "lucide-react";

// Default configs that match the Python backend's configs.json
const DEFAULT_SELECTORS = [
  {
    class: "BBIKDJSelector",
    alias: "少妇战法",
    activate: true,
    params: {
      j_threshold: 15,
      bbi_min_window: 20,
      max_window: 120,
      price_range_pct: 1,
      bbi_q_threshold: 0.2,
      j_q_threshold: 0.1,
    },
  },
  {
    class: "SuperB1Selector",
    alias: "SuperB1战法",
    activate: true,
    params: {
      lookback_n: 10,
      close_vol_pct: 0.02,
      price_drop_pct: 0.02,
      j_threshold: 10,
      j_q_threshold: 0.1,
    },
  },
  {
    class: "BBIShortLongSelector",
    alias: "补票战法",
    activate: true,
    params: {
      n_short: 5,
      n_long: 21,
      m: 5,
      bbi_min_window: 2,
      max_window: 120,
      bbi_q_threshold: 0.2,
      upper_rsv_threshold: 75,
      lower_rsv_threshold: 25,
    },
  },
  {
    class: "PeakKDJSelector",
    alias: "填坑战法",
    activate: true,
    params: {
      j_threshold: 10,
      max_window: 120,
      fluc_threshold: 0.03,
      j_q_threshold: 0.1,
      gap_threshold: 0.2,
    },
  },
  {
    class: "MA60CrossVolumeWaveSelector",
    alias: "上穿60放量战法",
    activate: true,
    params: {
      lookback_n: 25,
      vol_multiple: 1.8,
      j_threshold: 15,
      j_q_threshold: 0.1,
      ma60_slope_days: 5,
      max_window: 120,
    },
  },
  {
    class: "BigBullishVolumeSelector",
    alias: "暴力K战法",
    activate: true,
    params: {
      up_pct_threshold: 0.06,
      upper_wick_pct_max: 0.02,
      require_bullish_close: true,
      close_lt_zxdq_mult: 1.15,
      vol_lookback_n: 20,
      vol_multiple: 2.5,
    },
  },
];

const DEFAULT_SELL_STRATEGIES: Record<string, { description: string; name: string; combination_logic: string; strategies: Array<{ class: string; params: Record<string, unknown> }> }> = {
  conservative_trailing: {
    description: "Conservative risk management",
    name: "conservative_trailing",
    combination_logic: "ANY",
    strategies: [
      { class: "PercentageTrailingStopStrategy", params: { trailing_pct: 0.08, activate_after_profit_pct: 0.0 } },
      { class: "FixedProfitTargetStrategy", params: { target_pct: 0.15 } },
      { class: "TimedExitStrategy", params: { max_holding_days: 60 } },
    ],
  },
  aggressive_atr: {
    description: "Aggressive ATR-based trailing",
    name: "aggressive_atr",
    combination_logic: "ANY",
    strategies: [
      { class: "ATRTrailingStopStrategy", params: { atr_period: 14, atr_multiplier: 2.0 } },
      { class: "FixedProfitTargetStrategy", params: { target_pct: 0.2 } },
      { class: "TimedExitStrategy", params: { max_holding_days: 45 } },
    ],
  },
  indicator_based: {
    description: "Technical indicator-based exits",
    name: "indicator_based",
    combination_logic: "ANY",
    strategies: [
      { class: "KDJOverboughtExitStrategy", params: { j_threshold: 85, wait_for_turndown: true } },
      { class: "BBIReversalExitStrategy", params: { consecutive_declines: 3 } },
      { class: "PercentageTrailingStopStrategy", params: { trailing_pct: 0.1 } },
      { class: "TimedExitStrategy", params: { max_holding_days: 60 } },
    ],
  },
  adaptive_volatility: {
    description: "Adaptive stop based on volatility",
    name: "adaptive_volatility",
    combination_logic: "ANY",
    strategies: [
      { class: "AdaptiveVolatilityExitStrategy", params: { volatility_period: 20, lookback_period: 120, low_vol_percentile: 30, high_vol_percentile: 70, low_vol_stop_pct: 0.05, normal_vol_stop_pct: 0.08, high_vol_stop_pct: 0.12 } },
      { class: "FixedProfitTargetStrategy", params: { target_pct: 0.15 } },
      { class: "TimedExitStrategy", params: { max_holding_days: 60 } },
    ],
  },
  chandelier_3r: {
    description: "Chandelier stop with 3R profit target",
    name: "chandelier_3r",
    combination_logic: "ANY",
    strategies: [
      { class: "ChandelierStopStrategy", params: { lookback_period: 22, atr_period: 14, atr_multiplier: 3.0 } },
      { class: "MultipleRExitStrategy", params: { r_multiple: 3.0, atr_period: 14, stop_multiplier: 2.0 } },
      { class: "TimedExitStrategy", params: { max_holding_days: 60 } },
    ],
  },
  zx_discipline: {
    description: "Exit based on ZX lines breach",
    name: "zx_discipline",
    combination_logic: "ANY",
    strategies: [
      { class: "ZXLinesCrossDownExitStrategy", params: {} },
      { class: "MADeathCrossExitStrategy", params: { fast_period: 5, slow_period: 20 } },
      { class: "PercentageTrailingStopStrategy", params: { trailing_pct: 0.08 } },
      { class: "TimedExitStrategy", params: { max_holding_days: 60 } },
    ],
  },
  simple_percentage_stop: {
    description: "Simple baseline comparison",
    name: "simple_percentage_stop",
    combination_logic: "ANY",
    strategies: [
      { class: "PercentageTrailingStopStrategy", params: { trailing_pct: 0.08 } },
      { class: "TimedExitStrategy", params: { max_holding_days: 60 } },
    ],
  },
};

export default function HomePage() {
  const { data } = useConfig();

  const selectors = data?.selectors || DEFAULT_SELECTORS;
  const sellStrategies = data?.sell_strategies || DEFAULT_SELL_STRATEGIES;

  return (
    <div className="p-6">
      <BacktestForm
        selectors={selectors}
        sellStrategies={sellStrategies}
      />
    </div>
  );
}
