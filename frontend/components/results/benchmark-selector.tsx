"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const BENCHMARKS = [
  { value: "上证指数", label: "上证指数" },
  { value: "沪深300", label: "沪深300" },
  { value: "中证500", label: "中证500" },
  { value: "创业板指", label: "创业板指" },
  { value: "none", label: "不对比" },
];

interface BenchmarkSelectorProps {
  value: string;
  onChange: (v: string) => void;
}

export function BenchmarkSelector({ value, onChange }: BenchmarkSelectorProps) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-[160px] bg-card">
        <SelectValue placeholder="选择对比基准" />
      </SelectTrigger>
      <SelectContent>
        {BENCHMARKS.map((b) => (
          <SelectItem key={b.value} value={b.value}>
            {b.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
