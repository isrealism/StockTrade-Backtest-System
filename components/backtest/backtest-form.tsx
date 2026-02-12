"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SelectorConfig } from "./selector-config";
import { SellStrategyConfig } from "./sell-strategy-config";
import { createBacktest, type BacktestPayload, type SelectorConfig as SelectorType, type SellStrategyConfig as SellType } from "@/lib/api";
import {
  Play,
  Save,
  Loader2,
  Calendar,
  DollarSign,
  Settings2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface BacktestFormProps {
  selectors: SelectorType[];
  sellStrategies: Record<string, SellType>;
}

export function BacktestForm({ selectors, sellStrategies }: BacktestFormProps) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Basic params
  const [name, setName] = useState("回测任务");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [initialCapital, setInitialCapital] = useState(1000000);
  const [maxPositions, setMaxPositions] = useState(10);
  const [positionSizing, setPositionSizing] = useState("equal_weight");

  // Advanced params
  const [commissionRate, setCommissionRate] = useState(0.0003);
  const [stampTaxRate, setStampTaxRate] = useState(0.001);
  const [slippageRate, setSlippageRate] = useState(0.001);
  const [lookbackDays, setLookbackDays] = useState(200);

  // Stock pool
  const [stockPoolType, setStockPoolType] = useState("all");
  const [customCodes, setCustomCodes] = useState("");

  // Selector config
  const [selectorList, setSelectorList] = useState(selectors);
  const [combinationMode, setCombinationMode] = useState("OR");

  // Sell strategy config
  const [selectedSellStrategy, setSelectedSellStrategy] = useState(
    Object.keys(sellStrategies)[0] || "conservative_trailing"
  );
  const [customSellParams, setCustomSellParams] = useState<Record<string, Record<string, unknown>> | null>(null);

  const handleSubmit = useCallback(async () => {
    setIsSubmitting(true);
    try {
      const buyConfig = {
        selector_combination: {
          mode: combinationMode,
          time_window_days: 5,
          required_selectors: [],
        },
        selectors: selectorList,
      };

      const payload: BacktestPayload = {
        name,
        start_date: startDate,
        end_date: endDate,
        initial_capital: initialCapital,
        max_positions: maxPositions,
        position_sizing: positionSizing,
        commission_rate: commissionRate,
        stamp_tax_rate: stampTaxRate,
        slippage_rate: slippageRate,
        sell_strategy_name: selectedSellStrategy,
        buy_config: buyConfig,
        lookback_days: lookbackDays,
        stock_pool:
          stockPoolType === "all"
            ? { type: "all" }
            : {
                type: "list",
                codes: customCodes
                  .split(/[,\n\s]+/)
                  .map((c) => c.trim())
                  .filter(Boolean),
              },
      };

      const result = await createBacktest(payload);
      router.push(`/tasks?active=${result.id}`);
    } catch (err) {
      console.error("Failed to create backtest:", err);
    } finally {
      setIsSubmitting(false);
    }
  }, [
    name, startDate, endDate, initialCapital, maxPositions, positionSizing,
    commissionRate, stampTaxRate, slippageRate, lookbackDays, stockPoolType,
    customCodes, selectorList, combinationMode, selectedSellStrategy, router,
  ]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-foreground">回测配置</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            配置选股策略、卖出策略及回测参数，启动量化回测
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Save className="mr-1.5 h-3.5 w-3.5" />
            保存模板
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isSubmitting}
            size="sm"
          >
            {isSubmitting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-1.5 h-3.5 w-3.5" />
            )}
            启动回测
          </Button>
        </div>
      </div>

      <Tabs defaultValue="basic" className="space-y-4">
        <TabsList>
          <TabsTrigger value="basic">基础配置</TabsTrigger>
          <TabsTrigger value="selectors">选股策略</TabsTrigger>
          <TabsTrigger value="sell">卖出策略</TabsTrigger>
        </TabsList>

        {/* Basic Config Tab */}
        <TabsContent value="basic">
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Basic Params Card */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-primary" />
                  基本参数
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>任务名称</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="输入回测任务名称"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label>开始日期</Label>
                    <Input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>结束日期</Label>
                    <Input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>股票池</Label>
                  <Select value={stockPoolType} onValueChange={setStockPoolType}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全量股票</SelectItem>
                      <SelectItem value="list">自定义股票代码</SelectItem>
                    </SelectContent>
                  </Select>
                  {stockPoolType === "list" && (
                    <textarea
                      className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      placeholder={"输入股票代码, 逗号或换行分隔\n例如: 000001, 000002, 600000"}
                      value={customCodes}
                      onChange={(e) => setCustomCodes(e.target.value)}
                    />
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Capital & Position Card */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <DollarSign className="h-4 w-4 text-primary" />
                  资金与仓位
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>初始资金 (元)</Label>
                  <Input
                    type="number"
                    value={initialCapital}
                    onChange={(e) => setInitialCapital(Number(e.target.value))}
                    step={100000}
                  />
                </div>
                <div className="space-y-2">
                  <Label>最大持仓数</Label>
                  <Input
                    type="number"
                    value={maxPositions}
                    onChange={(e) => setMaxPositions(Number(e.target.value))}
                    min={1}
                    max={50}
                  />
                </div>
                <div className="space-y-2">
                  <Label>仓位分配方式</Label>
                  <Select value={positionSizing} onValueChange={setPositionSizing}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="equal_weight">等权分配</SelectItem>
                      <SelectItem value="risk_based">基于风险分配 (ATR)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Advanced Toggle */}
                <button
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  <Settings2 className="h-3.5 w-3.5" />
                  高级参数
                  {showAdvanced ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronRight className="h-3 w-3" />
                  )}
                </button>

                {showAdvanced && (
                  <div className="grid grid-cols-2 gap-3 rounded-md bg-secondary/50 p-3">
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        佣金费率
                      </Label>
                      <Input
                        type="number"
                        value={commissionRate}
                        onChange={(e) =>
                          setCommissionRate(Number(e.target.value))
                        }
                        step={0.0001}
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        印花税率
                      </Label>
                      <Input
                        type="number"
                        value={stampTaxRate}
                        onChange={(e) =>
                          setStampTaxRate(Number(e.target.value))
                        }
                        step={0.0001}
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        滑点费率
                      </Label>
                      <Input
                        type="number"
                        value={slippageRate}
                        onChange={(e) =>
                          setSlippageRate(Number(e.target.value))
                        }
                        step={0.0001}
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        数据回溯天数
                      </Label>
                      <Input
                        type="number"
                        value={lookbackDays}
                        onChange={(e) =>
                          setLookbackDays(Number(e.target.value))
                        }
                        min={60}
                        className="h-8 text-xs"
                      />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Selector Config Tab */}
        <TabsContent value="selectors">
          <SelectorConfig
            selectors={selectorList}
            onChange={setSelectorList}
            combinationMode={combinationMode}
            onCombinationModeChange={setCombinationMode}
          />
        </TabsContent>

        {/* Sell Strategy Tab */}
        <TabsContent value="sell">
          <SellStrategyConfig
            strategies={sellStrategies}
            selectedStrategy={selectedSellStrategy}
            onSelectStrategy={setSelectedSellStrategy}
            customParams={customSellParams}
            onCustomParamsChange={setCustomSellParams}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
