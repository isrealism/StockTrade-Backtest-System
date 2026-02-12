"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { BacktestPayload } from "@/lib/types";

interface BasicParamsProps {
  payload: Partial<BacktestPayload>;
  onChange: (updates: Partial<BacktestPayload>) => void;
}

export function BasicParams({ payload, onChange }: BasicParamsProps) {
  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">基本参数</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">回测名称</Label>
            <Input
              id="name"
              placeholder="输入回测名称"
              value={payload.name || ""}
              onChange={(e) => onChange({ name: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="start_date">起始日期</Label>
            <Input
              id="start_date"
              type="date"
              value={payload.start_date || ""}
              onChange={(e) => onChange({ start_date: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="end_date">结束日期</Label>
            <Input
              id="end_date"
              type="date"
              value={payload.end_date || ""}
              onChange={(e) => onChange({ end_date: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="initial_capital">初始资金</Label>
            <Input
              id="initial_capital"
              type="number"
              value={payload.initial_capital ?? 1000000}
              onChange={(e) =>
                onChange({ initial_capital: parseFloat(e.target.value) || 0 })
              }
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="max_positions">最大持仓数</Label>
            <Input
              id="max_positions"
              type="number"
              min={1}
              max={50}
              value={payload.max_positions ?? 10}
              onChange={(e) =>
                onChange({ max_positions: parseInt(e.target.value) || 1 })
              }
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="position_sizing">仓位管理</Label>
            <Select
              value={payload.position_sizing || "equal_weight"}
              onValueChange={(v) => onChange({ position_sizing: v })}
            >
              <SelectTrigger id="position_sizing">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="equal_weight">等权分配</SelectItem>
                <SelectItem value="kelly">Kelly公式</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="commission_rate">佣金费率</Label>
            <Input
              id="commission_rate"
              type="number"
              step="0.0001"
              value={payload.commission_rate ?? 0.0003}
              onChange={(e) =>
                onChange({ commission_rate: parseFloat(e.target.value) || 0 })
              }
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="stamp_tax_rate">印花税率</Label>
            <Input
              id="stamp_tax_rate"
              type="number"
              step="0.0001"
              value={payload.stamp_tax_rate ?? 0.001}
              onChange={(e) =>
                onChange({ stamp_tax_rate: parseFloat(e.target.value) || 0 })
              }
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="slippage_rate">滑点费率</Label>
            <Input
              id="slippage_rate"
              type="number"
              step="0.0001"
              value={payload.slippage_rate ?? 0.001}
              onChange={(e) =>
                onChange({ slippage_rate: parseFloat(e.target.value) || 0 })
              }
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="lookback_days">回溯天数</Label>
            <Input
              id="lookback_days"
              type="number"
              value={payload.lookback_days ?? 200}
              onChange={(e) =>
                onChange({ lookback_days: parseInt(e.target.value) || 200 })
              }
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
