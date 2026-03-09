"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Info, TrendingUp, RefreshCw } from "lucide-react";
import { useNumberInput } from "@/lib/useNumberInput";

// ─────────────────────────────────────────────
// 类型定义
// ─────────────────────────────────────────────

export interface ScoreFilterConfig {
  enabled: boolean;
  percentile_threshold: number;   // 0–100
  min_history: number;
  warmup_lookback_days: number;
}

export interface RotationConfig {
  enabled: boolean;
  min_loss: number;               // 如 0.05
  max_per_day: number;
  score_ratio: number;            // 如 1.2
  min_score_improvement: number;  // 如 10.0
  no_score_policy: "skip" | "allow" | "mean";
}

export interface ScoreRotationConfigProps {
  scoreFilter: ScoreFilterConfig;
  rotation: RotationConfig;
  onScoreFilterChange: (cfg: ScoreFilterConfig) => void;
  onRotationChange: (cfg: RotationConfig) => void;
}

// ─────────────────────────────────────────────
// 小工具：带 tooltip 的 Label
// ─────────────────────────────────────────────

function LabelWithTip({ label, tip }: { label: string; tip: string }) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="flex items-center gap-1 cursor-default">
            {label}
            <Info className="h-3 w-3 text-muted-foreground" />
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs text-xs">
          {tip}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ─────────────────────────────────────────────
// 主组件
// ─────────────────────────────────────────────

export function ScoreRotationConfig({
  scoreFilter,
  rotation,
  onScoreFilterChange,
  onRotationChange,
}: ScoreRotationConfigProps) {

  // ── ScoreFilter 字段 ──────────────────────────────────────────────
  const percentileInp = useNumberInput(
    scoreFilter.percentile_threshold,
    (num) => onScoreFilterChange({ ...scoreFilter, percentile_threshold: num }),
    { clamp: (n) => Math.min(99, Math.max(1, Math.round(n))) }
  );

  const minHistoryInp = useNumberInput(
    scoreFilter.min_history,
    (num) => onScoreFilterChange({ ...scoreFilter, min_history: num }),
    { clamp: (n) => Math.max(1, Math.round(n)) }
  );

  const warmupDaysInp = useNumberInput(
    scoreFilter.warmup_lookback_days,
    (num) => onScoreFilterChange({ ...scoreFilter, warmup_lookback_days: num }),
    { clamp: (n) => Math.max(1, Math.round(n)) }
  );

  // ── Rotation 字段 ─────────────────────────────────────────────────
  // min_loss 存储 0~1，界面显示百分比
  const minLossInp = useNumberInput(
    rotation.min_loss * 100,
    (num) => onRotationChange({ ...rotation, min_loss: num / 100 }),
    {
      display: (v) => v.toFixed(1),
      clamp: (n) => Math.max(0.1, Math.min(50, n)),
    }
  );

  const maxPerDayInp = useNumberInput(
    rotation.max_per_day,
    (num) => onRotationChange({ ...rotation, max_per_day: num }),
    { clamp: (n) => Math.max(1, Math.min(10, Math.round(n))) }
  );

  const scoreRatioInp = useNumberInput(
    rotation.score_ratio,
    (num) => onRotationChange({ ...rotation, score_ratio: num }),
    {
      display: (v) => v.toFixed(1),
      clamp: (n) => Math.max(1.0, Math.min(3.0, n)),
    }
  );

  const minScoreImprovementInp = useNumberInput(
    rotation.min_score_improvement,
    (num) => onRotationChange({ ...rotation, min_score_improvement: num }),
    { clamp: (n) => Math.max(0, n) }
  );

  return (
    <div className="space-y-4">
      {/* ── Score 百分位过滤 ──────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <TrendingUp className="h-4 w-4 text-primary" />
              信号质量过滤（Score Filter）
            </CardTitle>
            <Switch
              checked={scoreFilter.enabled}
              onCheckedChange={(v) =>
                onScoreFilterChange({ ...scoreFilter, enabled: v })
              }
            />
          </div>
          <p className="text-xs text-muted-foreground">
            只允许评分高于历史百分位阈值的信号进入买入决策，过滤低质量入场机会
          </p>
        </CardHeader>

        {scoreFilter.enabled && (
          <CardContent className="grid grid-cols-2 gap-3 pt-0">
            {/* 百分位阈值 */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="百分位阈值"
                  tip="例如 60 表示只保留历史前 40% 的强信号（score ≥ 历史第60百分位数）"
                />
              </Label>
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  value={percentileInp.inputValue}
                  onChange={percentileInp.handleChange}
                  onBlur={percentileInp.handleBlur}
                  min={1}
                  max={99}
                  step={5}
                  className="h-8 text-xs"
                />
                <span className="text-xs text-muted-foreground shrink-0">%</span>
              </div>
              <p className="text-xs text-muted-foreground">
                保留历史前{" "}
                <span className="font-medium text-foreground">
                  {100 - scoreFilter.percentile_threshold}%
                </span>{" "}
                强信号
              </p>
            </div>

            {/* 最低历史样本数 */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="最低样本数"
                  tip="历史 score 记录数量不足此值时，跳过过滤直接放行所有信号"
                />
              </Label>
              <Input
                type="number"
                value={minHistoryInp.inputValue}
                onChange={minHistoryInp.handleChange}
                onBlur={minHistoryInp.handleBlur}
                min={1}
                className="h-8 text-xs"
              />
            </div>

            {/* 预热天数 */}
            <div className="space-y-1 col-span-2">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="预热期天数"
                  tip="正式回测开始前，利用此天数的历史数据预填充 score 分布，避免冷启动"
                />
              </Label>
              <Input
                type="number"
                value={warmupDaysInp.inputValue}
                onChange={warmupDaysInp.handleChange}
                onBlur={warmupDaysInp.handleBlur}
                min={1}
                className="h-8 text-xs"
              />
            </div>
          </CardContent>
        )}
      </Card>

      {/* ── 换仓逻辑 (Rotation) ──────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <RefreshCw className="h-4 w-4 text-primary" />
              主动换仓（Rotation）
            </CardTitle>
            <Switch
              checked={rotation.enabled}
              onCheckedChange={(v) =>
                onRotationChange({ ...rotation, enabled: v })
              }
            />
          </div>
          <p className="text-xs text-muted-foreground">
            当持仓亏损且当日有评分更高的新信号时，自动替换亏损仓位，提升资金效率
          </p>
        </CardHeader>

        {rotation.enabled && (
          <CardContent className="grid grid-cols-2 gap-3 pt-0">
            {/* 最低亏损触发 */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="触发最低亏损"
                  tip="持仓未实现亏损达到此比例才纳入换仓候选（如 0.05 = 亏损 5%）"
                />
              </Label>
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  value={minLossInp.inputValue}
                  onChange={minLossInp.handleChange}
                  onBlur={minLossInp.handleBlur}
                  min={0.1}
                  max={50}
                  step={0.5}
                  className="h-8 text-xs"
                />
                <span className="text-xs text-muted-foreground shrink-0">%</span>
              </div>
            </div>

            {/* 每日最大换仓数 */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="每日最大换仓数"
                  tip="单日触发换仓的最大对数，防止过度换仓"
                />
              </Label>
              <Input
                type="number"
                value={maxPerDayInp.inputValue}
                onChange={maxPerDayInp.handleChange}
                onBlur={maxPerDayInp.handleBlur}
                min={1}
                max={10}
                className="h-8 text-xs"
              />
            </div>

            {/* Score 倍数门槛 */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="Score 倍数门槛"
                  tip="新信号 score ≥ 旧入场 score × 此倍数，才允许换仓（相对门槛）"
                />
              </Label>
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  value={scoreRatioInp.inputValue}
                  onChange={scoreRatioInp.handleChange}
                  onBlur={scoreRatioInp.handleBlur}
                  min={1.0}
                  max={3.0}
                  step={0.1}
                  className="h-8 text-xs"
                />
                <span className="text-xs text-muted-foreground shrink-0">×</span>
              </div>
            </div>

            {/* 最低绝对提升 */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="最低 Score 提升"
                  tip="新信号 score 须比旧入场 score 高出此绝对值（绝对门槛，防微小差距触发）"
                />
              </Label>
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  value={minScoreImprovementInp.inputValue}
                  onChange={minScoreImprovementInp.handleChange}
                  onBlur={minScoreImprovementInp.handleBlur}
                  min={0}
                  step={1}
                  className="h-8 text-xs"
                />
                <span className="text-xs text-muted-foreground shrink-0">pts</span>
              </div>
            </div>

            {/* 无 entry_score 仓位策略 */}
            <div className="space-y-1 col-span-2">
              <Label className="text-xs text-muted-foreground">
                <LabelWithTip
                  label="无评分仓位策略"
                  tip="持仓若无 entry_score 记录时的处理方式：skip=跳过（保守），allow=视为0（激进），mean=用历史均值填充（中性）"
                />
              </Label>
              <Select
                value={rotation.no_score_policy}
                onValueChange={(v) =>
                  onRotationChange({
                    ...rotation,
                    no_score_policy: v as "skip" | "allow" | "mean",
                  })
                }
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="skip" className="text-xs">
                    skip — 跳过（保守，默认）
                  </SelectItem>
                  <SelectItem value="allow" className="text-xs">
                    allow — 视 score 为 0（激进）
                  </SelectItem>
                  <SelectItem value="mean" className="text-xs">
                    mean — 用历史均值填充（中性）
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        )}
      </Card>
    </div>
  );
}

// ─────────────────────────────────────────────
// 默认值导出（方便 backtest-form.tsx 使用）
// ─────────────────────────────────────────────

export const DEFAULT_SCORE_FILTER: ScoreFilterConfig = {
  enabled: false,
  percentile_threshold: 60,
  min_history: 20,
  warmup_lookback_days: 20,
};

export const DEFAULT_ROTATION: RotationConfig = {
  enabled: false,
  min_loss: 0.05,
  max_per_day: 2,
  score_ratio: 1.2,
  min_score_improvement: 10.0,
  no_score_policy: "skip",
};