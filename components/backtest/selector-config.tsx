"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SELECTOR_DESCRIPTIONS } from "@/lib/constants";
import type { SelectorConfig, SelectorParam } from "@/lib/types";

interface SelectorConfigPanelProps {
  selectors: SelectorConfig[];
  onChange: (selectors: SelectorConfig[]) => void;
}

export function SelectorConfigPanel({
  selectors,
  onChange,
}: SelectorConfigPanelProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const toggleActivate = (idx: number) => {
    const updated = [...selectors];
    updated[idx] = { ...updated[idx], activate: !updated[idx].activate };
    onChange(updated);
  };

  const updateParam = (idx: number, key: string, value: number | boolean | string) => {
    const updated = [...selectors];
    updated[idx] = {
      ...updated[idx],
      params: { ...updated[idx].params, [key]: value },
    };
    onChange(updated);
  };

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">选股策略（买入信号）</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          {selectors.map((sel, idx) => {
            const desc = SELECTOR_DESCRIPTIONS[sel.class];
            const isExpanded = expanded === sel.class;
            return (
              <div
                key={sel.class}
                className="rounded-lg border bg-background p-4"
              >
                <div className="flex items-center gap-3">
                  <Switch
                    checked={sel.activate}
                    onCheckedChange={() => toggleActivate(idx)}
                  />
                  <button
                    type="button"
                    className="flex flex-1 items-center gap-2 text-left"
                    onClick={() =>
                      setExpanded(isExpanded ? null : sel.class)
                    }
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="font-medium">{sel.alias}</span>
                    <Badge variant="outline" className="ml-1 text-xs font-normal">
                      {sel.class}
                    </Badge>
                  </button>
                  {desc && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Info className="h-4 w-4 shrink-0 text-muted-foreground" />
                      </TooltipTrigger>
                      <TooltipContent
                        side="left"
                        className="max-w-xs text-xs leading-relaxed"
                      >
                        {desc.summary}
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>
                {isExpanded && (
                  <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
                    {renderParams(sel.params, (key, value) =>
                      updateParam(idx, key, value)
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function renderParams(
  params: SelectorParam,
  onChange: (key: string, value: number | boolean | string) => void,
  prefix = ""
) {
  return Object.entries(params).map(([key, value]) => {
    const fullKey = prefix ? `${prefix}.${key}` : key;

    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      return (
        <div
          key={fullKey}
          className="col-span-full rounded border bg-card p-3"
        >
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            {key}
          </p>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {renderParams(
              value as SelectorParam,
              (subKey, val) => onChange(`${key}.${subKey}` as string, val),
              fullKey
            )}
          </div>
        </div>
      );
    }

    if (typeof value === "boolean") {
      return (
        <div key={fullKey} className="flex items-center gap-2">
          <Switch
            id={fullKey}
            checked={value}
            onCheckedChange={(v) => onChange(key, v)}
          />
          <Label htmlFor={fullKey} className="text-xs">
            {key}
          </Label>
        </div>
      );
    }

    return (
      <div key={fullKey} className="flex flex-col gap-1">
        <Label htmlFor={fullKey} className="text-xs text-muted-foreground">
          {key}
        </Label>
        <Input
          id={fullKey}
          type="number"
          step="any"
          className="h-8 text-xs"
          value={value as number}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v)) onChange(key, v);
          }}
        />
      </div>
    );
  });
}
