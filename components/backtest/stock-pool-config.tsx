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
import type { StockPool } from "@/lib/types";

interface StockPoolConfigProps {
  pool: StockPool;
  onChange: (pool: StockPool) => void;
}

export function StockPoolConfig({ pool, onChange }: StockPoolConfigProps) {
  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">股票池</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label>选股范围</Label>
            <Select
              value={pool.type}
              onValueChange={(v) =>
                onChange({ type: v as "all" | "list", codes: pool.codes })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部A股</SelectItem>
                <SelectItem value="list">自定义股票列表</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {pool.type === "list" && (
            <div className="flex flex-col gap-2">
              <Label>股票代码（逗号分隔）</Label>
              <Input
                placeholder="如：000001, 600519, 300750"
                value={(pool.codes || []).join(", ")}
                onChange={(e) =>
                  onChange({
                    type: "list",
                    codes: e.target.value
                      .split(/[,，\s]+/)
                      .map((c) => c.trim())
                      .filter(Boolean),
                  })
                }
              />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
