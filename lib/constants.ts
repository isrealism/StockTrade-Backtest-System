/* ── Buy Selector Descriptions (from Z哥战法详解 PDF) ── */
export const SELECTOR_DESCRIPTIONS: Record<
  string,
  { name: string; alias: string; summary: string; logic: string; params: string }
> = {
  BBIKDJSelector: {
    name: "BBIKDJSelector",
    alias: "少妇战法",
    summary: "BBI上升趋势 + KDJ超卖区入场 + MA60上穿 + DIF>0 + 知行约束",
    logic:
      "核心逻辑：股票整体趋势向好（BBI上升），近期收盘价波动不过大，短期趋势好于长期趋势，近期出现收盘价上穿60日均线，选取J值处于超卖区的时机入场。\n\n筛选条件：\n1. 满足当日过滤（涨跌幅<2%，振幅<7%）\n2. 近max_window日收盘价波动幅度约束\n3. BBI上升：通过bbi_deriv_uptrend()筛选\n4. KDJ过滤：J值<15或处于最近120天最低20%分位\n5. 上穿60日均线\n6. MACD中DIF>0\n7. 知行约束：收盘>长期线，短期>长期线",
    params:
      "j_threshold(15), j_q_threshold(0.2), bbi_min_window(20), max_window(120), price_range_pct(1.0), bbi_q_threshold(0.2)",
  },
  SuperB1Selector: {
    name: "SuperB1Selector",
    alias: "SuperB1战法",
    summary: "先发出B1信号后横盘，突然大幅下跌进入超卖区，预期反弹",
    logic:
      "核心逻辑：在前一段周期中股票发出过B1信号（少妇战法信号），但之后一直稳定横盘，当日突然大幅下跌，并处于超卖区，近期可能出现反弹。\n\n筛选条件：\n1. 满足当日过滤\n2. 保证数据量充足\n3. 搜索满足BBIKDJ筛选条件的t_m日，并在[t_m, T-1]区间中验证收盘价波动率不超过close_vol_pct\n4. 在t_m当日满足知行约束\n5. 当日收盘价相对前一日下跌不小于price_drop_pct\n6. KDJ过滤：J值<10或处于lookback_n日内相对低位\n7. 当日知行约束仅要求短期>长期",
    params:
      "lookback_n(10), close_vol_pct(0.02), price_drop_pct(0.02), j_threshold(10), j_q_threshold(0.1), B1_params(嵌套)",
  },
  BBIShortLongSelector: {
    name: "BBIShortLongSelector",
    alias: "补票战法",
    summary: "BBI多头 + 长RSV高位 + 短RSV先高后低再高 + DIF>0",
    logic:
      "核心逻辑：股票大趋势处于多头（BBI上升且DIF>0），长周期能量维持高位（长RSV>=threshold），近期利用短线波动带来的回撤（短RSV先处于高位，再进入超卖区，当日处在强势区）进行择时。\n\n筛选条件：\n1. 满足当日过滤\n2. BBI上升\n3. RSV过滤：长期RSV全部>=75，短RSV存在由高到低再到高的模式\n4. MACD：DIF>0\n5. 知行约束：收盘>长期，短期>长期",
    params:
      "n_short(5), n_long(21), m(5), bbi_min_window(2), max_window(120), bbi_q_threshold(0.2), upper_rsv_threshold(75), lower_rsv_threshold(25)",
  },
  PeakKDJSelector: {
    name: "PeakKDJSelector",
    alias: "填坑战法",
    summary: "上升趋势 + 新高>前高 + 回踩前峰收盘价 + J值低位",
    logic:
      "核心逻辑：股票处于上升趋势，最新峰值高于前一峰值，在价格回调至前一个有效波峰的收盘价附近、并且J值处于低位时进行买入。\n\n筛选条件：\n1. 满足当日过滤\n2. 调用_find_peaks找到波峰（基于K线实体顶部）\n3. 最新波峰高度 > 前向波峰高度\n4. 中间峰全部低于前向波峰\n5. 两峰之间存在明显低谷\n6. 今日收盘价在前向波峰收盘价的±3%内\n7. KDJ过滤：J<10或处于120天最低10%分位\n8. 知行约束",
    params:
      "j_threshold(10), max_window(120), fluc_threshold(0.03), j_q_threshold(0.1), gap_threshold(0.2)",
  },
  MA60CrossVolumeWaveSelector: {
    name: "MA60CrossVolumeWaveSelector",
    alias: "上穿60放量战法",
    summary: "上穿MA60 + 成交量显著放大 + J值低位",
    logic:
      "核心逻辑：寻找近期收盘价上穿60日均线，同时伴随成交量放大的股票，配合KDJ低位确认入场时机。\n\n筛选条件：\n1. 满足当日过滤\n2. 上穿MA60\n3. 成交量放大（当日量>近N日均量×vol_multiple）\n4. J值低位过滤\n5. MA60斜率为正（上升趋势）",
    params:
      "lookback_n(25), vol_multiple(1.8), j_threshold(15), j_q_threshold(0.1), ma60_slope_days(5), max_window(120)",
  },
  BigBullishVolumeSelector: {
    name: "BigBullishVolumeSelector",
    alias: "暴力K战法",
    summary: "大阳线(>6%) + 放量(>2.5x) + 收盘价<知行短期线",
    logic:
      "核心逻辑：寻找单日出现实体大阳线且伴随成交量显著放大的股票。引入知行短期趋势线约束，要求收盘价位于趋势线之下（或附近），确保入场点位于低位反弹阶段。\n\n筛选条件：\n1. 满足当日过滤\n2. 当日阳线约束：收盘>=开盘\n3. 当日涨幅>6%\n4. 上影线限制<2%\n5. 成交量验证：当日量>2.5×近20日均量\n6. 相对位置约束：收盘价<知行短期线×1.15",
    params:
      "up_pct_threshold(0.06), upper_wick_pct_max(0.02), require_bullish_close(true), close_lt_zxdq_mult(1.15), vol_lookback_n(20), vol_multiple(2.5)",
  },
};

/* ── Sell Strategy Descriptions (from Sell-Strategies PDF) ── */
export const SELL_STRATEGY_DESCRIPTIONS: Record<
  string,
  { name: string; category: string; description: string }
> = {
  KDJOverboughtExitStrategy: {
    name: "KDJ超买退场",
    category: "指标退场",
    description: "J值过高形成超买时卖出。参数：j_threshold(80), wait_for_turndown(false)。",
  },
  BBIReversalExitStrategy: {
    name: "BBI趋势反转",
    category: "指标退场",
    description: "BBI多空均线连续下跌，趋势由多转空时卖出。参数：consecutive_declines(3)。",
  },
  ZXLinesCrossDownExitStrategy: {
    name: "知行线死叉",
    category: "指标退场",
    description:
      "知行短期趋势线下穿多空线时卖出。触发条件：ZXDQ(T-1)>=ZXDKX(T-1) 且 ZXDQ(T)<ZXDKX(T)。",
  },
  MADeathCrossExitStrategy: {
    name: "均线死叉",
    category: "指标退场",
    description:
      "短期均线下穿长期均线。参数：fast_period(5), slow_period(20)。",
  },
  FixedProfitTargetStrategy: {
    name: "固定比例止盈",
    category: "止盈退场",
    description: "持仓浮盈达到预设百分比时卖出。参数：target_pct(0.15)。",
  },
  MultipleRExitStrategy: {
    name: "R倍数止盈",
    category: "止盈退场",
    description:
      "基于入场时的风险(R)计算止盈目标。参数：r_multiple(3.0), atr_period(14), stop_multiplier(2.0)。",
  },
  PercentageTrailingStopStrategy: {
    name: "百分比移动止损",
    category: "止损",
    description:
      "价格从持仓期间最高收盘价回撤一定比例后卖出。参数：trailing_pct(0.08), activate_after_profit_pct(0.0)。",
  },
  ATRTrailingStopStrategy: {
    name: "ATR移动止损",
    category: "止损",
    description:
      "利用ATR衡量波动率，价格跌破最高收盘价-N倍ATR时卖出。参数：atr_period(14), atr_multiplier(2.0)。",
  },
  ChandelierStopStrategy: {
    name: "吊灯止损",
    category: "止损",
    description:
      "基于持仓期间最高High价的ATR变体。参数：lookback_period(22), atr_period(14), atr_multiplier(3.0)。",
  },
  AdaptiveVolatilityExitStrategy: {
    name: "自适应波动率止损",
    category: "止损",
    description:
      "根据当前市场波动率所处的历史分位动态调整止损宽度。低波动收窄止损，高波动放宽止损。",
  },
  VolumeDryUpExitStrategy: {
    name: "成交量枯竭退场",
    category: "放量退场",
    description:
      "成交量连续萎缩，显著低于历史均量时卖出。参数：volume_threshold_pct(0.5), lookback_period(20), consecutive_days(3)。",
  },
  TimedExitStrategy: {
    name: "强制时间平仓",
    category: "时间到期",
    description:
      "防止资金无效占用，到达最大持仓天数后强制平仓。参数：max_holding_days(60)。",
  },
  SimpleHoldStrategy: {
    name: "永久持有",
    category: "基准",
    description: "买入后永不卖出的基准策略。",
  },
};

/* ── Sell Combo Preset Names ── */
export const SELL_COMBO_NAMES: Record<string, string> = {
  conservative_trailing: "保守追踪止损",
  aggressive_atr: "激进ATR止损",
  indicator_based: "指标退出",
  adaptive_volatility: "自适应波动率",
  chandelier_3r: "吊灯止损3R",
  zx_discipline: "知行纪律",
  simple_percentage_stop: "简单百分比止损",
  hold_forever: "永久持有",
};

/* ── Ranking Metric Labels ── */
export const RANKING_METRICS: { value: string; label: string }[] = [
  { value: "score", label: "综合评分" },
  { value: "total_return_pct", label: "总收益率" },
  { value: "win_rate_pct", label: "胜率" },
  { value: "sharpe_ratio", label: "夏普比率" },
  { value: "max_drawdown_pct", label: "最大回撤" },
];

/* ── Status Labels ── */
export const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  PENDING: { label: "等待中", color: "bg-chart-3/20 text-chart-3" },
  RUNNING: { label: "运行中", color: "bg-primary/20 text-primary" },
  COMPLETED: { label: "已完成", color: "bg-profit/20 text-profit" },
  FAILED: { label: "失败", color: "bg-loss/20 text-loss" },
  CANCELLED: { label: "已取消", color: "bg-muted-foreground/20 text-muted-foreground" },
};
