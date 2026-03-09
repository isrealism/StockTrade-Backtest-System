"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight, Shield } from "lucide-react";
import { cn } from "@/lib/utils";
import { NumericInput } from "@/lib/useNumberInput";

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  conservative_trailing: "保守移动止损，适合趋势行情",
  aggressive_trailing: "激进移动止损，快进快出",
  profit_target: "固定止盈，锁定收益",
  time_based: "时间平仓，防止资金占用",
};

const SELL_CLASS_LABELS: Record<string, string> = {
  PercentageTrailingStopStrategy: "百分比移动止损",
  FixedProfitTargetStrategy: "固定止盈",
  TimedExit: "时间平仓",
  ATRTrailingStop: "ATR 移动止损",
  ChandelierStop: "吊灯止损",
  AdaptiveVolatilityExit: "自适应波动率止损",
  VolumeDryUpExit: "成交量枯竭退场",
  MultipleRExitStrategy: "R 倍数止盈",
};

const SELL_PARAM_LABELS: Record<string, string> = {
  trailing_pct: "移动止损比例",
  target_pct: "止盈比例",
  stop_pct: "止损比例",
  max_holding_days: "最大持仓天数",
  atr_period: "ATR 周期",
  atr_multiplier: "ATR 倍数",
  lookback_period: "回溯周期",
  volume_threshold_pct: "成交量阈值",
  consecutive_days: "连续天数",
  r_multiple: "R 倍数",
  stop_multiplier: "止损倍数",
  volatility_period: "波动率周期",
  low_vol_percentile: "低波动分位",
  high_vol_percentile: "高波动分位",
  low_vol_stop_pct: "低波动止损",
  normal_vol_stop_pct: "正常波动止损",
  high_vol_stop_pct: "高波动止损",
};

interface SellStrategyConfigProps {
  strategies: Record<
    string,
    {
      description?: string;
      combination_logic?: string;
      params?: Record<string, unknown>;
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

  function updateSubStrategyParam(subIdx: number, key: string, value: unknown) {
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
                  {STRATEGY_DESCRIPTIONS[name] || strategies[name]?.description}
                </p>
              </button>
            );
          })}
        </div>

        {/* Sub-strategy details */}
        {currentStrategy?.strategies && currentStrategy.strategies.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-xs font-medium text-muted-foreground">
              组合逻辑:{" "}
              {currentStrategy.combination_logic === "ANY"
                ? "任一触发即卖出 (OR)"
                : "全部触发才卖出 (AND)"}
            </p>
            {currentStrategy.strategies.map((sub, idx) => {
              const isExpanded =
                expandedStrategy === `${selectedStrategy}__${idx}`;
              return (
                <div
                  key={idx}
                  className="rounded-md border border-border bg-background"
                >
                  <button
                    onClick={() =>
                      setExpandedStrategy(
                        isExpanded ? null : `${selectedStrategy}__${idx}`
                      )
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
                        {Object.entries(sub.params).map(([key, defaultVal]) => {
                          const currentVal = getSubParam(idx, key, defaultVal);
                          return (
                            <div key={key} className="space-y-1">
                              <Label className="text-xs text-muted-foreground">
                                {SELL_PARAM_LABELS[key] || key}
                              </Label>
                              {/* ✅ NumericInput 替换原来的 String() + Number() 写法 */}
                              <NumericInput
                                value={
                                  typeof currentVal === "number"
                                    ? currentVal
                                    : Number(currentVal)
                                }
                                onChange={(num) =>
                                  updateSubStrategyParam(idx, key, num)
                                }
                                step={
                                  typeof defaultVal === "number" && defaultVal < 1
                                    ? 0.01
                                    : 1
                                }
                                className="h-8 text-xs"
                              />
                            </div>
                          );
                        })}
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