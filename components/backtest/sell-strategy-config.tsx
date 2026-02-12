"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SELL_COMBO_NAMES, SELL_STRATEGY_DESCRIPTIONS } from "@/lib/constants";
import type { SellStrategyConfig } from "@/lib/types";

interface SellStrategyConfigPanelProps {
  strategies: Record<string, SellStrategyConfig>;
  selectedName: string;
  onSelect: (name: string) => void;
  onConfigChange: (config: SellStrategyConfig) => void;
}

export function SellStrategyConfigPanel({
  strategies,
  selectedName,
  onSelect,
  onConfigChange,
}: SellStrategyConfigPanelProps) {
  const currentConfig = strategies[selectedName];

  const updateSubParam = (
    stratIdx: number,
    paramKey: string,
    value: number | boolean | string
  ) => {
    if (!currentConfig?.strategies) return;
    const updated = { ...currentConfig };
    const subs = [...(updated.strategies || [])];
    subs[stratIdx] = {
      ...subs[stratIdx],
      params: { ...subs[stratIdx].params, [paramKey]: value },
    };
    updated.strategies = subs;
    onConfigChange(updated);
  };

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">卖出策略</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label>策略组合</Label>
            <Select value={selectedName} onValueChange={onSelect}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(strategies).map(([key, config]) => (
                  <SelectItem key={key} value={key}>
                    {SELL_COMBO_NAMES[key] || key}
                    <span className="ml-2 text-xs text-muted-foreground">
                      ({key})
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {currentConfig && (
            <div className="rounded-lg border bg-background p-4">
              <p className="mb-1 text-sm font-medium">
                {SELL_COMBO_NAMES[selectedName] || selectedName}
              </p>
              <p className="mb-4 text-xs text-muted-foreground">
                {currentConfig.description}
              </p>

              {currentConfig.combination_logic && (
                <Badge variant="outline" className="mb-3">
                  组合逻辑: {currentConfig.combination_logic}
                </Badge>
              )}

              {currentConfig.strategies?.map((sub, idx) => {
                const desc = SELL_STRATEGY_DESCRIPTIONS[sub.class];
                return (
                  <div
                    key={`${sub.class}-${idx}`}
                    className="mt-3 rounded border bg-card p-3"
                  >
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-sm font-medium">
                        {desc?.name || sub.class}
                      </span>
                      {desc && (
                        <Badge
                          variant="secondary"
                          className="text-xs font-normal"
                        >
                          {desc.category}
                        </Badge>
                      )}
                    </div>
                    {Object.keys(sub.params).length > 0 && (
                      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                        {Object.entries(sub.params).map(
                          ([paramKey, paramVal]) => (
                            <div
                              key={paramKey}
                              className="flex flex-col gap-1"
                            >
                              <Label className="text-xs text-muted-foreground">
                                {paramKey}
                              </Label>
                              {typeof paramVal === "boolean" ? (
                                <Select
                                  value={paramVal ? "true" : "false"}
                                  onValueChange={(v) =>
                                    updateSubParam(
                                      idx,
                                      paramKey,
                                      v === "true"
                                    )
                                  }
                                >
                                  <SelectTrigger className="h-8 text-xs">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="true">true</SelectItem>
                                    <SelectItem value="false">false</SelectItem>
                                  </SelectContent>
                                </Select>
                              ) : (
                                <Input
                                  type="number"
                                  step="any"
                                  className="h-8 text-xs"
                                  value={paramVal as number}
                                  onChange={(e) => {
                                    const v = parseFloat(e.target.value);
                                    if (!isNaN(v))
                                      updateSubParam(idx, paramKey, v);
                                  }}
                                />
                              )}
                            </div>
                          )
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {currentConfig.class && !currentConfig.strategies && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {SELL_STRATEGY_DESCRIPTIONS[currentConfig.class]?.description ||
                    "无额外参数"}
                </p>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
