"use client";

import { useState, useMemo } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ReturnsCharts } from "./charts/returns-charts";
import { RiskCharts } from "./charts/risk-charts";
import { EventCharts } from "./charts/event-charts";

interface PerformanceChartsProps {
  equityCurve: Array<Record<string, unknown>>;
  trades: Array<Record<string, unknown>>;
  analysis: Record<string, Record<string, unknown>> | undefined;
  benchmark: string;
  startDate: string;
  endDate: string;
}

const RETURNS_CHARTS = [
  { value: "cumulative", label: "累计收益曲线" },
  { value: "drawdown", label: "回撤曲线" },
  { value: "rolling", label: "滚动收益" },
];

const RISK_CHARTS = [
  { value: "distribution", label: "收益分布直方图" },
  { value: "volatility", label: "波动率" },
  { value: "sharpe", label: "夏普比率走势" },
];

const EVENT_CHARTS = [
  { value: "trigger_dist", label: "事件触发分布" },
  { value: "event_scatter", label: "事件收益散点" },
  { value: "holding_dist", label: "持仓周期分布" },
  { value: "event_winrate", label: "事件胜率统计" },
  { value: "equity_positions", label: "资金曲线与持仓数" },
];

export function PerformanceCharts({
  equityCurve,
  trades,
  analysis,
  benchmark,
  startDate,
  endDate,
}: PerformanceChartsProps) {
  const [returnsChart, setReturnsChart] = useState("cumulative");
  const [riskChart, setRiskChart] = useState("distribution");
  const [eventChart, setEventChart] = useState("trigger_dist");

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-sm font-medium text-foreground">表现图表</h3>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* Returns Section */}
        <ChartSection
          title="收益板块"
          options={RETURNS_CHARTS}
          value={returnsChart}
          onChange={setReturnsChart}
        >
          <ReturnsCharts
            chartType={returnsChart}
            equityCurve={equityCurve}
            benchmark={benchmark}
            startDate={startDate}
            endDate={endDate}
          />
        </ChartSection>

        {/* Risk Section */}
        <ChartSection
          title="风险板块"
          options={RISK_CHARTS}
          value={riskChart}
          onChange={setRiskChart}
        >
          <RiskCharts
            chartType={riskChart}
            equityCurve={equityCurve}
            trades={trades}
          />
        </ChartSection>

        {/* Event Section */}
        <ChartSection
          title="事件板块"
          options={EVENT_CHARTS}
          value={eventChart}
          onChange={setEventChart}
        >
          <EventCharts
            chartType={eventChart}
            equityCurve={equityCurve}
            trades={trades}
          />
        </ChartSection>
      </div>
    </div>
  );
}

function ChartSection({
  title,
  options,
  value,
  onChange,
  children,
}: {
  title: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-xs font-medium text-muted-foreground">
          {title}
        </span>
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger className="h-7 w-[150px] bg-secondary text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="h-[280px] p-4">{children}</div>
    </div>
  );
}
