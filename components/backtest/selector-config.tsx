"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const SELECTOR_INFO: Record<string, { name: string; description: string }> = {
  BBIKDJSelector: {
    name: "少妇战法",
    description:
      "BBI持续上升 + KDJ超卖区 + 上穿MA60 + DIF>0，捕捉趋势向好的低位入场",
  },
  SuperB1Selector: {
    name: "SuperB1战法",
    description:
      "前期发出B1信号后横盘整理，当日突然大幅下跌进入超卖区，捕捉反弹机会",
  },
  BBIShortLongSelector: {
    name: "补票战法",
    description:
      "大趋势多头(BBI+DIF) + 长RSV高位 + 短RSV超卖后反弹，短线波动择时入场",
  },
  PeakKDJSelector: {
    name: "填坑战法",
    description:
      "上升趋势中最新峰值高于前峰，价格回调至前峰附近 + J值低位，在支撑位买入",
  },
  MA60CrossVolumeWaveSelector: {
    name: "上穿60放量战法",
    description: "收盘价上穿MA60均线并伴随成交量放大，趋势突破信号",
  },
  BigBullishVolumeSelector: {
    name: "暴力K战法",
    description:
      "单日实体大阳线 + 成交量显著放大 + 收盘价位于知行线之下，低位反弹确认",
  },
};

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
};

interface SelectorConfigProps {
  selectors: Array<{
    class: string;
    alias: string;
    activate: boolean;
    params: Record<string, unknown>;
  }>;
  onChange: (selectors: SelectorConfigProps["selectors"]) => void;
  combinationMode: string;
  onCombinationModeChange: (mode: string) => void;
}

export function SelectorConfig({
  selectors,
  onChange,
  combinationMode,
  onCombinationModeChange,
}: SelectorConfigProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  function toggleActivate(idx: number) {
    const updated = [...selectors];
    updated[idx] = { ...updated[idx], activate: !updated[idx].activate };
    onChange(updated);
  }

  function updateParam(idx: number, key: string, value: unknown) {
    const updated = [...selectors];
    updated[idx] = {
      ...updated[idx],
      params: { ...updated[idx].params, [key]: value },
    };
    onChange(updated);
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>买入选股器配置</CardTitle>
          <div className="flex items-center gap-2">
            <Label className="text-xs text-muted-foreground">信号组合:</Label>
            <div className="flex items-center gap-1 rounded-md bg-secondary p-0.5">
              {["OR", "AND"].map((mode) => (
                <button
                  key={mode}
                  onClick={() => onCombinationModeChange(mode)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                    combinationMode === mode
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {mode === "OR" ? "任一满足" : "全部满足"}
                </button>
              ))}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {selectors.map((selector, idx) => {
          const info = SELECTOR_INFO[selector.class];
          const isExpanded = expandedIdx === idx;
          return (
            <div
              key={selector.class}
              className={cn(
                "rounded-lg border transition-colors",
                selector.activate
                  ? "border-primary/30 bg-primary/5"
                  : "border-border bg-background"
              )}
            >
              {/* Header */}
              <div className="flex items-center gap-3 px-4 py-3">
                <Switch
                  checked={selector.activate}
                  onCheckedChange={() => toggleActivate(idx)}
                  aria-label={`启用${info?.name || selector.alias}`}
                />
                <button
                  onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                  className="flex flex-1 items-center gap-2 text-left"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-medium">
                    {info?.name || selector.alias}
                  </span>
                  <Badge variant="secondary" className="text-[10px]">
                    {selector.class}
                  </Badge>
                </button>
              </div>

              {/* Info + Params */}
              {isExpanded && (
                <div className="border-t border-border px-4 py-3">
                  {info && (
                    <div className="mb-3 flex items-start gap-2 rounded-md bg-secondary/50 p-2.5">
                      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                      <p className="text-xs leading-relaxed text-muted-foreground">
                        {info.description}
                      </p>
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                    {Object.entries(selector.params).map(([key, value]) => {
                      if (key === "B1_params") return null;
                      const label = PARAM_LABELS[key] || key;
                      if (typeof value === "boolean") {
                        return (
                          <div
                            key={key}
                            className="flex items-center justify-between gap-2 rounded-md bg-background p-2"
                          >
                            <Label className="text-xs text-muted-foreground">
                              {label}
                            </Label>
                            <Switch
                              checked={value}
                              onCheckedChange={(v) =>
                                updateParam(idx, key, v)
                              }
                            />
                          </div>
                        );
                      }
                      return (
                        <div key={key} className="space-y-1">
                          <Label className="text-xs text-muted-foreground">
                            {label}
                          </Label>
                          <Input
                            type="number"
                            value={String(value)}
                            onChange={(e) =>
                              updateParam(
                                idx,
                                key,
                                Number(e.target.value)
                              )
                            }
                            className="h-8 text-xs"
                            step={
                              typeof value === "number" && value < 1
                                ? "0.01"
                                : "1"
                            }
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
      </CardContent>
    </Card>
  );
}
