"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight, Shield } from "lucide-react";
import { useState } from "react";

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  conservative_trailing: "保守型: 8%移动止损 + 15%止盈 + 60天强制平仓",
  aggressive_atr: "激进型: ATR移动止损 + 20%止盈 + 45天最大持仓",
  indicator_based: "指标型: KDJ超买 + BBI反转 + 10%移动止损",
  adaptive_volatility: "自适应: 根据波动率动态调整止损 + 15%止盈",
  chandelier_3r: "吊灯型: 3倍ATR吊灯止损 + 3R止盈",
  zx_discipline: "知行型: 知行线死叉 + MA死叉 + 8%移动止损",
  simple_percentage_stop: "简单型: 8%移动止损 + 60天最大持仓 (基线对比)",
  hold_forever: "永不卖出 (买入持有基线)",
};

const SELL_CLASS_LABELS: Record<string, string> = {
  PercentageTrailingStopStrategy: "百分比移动止损",
  ATRTrailingStopStrategy: "ATR移动止损",
  ChandelierStopStrategy: "吊灯止损",
  AdaptiveVolatilityExitStrategy: "自适应波动率止损",
  FixedProfitTargetStrategy: "固定止盈",
  MultipleRExitStrategy: "R倍数止盈",
  KDJOverboughtExitStrategy: "KDJ超买退场",
  BBIReversalExitStrategy: "BBI反转退场",
  ZXLinesCrossDownExitStrategy: "知行线死叉",
  MADeathCrossExitStrategy: "均线死叉",
  VolumeDryUpExitStrategy: "成交量枯竭",
  TimedExitStrategy: "强制时间平仓",
  SimpleHoldStrategy: "永不卖出",
};

const SELL_PARAM_LABELS: Record<string, string> = {
  trailing_pct: "止损比例",
  activate_after_profit_pct: "激活盈利阈值",
  target_pct: "止盈目标",
  atr_period: "ATR周期",
  atr_multiplier: "ATR倍数",
  lookback_period: "回溯周期",
  r_multiple: "R倍数",
  stop_multiplier: "止损倍数",
  j_threshold: "J值阈值",
  wait_for_turndown: "等待掉头",
  use_percentile: "使用分位数",
  j_q_threshold: "J分位阈值",
  consecutive_declines: "连续下跌天数",
  fast_period: "快线周期",
  slow_period: "慢线周期",
  volatility_period: "波动率周期",
  low_vol_percentile: "低波动分位",
  high_vol_percentile: "高波动分位",
  low_vol_stop_pct: "低波动止损",
  normal_vol_stop_pct: "正常止损",
  high_vol_stop_pct: "高波动止损",
  max_holding_days: "最大持仓天数",
  volume_threshold_pct: "枯竭阈值",
  consecutive_days: "连续天数",
};

interface SellStrategyConfigProps {
  strategies: Record<
    string,
    {
      description: string;
      name: string;
      combination_logic?: string;
      strategies?: Array<{
        class: string;
        params: Record<string, unknown>;
      }>;
    }
  >;
  selectedStrategy: string;
  onSelectStrategy: (name: string) => void;
  customParams: Record<string, Record<string, unknown>> | null;
  onCustomParamsChange: (
    params: Record<string, Record<string, unknown>>
  ) => void;
}

export function SellStrategyConfig({
  strategies,
  selectedStrategy,
  onSelectStrategy,
  customParams,
  onCustomParamsChange,
}: SellStrategyConfigProps) {
  const [expandedStrategy, setExpandedStrategy] = useState<string | null>(null);

  const strategyNames = Object.keys(strategies);
  const currentStrategy = strategies[selectedStrategy];

  function updateSubStrategyParam(
    subIdx: number,
    key: string,
    value: unknown
  ) {
    const subs = currentStrategy?.strategies || [];
    const currentSub = subs[subIdx];
    if (!currentSub) return;

    const newParams = { ...customParams };
    const subKey = `${selectedStrategy}__${subIdx}`;
    newParams[subKey] = {
      ...currentSub.params,
      ...(customParams?.[subKey] || {}),
      [key]: value,
    };
    onCustomParamsChange(newParams);
  }

  function getSubParam(subIdx: number, key: string, defaultValue: unknown) {
    const subKey = `${selectedStrategy}__${subIdx}`;
    return customParams?.[subKey]?.[key] ?? defaultValue;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" />
          卖出策略配置
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Strategy Selection */}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {strategyNames.map((name) => {
            const isSelected = name === selectedStrategy;
            return (
              <button
                key={name}
                onClick={() => onSelectStrategy(name)}
                className={cn(
                  "rounded-lg border p-3 text-left transition-all",
                  isSelected
                    ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                    : "border-border bg-background hover:border-muted-foreground/30"
                )}
              >
                <p className="text-sm font-medium text-foreground">{name}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {STRATEGY_DESCRIPTIONS[name] ||
                    strategies[name]?.description}
                </p>
              </button>
            );
          })}
        </div>

        {/* Sub-strategy details */}
        {currentStrategy?.strategies && currentStrategy.strategies.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-xs font-medium text-muted-foreground">
              组合逻辑: {currentStrategy.combination_logic === "ANY" ? "任一触发即卖出 (OR)" : "全部触发才卖出 (AND)"}
            </p>
            {currentStrategy.strategies.map((sub, idx) => {
              const isExpanded = expandedStrategy === `${selectedStrategy}__${idx}`;
              return (
                <div
                  key={idx}
                  className="rounded-md border border-border bg-background"
                >
                  <button
                    onClick={() =>
                      setExpandedStrategy(isExpanded ? null : `${selectedStrategy}__${idx}`)
                    }
                    className="flex w-full items-center gap-2 px-3 py-2 text-left"
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                    <span className="text-sm">
                      {SELL_CLASS_LABELS[sub.class] || sub.class}
                    </span>
                    <Badge variant="secondary" className="ml-auto text-[10px]">
                      {sub.class.replace("Strategy", "")}
                    </Badge>
                  </button>
                  {isExpanded && Object.keys(sub.params).length > 0 && (
                    <div className="border-t border-border px-3 py-2">
                      <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
                        {Object.entries(sub.params).map(([key, defaultVal]) => (
                          <div key={key} className="space-y-1">
                            <Label className="text-xs text-muted-foreground">
                              {SELL_PARAM_LABELS[key] || key}
                            </Label>
                            <Input
                              type="number"
                              value={String(getSubParam(idx, key, defaultVal))}
                              onChange={(e) =>
                                updateSubStrategyParam(
                                  idx,
                                  key,
                                  Number(e.target.value)
                                )
                              }
                              className="h-8 text-xs"
                              step={
                                typeof defaultVal === "number" && defaultVal < 1
                                  ? "0.01"
                                  : "1"
                              }
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
