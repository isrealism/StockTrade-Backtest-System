"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
  BarChart3,
  TrendingUp,
  Factory,
  Landmark,
  ShieldCheck,
  Droplets,
  BadgeDollarSign,
  FileBarChart2,
  RotateCcw,
  Check,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

// ─── Data ────────────────────────────────────────────────────────────────────

const INDUSTRIES: Record<string, string[]> = {
  消费: ["白酒", "食品饮料", "家用电器", "纺织服装", "商贸零售", "休闲服务", "农林牧渔"],
  科技: ["电子", "计算机", "通信", "传媒", "半导体", "人工智能"],
  医药: ["医药生物", "医疗器械", "创新药", "中药", "医疗服务"],
  周期: ["煤炭", "钢铁", "化工", "有色金属", "石油石化", "建材"],
  金融: ["银行", "券商", "保险", "多元金融"],
  制造: ["新能源", "电力设备", "军工", "机械设备", "汽车", "交运设备"],
  地产基建: ["房地产", "建筑装饰", "建筑材料", "公用事业"],
};

const INDEX_CONSTITUENTS = [
  "沪深300", "中证500", "中证1000", "上证50",
  "科创50", "创业板指", "中证100", "北证50",
];

const MARKET_TYPES = [
  { id: "sh_main", label: "沪市主板" },
  { id: "sz_main", label: "深市主板" },
  { id: "chinext", label: "创业板" },
  { id: "star", label: "科创板" },
  { id: "bj", label: "北交所" },
];

const QUALITY_FILTERS = [
  { id: "no_st", label: "排除 ST 股", desc: "剔除ST/*ST股票", default: true },
  { id: "no_new", label: "排除次新股", desc: "上市不足6个月", default: true },
  { id: "no_halt", label: "排除停牌股", desc: "当前处于停牌状态", default: true },
  { id: "no_limit", label: "排除连续涨跌停", desc: "过去20日涨跌停≥5次", default: false },
  { id: "no_loss", label: "排除连亏股", desc: "连续2年净利润为负", default: false },
  { id: "no_audit", label: "排除非标审计", desc: "审计意见非标准无保留", default: false },
  { id: "hs_connect", label: "仅沪深通标的", desc: "北向资金可配置股票", default: false },
  { id: "profit_positive", label: "盈利为正", desc: "最近一期净利润 > 0", default: false },
];

const MV_PRESETS = [
  { label: "微盘", range: "0~20亿", color: "text-slate-400 border-slate-400/40 bg-slate-400/10" },
  { label: "小盘", range: "20~100亿", color: "text-blue-400 border-blue-400/40 bg-blue-400/10" },
  { label: "中盘", range: "100~500亿", color: "text-emerald-400 border-emerald-400/40 bg-emerald-400/10" },
  { label: "大盘", range: "500~2000亿", color: "text-amber-400 border-amber-400/40 bg-amber-400/10" },
  { label: "超大盘", range: "2000亿+", color: "text-red-400 border-red-400/40 bg-red-400/10" },
];

const LIQUIDITY_PRESETS = [
  { label: "宽松", desc: "≥ 1000万/日" },
  { label: "标准", desc: "≥ 3000万/日" },
  { label: "严格", desc: "≥ 1亿/日" },
  { label: "超严格", desc: "≥ 5亿/日" },
];

const VALUATION_FILTERS = [
  { id: "pe_lte50", label: "PE ≤ 50×", desc: "市盈率不超过50倍（TTM）" },
  { id: "pe_positive", label: "PE 为正", desc: "盈利为正，排除亏损股" },
  { id: "pb_lte5", label: "PB ≤ 5×", desc: "市净率不超过5倍" },
  { id: "pb_lte1", label: "PB ≤ 1×", desc: "破净股，价值修复机会" },
  { id: "div_gt2", label: "股息率 ≥ 2%", desc: "近12个月股息率" },
  { id: "div_gt4", label: "股息率 ≥ 4%", desc: "高股息策略门槛" },
  { id: "low_pe_rank", label: "PE 历史低位", desc: "PE处于近3年30%分位以下" },
  { id: "low_pb_rank", label: "PB 历史低位", desc: "PB处于近3年30%分位以下" },
];

const FINANCIAL_FILTERS = [
  { id: "roe_gt10", label: "ROE ≥ 10%", desc: "净资产收益率基准线" },
  { id: "roe_gt15", label: "ROE ≥ 15%", desc: "高质量盈利门槛" },
  { id: "rev_growth", label: "营收同比增长", desc: "近一年营收同比 > 0%" },
  { id: "profit_growth", label: "净利润同比增长", desc: "近一年净利润同比 > 0%" },
  { id: "gross_gt30", label: "毛利率 ≥ 30%", desc: "具备一定定价能力" },
  { id: "debt_lt60", label: "负债率 < 60%", desc: "财务稳健（金融股除外）" },
  { id: "debt_lt80", label: "负债率 < 80%", desc: "排除高杠杆标的" },
  { id: "fcf_positive", label: "自由现金流为正", desc: "经营现金流覆盖资本开支" },
];

// ─── Types ───────────────────────────────────────────────────────────────────

export interface StockFilterConfig {
  mvPresets: string[];
  mvCustom: { enabled: boolean; min: string; max: string };
  selectedIndex: string[];
  selectedIndustries: string[];
  selectedMarkets: string[];
  qualityFilters: Record<string, boolean>;
  liquidityPreset: string;
  liquidityCustom: string;
  valuationFilters: Record<string, boolean>;
  financialFilters: Record<string, boolean>;
}

export function defaultStockFilterConfig(): StockFilterConfig {
  return {
    mvPresets: [],
    mvCustom: { enabled: false, min: "", max: "" },
    selectedIndex: [],
    selectedIndustries: [],
    selectedMarkets: [],
    qualityFilters: Object.fromEntries(QUALITY_FILTERS.map((f) => [f.id, f.default])),
    liquidityPreset: "标准",
    liquidityCustom: "",
    valuationFilters: {},
    financialFilters: {},
  };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionHeader({
  icon: Icon,
  title,
  count,
}: {
  icon: React.ElementType;
  title: string;
  count?: number;
}) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <Icon className="h-3.5 w-3.5 text-primary" />
      <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
        {title}
      </span>
      {count !== undefined && (
        <span
          className={cn(
            "ml-auto rounded-full px-2 py-0.5 text-[10px] font-mono",
            count > 0
              ? "bg-primary/15 text-primary"
              : "bg-muted text-muted-foreground"
          )}
        >
          {count > 0 ? `${count} 已选` : "未选"}
        </span>
      )}
    </div>
  );
}

function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-border bg-card p-4", className)}>
      {children}
    </div>
  );
}

function FilterTag({
  label,
  active,
  onClick,
  colorClass,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  colorClass?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded border px-2.5 py-1 text-xs font-medium transition-all duration-150",
        active
          ? colorClass ?? "border-primary/50 bg-primary/15 text-primary"
          : "border-border bg-transparent text-muted-foreground hover:border-muted-foreground/40 hover:text-foreground"
      )}
    >
      {label}
    </button>
  );
}

function ToggleFilter({
  label,
  desc,
  checked,
  onChange,
}: {
  label: string;
  desc?: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <button
      onClick={onChange}
      className={cn(
        "flex items-start gap-2.5 rounded-md border p-2.5 text-left transition-all duration-150",
        checked
          ? "border-primary/30 bg-primary/8"
          : "border-transparent bg-muted/30 hover:bg-muted/60"
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] transition-colors",
          checked
            ? "border-primary bg-primary text-primary-foreground"
            : "border-muted-foreground/40 bg-transparent"
        )}
      >
        {checked && <Check className="h-2.5 w-2.5" />}
      </span>
      <div>
        <p className={cn("text-xs font-medium leading-none", checked ? "text-foreground" : "text-muted-foreground")}>
          {label}
        </p>
        {desc && <p className="mt-1 text-[10px] leading-snug text-muted-foreground/60">{desc}</p>}
      </div>
    </button>
  );
}

// ─── Summary ─────────────────────────────────────────────────────────────────

function generateSummary(cfg: StockFilterConfig): string {
  const parts: string[] = [];
  const countActive = (obj: Record<string, boolean>) => Object.values(obj).filter(Boolean).length;

  if (cfg.mvPresets.length > 0) parts.push(`市值: ${cfg.mvPresets.join("/")}`)
  if (cfg.selectedIndex.length > 0) parts.push(`指数: ${cfg.selectedIndex.slice(0, 2).join("/")}${cfg.selectedIndex.length > 2 ? "…" : ""}`)
  if (cfg.selectedIndustries.length > 0) parts.push(`行业: ${cfg.selectedIndustries.slice(0, 3).join("/")}${cfg.selectedIndustries.length > 3 ? `+${cfg.selectedIndustries.length - 3}` : ""}`)
  if (cfg.selectedMarkets.length > 0) parts.push(cfg.selectedMarkets.map((m) => MARKET_TYPES.find((x) => x.id === m)?.label).join("/"))
  const qc = countActive(cfg.qualityFilters); if (qc > 0) parts.push(`质量${qc}项`)
  const vc = countActive(cfg.valuationFilters); if (vc > 0) parts.push(`估值${vc}项`)
  const fc = countActive(cfg.financialFilters); if (fc > 0) parts.push(`财务${fc}项`)
  return parts.length > 0 ? parts.join("  ·  ") : "未配置任何筛选条件"
}

function countTotal(cfg: StockFilterConfig): number {
  const countActive = (obj: Record<string, boolean>) => Object.values(obj).filter(Boolean).length;
  return (
    cfg.mvPresets.length + (cfg.mvCustom.enabled ? 1 : 0) +
    cfg.selectedIndex.length + cfg.selectedIndustries.length +
    cfg.selectedMarkets.length +
    countActive(cfg.qualityFilters) + countActive(cfg.valuationFilters) +
    countActive(cfg.financialFilters) +
    (cfg.liquidityPreset !== "标准" || cfg.liquidityCustom ? 1 : 0)
  );
}

// ─── Main Dialog ──────────────────────────────────────────────────────────────

interface StockFilterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: StockFilterConfig;
  onChange: (cfg: StockFilterConfig) => void;
}

export function StockFilterDialog({
  open,
  onOpenChange,
  value,
  onChange,
}: StockFilterDialogProps) {
  // Local draft state — only committed on "确认"
  const [draft, setDraft] = useState<StockFilterConfig>(value);
  const [expandedGroups, setExpandedGroups] = useState<string[]>(Object.keys(INDUSTRIES));

  const update = (partial: Partial<StockFilterConfig>) =>
    setDraft((prev) => ({ ...prev, ...partial }));

  const countActive = (obj: Record<string, boolean>) =>
    Object.values(obj).filter(Boolean).length;

  const toggleMv = (label: string) =>
    update({
      mvPresets: draft.mvPresets.includes(label)
        ? draft.mvPresets.filter((x) => x !== label)
        : [...draft.mvPresets, label],
    });

  const toggleIndex = (idx: string) =>
    update({
      selectedIndex: draft.selectedIndex.includes(idx)
        ? draft.selectedIndex.filter((x) => x !== idx)
        : [...draft.selectedIndex, idx],
    });

  const toggleMarket = (id: string) =>
    update({
      selectedMarkets: draft.selectedMarkets.includes(id)
        ? draft.selectedMarkets.filter((x) => x !== id)
        : [...draft.selectedMarkets, id],
    });

  const toggleIndustry = (name: string) =>
    update({
      selectedIndustries: draft.selectedIndustries.includes(name)
        ? draft.selectedIndustries.filter((x) => x !== name)
        : [...draft.selectedIndustries, name],
    });

  const toggleGroup = (group: string) => {
    const items = INDUSTRIES[group];
    const allSelected = items.every((i) => draft.selectedIndustries.includes(i));
    update({
      selectedIndustries: allSelected
        ? draft.selectedIndustries.filter((x) => !items.includes(x))
        : [...new Set([...draft.selectedIndustries, ...items])],
    });
  };

  const totalCount = countTotal(draft);
  const summary = generateSummary(draft);

  const handleConfirm = () => {
    onChange(draft);
    onOpenChange(false);
  };

  const handleReset = () => {
    setDraft(defaultStockFilterConfig());
  };

  // Reset draft when dialog opens with fresh value
  const handleOpenChange = (o: boolean) => {
    if (o) setDraft(value);
    onOpenChange(o);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-full max-w-5xl flex-col gap-0 overflow-hidden p-0">
        {/* Header */}
        <DialogHeader className="shrink-0 border-b border-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="h-5 w-0.5 rounded-full bg-primary" />
            <DialogTitle className="text-base font-semibold tracking-tight">
              股票池静态约束配置
            </DialogTitle>
            <span className="rounded border border-primary/30 px-2 py-0.5 font-mono text-[10px] text-primary">
              A-SHARE SCREENER
            </span>
          </div>
          <p className="mt-1 pl-[18px] text-xs text-muted-foreground">
            配置筛选条件后将自动生成对应的 Tushare 数据拉取逻辑
          </p>
        </DialogHeader>

        {/* Body — 3-column grid */}
        <ScrollArea className="flex-1 overflow-auto">
          <div className="grid grid-cols-3 gap-4 p-5">

            {/* ── Left column ── */}
            <div className="flex flex-col gap-4">

              {/* 市值区间 */}
              <Panel>
                <SectionHeader
                  icon={BarChart3}
                  title="市值区间"
                  count={draft.mvPresets.length + (draft.mvCustom.enabled ? 1 : 0)}
                />
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {MV_PRESETS.map((p) => (
                    <button
                      key={p.label}
                      onClick={() => toggleMv(p.label)}
                      className={cn(
                        "flex flex-col items-start rounded border px-2.5 py-1.5 text-left transition-all",
                        draft.mvPresets.includes(p.label)
                          ? p.color
                          : "border-border bg-transparent text-muted-foreground hover:border-muted-foreground/40"
                      )}
                    >
                      <span className="text-xs font-semibold">{p.label}</span>
                      <span className="text-[10px] opacity-70">{p.range}</span>
                    </button>
                  ))}
                </div>
                {/* Custom range */}
                <button
                  onClick={() => update({ mvCustom: { ...draft.mvCustom, enabled: !draft.mvCustom.enabled } })}
                  className="mb-2 flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
                >
                  <span
                    className={cn(
                      "flex h-3.5 w-3.5 items-center justify-center rounded border text-[9px] transition-colors",
                      draft.mvCustom.enabled
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-muted-foreground/40"
                    )}
                  >
                    {draft.mvCustom.enabled && <Check className="h-2 w-2" />}
                  </span>
                  自定义区间
                </button>
                {draft.mvCustom.enabled && (
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      placeholder="最小(亿)"
                      value={draft.mvCustom.min}
                      onChange={(e) => update({ mvCustom: { ...draft.mvCustom, min: e.target.value } })}
                      className="h-8 flex-1 rounded-md border border-input bg-background px-2.5 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    <span className="text-muted-foreground">—</span>
                    <input
                      type="number"
                      placeholder="最大(亿)"
                      value={draft.mvCustom.max}
                      onChange={(e) => update({ mvCustom: { ...draft.mvCustom, max: e.target.value } })}
                      className="h-8 flex-1 rounded-md border border-input bg-background px-2.5 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                  </div>
                )}
              </Panel>

              {/* 指数成分股 */}
              <Panel>
                <SectionHeader icon={TrendingUp} title="指数成分股" count={draft.selectedIndex.length} />
                <div className="flex flex-wrap gap-1.5">
                  {INDEX_CONSTITUENTS.map((idx) => (
                    <FilterTag
                      key={idx}
                      label={idx}
                      active={draft.selectedIndex.includes(idx)}
                      onClick={() => toggleIndex(idx)}
                      colorClass="border-violet-400/40 bg-violet-400/10 text-violet-400"
                    />
                  ))}
                </div>
                <p className="mt-2.5 text-[10px] text-muted-foreground/50">多选时取并集（OR 逻辑）</p>
              </Panel>

              {/* 上市板块 */}
              <Panel>
                <SectionHeader icon={Landmark} title="上市板块" count={draft.selectedMarkets.length} />
                <div className="flex flex-wrap gap-1.5">
                  {MARKET_TYPES.map((m) => (
                    <FilterTag
                      key={m.id}
                      label={m.label}
                      active={draft.selectedMarkets.includes(m.id)}
                      onClick={() => toggleMarket(m.id)}
                      colorClass="border-orange-400/40 bg-orange-400/10 text-orange-400"
                    />
                  ))}
                </div>
              </Panel>

              {/* 流动性门槛 */}
              <Panel>
                <SectionHeader icon={Droplets} title="流动性门槛" />
                <div className="mb-3 grid grid-cols-4 gap-1">
                  {LIQUIDITY_PRESETS.map((p) => (
                    <button
                      key={p.label}
                      onClick={() => update({ liquidityPreset: p.label })}
                      className={cn(
                        "flex flex-col items-center rounded-md border py-2 text-center transition-all",
                        draft.liquidityPreset === p.label
                          ? "border-sky-400/40 bg-sky-400/10 text-sky-400"
                          : "border-border bg-muted/30 text-muted-foreground hover:border-muted-foreground/30"
                      )}
                    >
                      <span className="text-xs font-semibold">{p.label}</span>
                      <span className="mt-0.5 text-[9px] opacity-70">{p.desc}</span>
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground whitespace-nowrap">自定义日均成交额 ≥</span>
                  <input
                    type="number"
                    placeholder="亿元"
                    value={draft.liquidityCustom}
                    onChange={(e) => update({ liquidityCustom: e.target.value })}
                    className="h-7 w-20 rounded-md border border-input bg-background px-2 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                  <span className="text-[11px] text-muted-foreground">亿/日</span>
                </div>
              </Panel>
            </div>

            {/* ── Middle column: Industries ── */}
            <div>
              <Panel className="h-full">
                <SectionHeader icon={Factory} title="行业板块" count={draft.selectedIndustries.length} />
                <div className="space-y-2.5">
                  {Object.entries(INDUSTRIES).map(([group, items]) => {
                    const isExpanded = expandedGroups.includes(group);
                    const selCount = items.filter((i) => draft.selectedIndustries.includes(i)).length;
                    const allSel = selCount === items.length;
                    return (
                      <div key={group}>
                        {/* Group header */}
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <button
                            onClick={() =>
                              setExpandedGroups((prev) =>
                                prev.includes(group)
                                  ? prev.filter((x) => x !== group)
                                  : [...prev, group]
                              )
                            }
                            className="text-muted-foreground"
                          >
                            {isExpanded
                              ? <ChevronDown className="h-3.5 w-3.5" />
                              : <ChevronRight className="h-3.5 w-3.5" />}
                          </button>
                          <span className="text-xs font-semibold text-foreground/80">{group}</span>
                          {selCount > 0 && (
                            <span className="rounded-full bg-primary/15 px-1.5 font-mono text-[10px] text-primary">
                              {selCount}/{items.length}
                            </span>
                          )}
                          <button
                            onClick={() => toggleGroup(group)}
                            className={cn(
                              "ml-auto text-[10px] font-medium",
                              allSel ? "text-destructive hover:text-destructive/80" : "text-primary hover:text-primary/80"
                            )}
                          >
                            {allSel ? "清除" : "全选"}
                          </button>
                        </div>
                        {isExpanded && (
                          <div className="flex flex-wrap gap-1 pl-5">
                            {items.map((item) => (
                              <FilterTag
                                key={item}
                                label={item}
                                active={draft.selectedIndustries.includes(item)}
                                onClick={() => toggleIndustry(item)}
                                colorClass="border-emerald-400/40 bg-emerald-400/10 text-emerald-400"
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Panel>
            </div>

            {/* ── Right column ── */}
            <div className="flex flex-col gap-4">

              {/* 基础质量过滤 */}
              <Panel>
                <SectionHeader icon={ShieldCheck} title="基础质量过滤" count={countActive(draft.qualityFilters)} />
                <div className="grid grid-cols-2 gap-1.5">
                  {QUALITY_FILTERS.map((f) => (
                    <ToggleFilter
                      key={f.id}
                      label={f.label}
                      desc={f.desc}
                      checked={draft.qualityFilters[f.id] ?? false}
                      onChange={() =>
                        update({
                          qualityFilters: {
                            ...draft.qualityFilters,
                            [f.id]: !draft.qualityFilters[f.id],
                          },
                        })
                      }
                    />
                  ))}
                </div>
              </Panel>

              {/* 估值约束 */}
              <Panel>
                <SectionHeader icon={BadgeDollarSign} title="估值约束" count={countActive(draft.valuationFilters)} />
                <div className="grid grid-cols-2 gap-1.5">
                  {VALUATION_FILTERS.map((f) => (
                    <ToggleFilter
                      key={f.id}
                      label={f.label}
                      desc={f.desc}
                      checked={draft.valuationFilters[f.id] ?? false}
                      onChange={() =>
                        update({
                          valuationFilters: {
                            ...draft.valuationFilters,
                            [f.id]: !draft.valuationFilters[f.id],
                          },
                        })
                      }
                    />
                  ))}
                </div>
              </Panel>

              {/* 财务质量约束 */}
              <Panel>
                <SectionHeader icon={FileBarChart2} title="财务质量约束" count={countActive(draft.financialFilters)} />
                <div className="grid grid-cols-2 gap-1.5">
                  {FINANCIAL_FILTERS.map((f) => (
                    <ToggleFilter
                      key={f.id}
                      label={f.label}
                      desc={f.desc}
                      checked={draft.financialFilters[f.id] ?? false}
                      onChange={() =>
                        update({
                          financialFilters: {
                            ...draft.financialFilters,
                            [f.id]: !draft.financialFilters[f.id],
                          },
                        })
                      }
                    />
                  ))}
                </div>
              </Panel>
            </div>
          </div>
        </ScrollArea>

        {/* Footer summary + actions */}
        <DialogFooter className="shrink-0 border-t border-border bg-card/50 px-5 py-3">
          <div className="flex w-full items-center gap-4">
            {/* Count badge */}
            <div
              className={cn(
                "flex shrink-0 items-center gap-2.5 rounded-lg border px-3 py-2",
                totalCount > 0
                  ? "border-primary/30 bg-primary/10"
                  : "border-border bg-muted/30"
              )}
            >
              <span
                className={cn(
                  "font-mono text-2xl font-bold leading-none",
                  totalCount > 0 ? "text-primary" : "text-muted-foreground"
                )}
              >
                {totalCount}
              </span>
              <span className="text-[10px] leading-tight text-muted-foreground">
                条件<br />已选
              </span>
            </div>

            {/* Summary text */}
            <div className="min-w-0 flex-1">
              <p className="mb-0.5 text-[10px] text-muted-foreground">当前筛选配置</p>
              <p
                className={cn(
                  "truncate text-xs",
                  totalCount > 0 ? "font-mono text-foreground/80" : "text-muted-foreground/50"
                )}
              >
                {summary}
              </p>
            </div>

            {/* Action buttons */}
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleReset}
                className="gap-1.5 text-muted-foreground hover:text-foreground"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                重置
              </Button>
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                取消
              </Button>
              <Button size="sm" onClick={handleConfirm} disabled={totalCount === 0}>
                确认应用
              </Button>
            </div>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
