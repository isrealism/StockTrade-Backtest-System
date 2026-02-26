from typing import Dict, List, Optional, Any

from scipy.signal import find_peaks
import numpy as np
import pandas as pd
import time

from utils.indicators import (
    compute_kdj,
    compute_bbi,
    compute_rsv,
    compute_dif,
    compute_atr,
    compute_zx_lines,
)
from utils.filters import (
    passes_day_constraints_today,
    zx_condition_at_positions,
    bbi_deriv_uptrend,
    last_valid_ma_cross_up,
)


# --------------------------- 内部工具函数 --------------------------- #

def _find_peaks(
    df: pd.DataFrame,
    *,
    column: str = "high",
    distance: Optional[int] = None,
    prominence: Optional[float] = None,
    height: Optional[float] = None,
    width: Optional[float] = None,
    rel_height: float = 0.5,
    **kwargs: Any,
) -> pd.DataFrame:
    
    if column not in df.columns:
        raise KeyError(f"'{column}' not found in DataFrame columns: {list(df.columns)}")

    y = df[column].to_numpy()

    indices, props = find_peaks(
        y,
        distance=distance,
        prominence=prominence,
        height=height,
        width=width,
        rel_height=rel_height,
        **kwargs,
    )

    peaks_df = df.iloc[indices].copy()
    peaks_df["is_peak"] = True

    # Flatten SciPy arrays into columns (only those with same length as indices)
    for key, arr in props.items():
        if isinstance(arr, (list, np.ndarray)) and len(arr) == len(indices):
            peaks_df[f"peak_{key}"] = arr

    return peaks_df



# --------------------------- Selector 类 --------------------------- #

class BBIKDJSelector:

    """
    自适应 *BBI(导数)* + *KDJ* 选股器
        • BBI: 允许 bbi_q_threshold 比例的回撤
        • KDJ: J < threshold ；或位于历史 J 的 j_q_threshold 分位及以下
        • MACD: DIF > 0
        • 收盘价波动幅度 ≤ price_range_pct
    """

    def __init__(
        self,
        j_threshold: float = -5,
        bbi_min_window: int = 90,
        max_window: int = 90,
        price_range_pct: float = 100.0,
        bbi_q_threshold: float = 0.05,
        j_q_threshold: float = 0.10,
    ) -> None:
        self.j_threshold = j_threshold
        self.bbi_min_window = bbi_min_window
        self.max_window = max_window
        self.price_range_pct = price_range_pct
        self.bbi_q_threshold = bbi_q_threshold  # ← 原 q_threshold
        self.j_q_threshold = j_q_threshold      # ← 新增

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        """
        过滤逻辑

        Args:
            hist: 包含预计算指标的 DataFrame（从数据库读取）
        """
        # 0. 当日约束（从数据库读取）
        if hist.iloc[-1]['day_constraints_pass'] == 0:
            return False

        # 1. 收盘价波动幅度约束（最近 max_window 根 K 线）
        win = hist.tail(self.max_window)
        high, low = win["close"].max(), win["close"].min()
        if low <= 0 or (high / low - 1) > self.price_range_pct:
            return False

        # 2. BBI 上升（仍需实时判断，因为依赖窗口参数）
        if not bbi_deriv_uptrend(
            hist["bbi"],  # 直接使用数据库的 BBI 列
            min_window=self.bbi_min_window,
            max_window=self.max_window,
            q_threshold=self.bbi_q_threshold,
        ):
            return False

        # 3. KDJ 过滤 - 直接使用数据库列
        j_today = float(hist.iloc[-1]['kdj_j'])
        j_window = hist['kdj_j'].tail(self.max_window).dropna()

        if j_window.empty:
            return False
        j_quantile = float(j_window.quantile(self.j_q_threshold))

        if not (j_today < self.j_threshold or j_today <= j_quantile):
            return False

        # 4. 60日均线条件 - 直接使用数据库列
        if hist["close"].iloc[-1] < hist["ma60"].iloc[-1]:
            return False

        # 寻找最近一次"有效上穿 MA60"
        t_pos = last_valid_ma_cross_up(hist["close"], hist["ma60"], lookback_n=self.max_window)
        if t_pos is None:
            return False

        # 5. MACD：DIF > 0 - 直接使用数据库列
        if hist["dif"].iloc[-1] <= 0:
            return False

        # 6. 知行条件 - 使用数据库布尔列
        if hist.iloc[-1]['zx_close_gt_long'] == 0 or hist.iloc[-1]['zx_short_gt_long'] == 0:
            return False

        return True

    def select(
        self, date: pd.Timestamp, data: Dict[str, pd.DataFrame]
    ) -> List[str]:

        # ── 第一步：为所有股票找到截止 date 的最新一行，拼成大表 ──────────
        # 每只股票取当日（≤ date）最新一行，连同 code 记录下来
        # 同时把截断+tail后的 hist 暂存，供通过预筛的股票直接复用，避免重复切片
        latest_rows: List[pd.Series] = []
        code_to_hist: Dict[str, pd.DataFrame] = {}

        for code, df in data.items():
            # searchsorted 是 O(log n)，比 df[df["date"]<=date] 的 O(n) 快
            _idx = int(df["date"].searchsorted(date, side="right"))
            if _idx == 0:
                continue
            hist = df.iloc[:_idx].tail(self.max_window + 20)
            if hist.empty:
                continue
            row = hist.iloc[-1].copy()
            row["_code"] = code
            latest_rows.append(row)
            code_to_hist[code] = hist  # 暂存，只在通过预筛后才用

        if not latest_rows:
            return []

        # 纵向堆叠 → shape (n_stocks, n_cols)，每行是一只股票的当日数据
        latest_df = pd.DataFrame(latest_rows).set_index("_code")

        # ── 第二步：三条件向量化预筛（全列操作，无 Python 循环）─────────
        # pandas 对整列做比较，底层是 numpy C 代码
        # 5000 只股票和 1 只股票的耗时几乎相同

        # 条件 1：当日约束（precompute 已写入数据库布尔列，直接读取）
        mask = latest_df["day_constraints_pass"] == 1
        # 条件 2：知行过滤：收盘 > 长期线 且 短期线 > 长期线
        mask &= latest_df["zx_close_gt_long"] == 1
        mask &= latest_df["zx_short_gt_long"] == 1
        # 条件 3：MACD DIF > 0
        mask &= latest_df["dif"] > 0

        # 通过预筛的候选股票（通常从 5000 只降到几百只）
        candidates = latest_df.index[mask].tolist()

        # ── 第三步：只对候选股票跑完整的精细过滤 ──────────────────────────
        picks: List[str] = []

        t2 = time.time()
        for code in candidates:
            if self._passes_filters(code_to_hist[code]):
                picks.append(code)
        t3 = time.time()
        print(f"精细过滤耗时: {t3 - t2:.2f}s，候选股票数量: {len(candidates)}")

        return picks


class SuperB1Selector:

    """SuperB1 选股器

    过滤逻辑概览
    ----------------
    1. **历史匹配 (t_m)** — 在 *lookback_n* 个交易日窗口内，至少存在一日
       满足 :class:`BBIKDJSelector`。

    2. **盘整区间** — 区间 ``[t_m, date-1]`` 收盘价波动率不超过 ``close_vol_pct``。

    3. **当日下跌** — ``(close_{date-1} - close_date) / close_{date-1}``
       ≥ ``price_drop_pct``。

    4. **J 值极低** — ``J < j_threshold`` *或* 位于历史 ``j_q_threshold`` 分位。
    """

    def __init__(
        self,
        *,
        lookback_n: int = 60,
        close_vol_pct: float = 0.05,
        price_drop_pct: float = 0.03,
        j_threshold: float = -5,
        j_q_threshold: float = 0.10,
        # ↓↓↓ 新增：嵌套 BBIKDJSelector 配置
        B1_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        # ---------- 参数合法性检查 ----------
        if lookback_n < 2:
            raise ValueError("lookback_n 应 ≥ 2")
        if not (0 < close_vol_pct < 1):
            raise ValueError("close_vol_pct 应位于 (0, 1) 区间")
        if not (0 < price_drop_pct < 1):
            raise ValueError("price_drop_pct 应位于 (0, 1) 区间")
        if not (0 <= j_q_threshold <= 1):
            raise ValueError("j_q_threshold 应位于 [0, 1] 区间")
        if B1_params is None:
            raise ValueError("bbi_params没有给出")

        # ---------- 基本参数 ----------
        self.lookback_n = lookback_n
        self.close_vol_pct = close_vol_pct
        self.price_drop_pct = price_drop_pct
        self.j_threshold = j_threshold
        self.j_q_threshold = j_q_threshold

        # ---------- 内部 BBIKDJSelector ----------
        self.bbi_selector = BBIKDJSelector(**(B1_params or {}))

        # 为保证给 BBIKDJSelector 提供足够历史，预留额外缓冲
        self._extra_for_bbi = self.bbi_selector.max_window + 20

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        """
        过滤逻辑
        """
        if len(hist) < 2:
            return False

        # 0. 当日约束（从数据库读取）
        if hist.iloc[-1]['day_constraints_pass'] == 0:
            return False

        # 1. 数据量判断
        if len(hist) < self.lookback_n + self._extra_for_bbi:
            return False

        # 2. 搜索满足 BBIKDJ 的 t_m（内部选股器会自动使用数据库模式）
        lb_hist = hist.tail(self.lookback_n + 1)
        tm_idx: int | None = None
        for idx in lb_hist.index[:-1]:
            if self.bbi_selector._passes_filters(hist.loc[:idx]):
                tm_idx = idx
                stable_seg = hist.loc[tm_idx : hist.index[-2], "close"]
                if len(stable_seg) < 3:
                    tm_idx = None
                    break
                high, low = stable_seg.max(), stable_seg.min()
                if low <= 0 or (high / low - 1) > self.close_vol_pct:
                    tm_idx = None
                    continue
                else:
                    break
        if tm_idx is None:
            return False

        # 3. 在 t_m 当日检查知行条件 - 使用数据库布尔列
        tm_pos = hist.index.get_loc(tm_idx)
        if hist.iloc[tm_pos]['zx_close_gt_long'] == 0 or hist.iloc[tm_pos]['zx_short_gt_long'] == 0:
            return False

        # 4. 当日相对前一日跌幅
        close_today, close_prev = hist["close"].iloc[-1], hist["close"].iloc[-2]
        if close_prev <= 0 or (close_prev - close_today) / close_prev < self.price_drop_pct:
            return False

        # 5. J 值极低 - 直接使用数据库列
        j_today = float(hist.iloc[-1]['kdj_j'])
        j_window = hist['kdj_j'].iloc[-self.lookback_n:].dropna()
        j_q_val = float(j_window.quantile(self.j_q_threshold)) if not j_window.empty else np.nan
        if not (j_today < self.j_threshold or j_today <= j_q_val):
            return False

        # 6. 当日仅要求【短期线>长期线】- 使用数据库布尔列
        if hist.iloc[-1]['zx_short_gt_long'] == 0:
            return False

        return True

    def select(self, date: pd.Timestamp, data: Dict[str, pd.DataFrame]) -> List[str]:        
        picks: List[str] = []
        min_len = self.lookback_n + self._extra_for_bbi

        for code, df in data.items():
            hist = df[df["date"] <= date].tail(min_len)
            if len(hist) < min_len:
                continue
            if self._passes_filters(hist):
                picks.append(code)

        return picks


class PeakKDJSelector:

    """
    Peaks + KDJ 选股器    
    """

    def __init__(
        self,
        j_threshold: float = -5,
        max_window: int = 90,
        fluc_threshold: float = 0.03,
        gap_threshold: float = 0.02,
        j_q_threshold: float = 0.10,
    ) -> None:
        self.j_threshold = j_threshold
        self.max_window = max_window
        self.fluc_threshold = fluc_threshold  # 当日↔peak_(t-n) 波动率上限
        self.gap_threshold = gap_threshold    # oc_prev 必须高于区间最低收盘价的比例
        self.j_q_threshold = j_q_threshold

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        """
        过滤逻辑
        """
        if hist.empty:
            return False

        # 0. 当日约束（从数据库读取）
        if hist.iloc[-1]['day_constraints_pass'] == 0:
            return False

        hist = hist.copy().sort_values("date")
        hist["oc_max"] = hist[["open", "close"]].max(axis=1)

        # 1. 提取 peaks（需要实时计算）
        peaks_df = _find_peaks(
            hist,
            column="oc_max",
            distance=6,
            prominence=0.5,
        )

        date_today = hist.iloc[-1]["date"]
        peaks_df = peaks_df[peaks_df["date"] < date_today]
        if len(peaks_df) < 2:
            return False

        peak_t = peaks_df.iloc[-1]
        peaks_list = peaks_df.reset_index(drop=True)
        oc_t = peak_t.oc_max
        total_peaks = len(peaks_list)

        # 2. 回溯寻找 peak_(t-n)
        target_peak = None
        for idx in range(total_peaks - 2, -1, -1):
            peak_prev = peaks_list.loc[idx]
            oc_prev = peak_prev.oc_max
            if oc_t <= oc_prev:
                continue

            if total_peaks >= 3 and idx < total_peaks - 2:
                inter_oc = peaks_list.loc[idx + 1 : total_peaks - 2, "oc_max"]
                if not (inter_oc < oc_prev).all():
                    continue

            date_prev = peak_prev.date
            mask = (hist["date"] > date_prev) & (hist["date"] < peak_t.date)
            min_close = hist.loc[mask, "close"].min()
            if pd.isna(min_close):
                continue
            if oc_prev <= min_close * (1 + self.gap_threshold):
                continue

            target_peak = peak_prev
            break

        if target_peak is None:
            return False

        # 3. 当日收盘价波动率
        close_today = hist.iloc[-1]["close"]
        fluc_pct = abs(close_today - target_peak.close) / target_peak.close
        if fluc_pct > self.fluc_threshold:
            return False

        # 4. KDJ 过滤 - 直接使用数据库列
        j_today = float(hist.iloc[-1]['kdj_j'])
        j_window = hist['kdj_j'].tail(self.max_window).dropna()
        if j_window.empty:
            return False
        j_quantile = float(j_window.quantile(self.j_q_threshold))
        if not (j_today < self.j_threshold or j_today <= j_quantile):
            return False

        # 5. 知行条件 - 使用数据库布尔列
        if hist.iloc[-1]['zx_close_gt_long'] == 0 or hist.iloc[-1]['zx_short_gt_long'] == 0:
            return False

        return True

    def select(
        self,
        date: pd.Timestamp,
        data: Dict[str, pd.DataFrame],
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            hist = hist.tail(self.max_window + 20)  # 额外缓冲
            if self._passes_filters(hist):
                picks.append(code)
        return picks


class BBIShortLongSelector:

    """
    BBI 上升 + 短/长期 RSV 条件 + DIF > 0 选股器
    """

    def __init__(
        self,
        n_short: int = 3,
        n_long: int = 21,
        m: int = 3,
        bbi_min_window: int = 90,
        max_window: int = 150,
        bbi_q_threshold: float = 0.05,
        upper_rsv_threshold: float = 75,
        lower_rsv_threshold: float = 25,
    ) -> None:
        if m < 2:
            raise ValueError("m 必须 ≥ 2")
        self.n_short = n_short
        self.n_long = n_long
        self.m = m
        self.bbi_min_window = bbi_min_window
        self.max_window = max_window
        self.bbi_q_threshold = bbi_q_threshold
        self.upper_rsv_threshold = upper_rsv_threshold
        self.lower_rsv_threshold = lower_rsv_threshold

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        """
        过滤逻辑
        """
        # 0. 当日约束（从数据库读取）
        if hist.iloc[-1]['day_constraints_pass'] == 0:
            return False

        # 1. BBI 上升（仍需实时判断，因为依赖窗口参数）
        if not bbi_deriv_uptrend(
            hist["bbi"],  # 直接使用数据库的 BBI 列
            min_window=self.bbi_min_window,
            max_window=self.max_window,
            q_threshold=self.bbi_q_threshold,
        ):
            return False

        # 2. 读取预计算 RSV（优先使用数据库列，缺失时实时计算并发出警告）
        import warnings
        rsv_short_col = f'rsv_{self.n_short}'
        rsv_long_col  = f'rsv_{self.n_long}'
        hist = hist.copy()
        if rsv_short_col in hist.columns:
            hist["RSV_short"] = hist[rsv_short_col]
        else:
            warnings.warn(
                f"预计算数据库缺少列 '{rsv_short_col}'，已回退到实时计算。"
                f"建议在 precompute_indicators.py 中添加 n={self.n_short} 的 RSV 计算。",
                UserWarning, stacklevel=2,
            )
            hist["RSV_short"] = compute_rsv(hist, self.n_short)
        if rsv_long_col in hist.columns:
            hist["RSV_long"] = hist[rsv_long_col]
        else:
            warnings.warn(
                f"预计算数据库缺少列 '{rsv_long_col}'，已回退到实时计算。"
                f"建议在 precompute_indicators.py 中添加 n={self.n_long} 的 RSV 计算。",
                UserWarning, stacklevel=2,
            )
            hist["RSV_long"] = compute_rsv(hist, self.n_long)

        if len(hist) < self.m:
            return False

        win = hist.iloc[-self.m :]
        long_ok = (win["RSV_long"] >= self.upper_rsv_threshold).all()

        short_series = win["RSV_short"]

        # 短期 RSV 模式检测
        mask_upper = short_series >= self.upper_rsv_threshold
        mask_lower = short_series < self.lower_rsv_threshold

        has_upper_then_lower = False
        if mask_upper.any():
            upper_indices = np.where(mask_upper.to_numpy())[0]
            for i in upper_indices:
                if i + 1 < len(short_series) and mask_lower.iloc[i + 1 :].any():
                    has_upper_then_lower = True
                    break

        end_ok = short_series.iloc[-1] >= self.upper_rsv_threshold

        if not (long_ok and has_upper_then_lower and end_ok):
            return False

        # 3. MACD：DIF > 0 - 直接使用数据库列
        if hist["dif"].iloc[-1] <= 0:
            return False

        # 4. 知行条件 - 使用数据库布尔列
        if hist.iloc[-1]['zx_close_gt_long'] == 0 or hist.iloc[-1]['zx_short_gt_long'] == 0:
            return False

        return True

    def select(
        self,
        date: pd.Timestamp,
        data: Dict[str, pd.DataFrame],
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            # 预留足够长度：RSV 计算窗口 + BBI 检测窗口 + m
            need_len = (
                max(self.n_short, self.n_long)
                + self.bbi_min_window
                + self.m
            )
            hist = hist.tail(max(need_len, self.max_window))
            if self._passes_filters(hist):
                picks.append(code)
        return picks


class MA60CrossVolumeWaveSelector:

    """
    条件：
    1) 当日 J 绝对低或相对低（J < j_threshold 或 J ≤ 近 max_window 根 J 的 j_q_threshold 分位）
    2) 最近 lookback_n 内，存在一次“有效上穿 MA60”（t-1 收盘 < MA60, t 收盘 ≥ MA60）；
       且从该上穿日 T 到今天的“上涨波段”日均成交量 ≥ 上穿前等长窗口的日均成交量 * vol_multiple
       —— 上涨波段定义为 [T, today] 间的所有交易日（不做趋势单调性强约束，稳健且可复现）
    3) 近 ma60_slope_days（默认 5）个交易日的 MA60 回归斜率 > 0
    """

    def __init__(
        self,
        *,
        lookback_n: int = 60,
        vol_multiple: float = 1.5,
        j_threshold: float = -5.0,
        j_q_threshold: float = 0.10,
        ma60_slope_days: int = 5,
        max_window: int = 120,   # 用于计算 J 分位
    ) -> None:
        if lookback_n < 2:
            raise ValueError("lookback_n 应 ≥ 2")
        if not (0.0 <= j_q_threshold <= 1.0):
            raise ValueError("j_q_threshold 应位于 [0,1]")
        if ma60_slope_days < 2:
            raise ValueError("ma60_slope_days 应 ≥ 2")
        self.lookback_n = lookback_n
        self.vol_multiple = vol_multiple
        self.j_threshold = j_threshold
        self.j_q_threshold = j_q_threshold
        self.ma60_slope_days = ma60_slope_days
        self.max_window = max_window

    def _ma_slope_positive(series: pd.Series, days: int) -> bool:
        """对最近 days 个点做一阶线性回归，斜率 > 0 判为正"""
        seg = series.dropna().tail(days)
        if len(seg) < days:
            return False
        x = np.arange(len(seg), dtype=float)
        # 线性回归（最小二乘）：斜率 k
        k, _ = np.polyfit(x, seg.values.astype(float), 1)
        return bool(k > 0)

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        """
        过滤逻辑
        """
        if hist.empty:
            return False

        hist = hist.copy().sort_values("date")
        min_len = max(60 + self.lookback_n + self.ma60_slope_days, self.max_window + 5)
        if len(hist) < min_len:
            return False

        # 0. 当日约束（从数据库读取）
        if hist.iloc[-1]['day_constraints_pass'] == 0:
            return False

        # 1. KDJ 过滤 - 直接使用数据库列
        j_today = float(hist.iloc[-1]['kdj_j'])
        j_window = hist['kdj_j'].tail(self.max_window).dropna()
        if j_window.empty:
            return False
        j_q_val = float(j_window.quantile(self.j_q_threshold))

        if not (j_today < self.j_threshold or j_today <= j_q_val):
            return False

        # 2. MA60 及有效上穿 - 直接使用数据库列
        if hist["close"].iloc[-1] < hist["ma60"].iloc[-1]:
            return False

        t_pos = last_valid_ma_cross_up(hist["close"], hist["ma60"], lookback_n=self.lookback_n)
        if t_pos is None:
            return False

        # 3. 成交量波段分析（使用原始 volume 列）
        seg_T_to_today = hist.iloc[t_pos:]
        if seg_T_to_today.empty:
            return False

        tmax_label = seg_T_to_today["high"].idxmax()
        int_pos_T = t_pos
        int_pos_Tmax = hist.index.get_loc(tmax_label)

        if int_pos_Tmax < int_pos_T:
            return False

        wave = hist.iloc[int_pos_T : int_pos_Tmax + 1]
        wave_len = len(wave)
        if wave_len < 3:
            return False

        # 成交量比较
        avg_wave_vol = wave["volume"].mean()
        pre_start = max(0, int_pos_T - wave_len)
        pre_wave = hist.iloc[pre_start : int_pos_T]
        if len(pre_wave) == 0:
            return False

        avg_pre_vol = pre_wave["volume"].mean()
        if avg_pre_vol <= 0 or avg_wave_vol < self.vol_multiple * avg_pre_vol:
            return False

        # 4. MA60 斜率 > 0（需要实时计算）
        if not self._ma_slope_positive(hist["ma60"], self.ma60_slope_days):
            return False

        # 5. 知行条件 - 使用数据库布尔列
        if hist.iloc[-1]['zx_close_gt_long'] == 0 or hist.iloc[-1]['zx_short_gt_long'] == 0:
            return False

        return True

    def select(self, date: pd.Timestamp, data: Dict[str, pd.DataFrame]) -> List[str]:
        picks: List[str] = []
        # 给足 60 日均线与量能比较的历史长度
        need_len = max(60 + self.lookback_n + self.ma60_slope_days, self.max_window + 20)
        for code, df in data.items():
            hist = df[df["date"] <= date].tail(need_len)
            if len(hist) < need_len:
                continue
            if self._passes_filters(hist):
                picks.append(code)
        return picks


class BigBullishVolumeSelector:    

    def __init__(
        self,
        *,
        up_pct_threshold: float = 0.04,       # 长阳阈值：例如 0.04 表示涨幅>4%
        upper_wick_pct_max: float = 0.5,      # 上影线比例上限（口径由 wick_mode 决定）
        vol_lookback_n: int = 20,             # 放量比较的历史天数 n
        vol_multiple: float = 1.5,            # 放量倍数阈值
        min_history: int | None = None,       # 最少历史长度（默认自动 = vol_lookback_n + 2）
        require_bullish_close: bool = True,   # 可选：要求当日收阳（close >= open）
        ignore_zero_volume: bool = True,      # 计算均量时是否忽略 volume=0
        close_lt_zxdq_mult: float = 1.0,      # 例如 1.0 表示 close < zxdq；1.02 表示 close < 1.02*zxdq
    ) -> None:
        if up_pct_threshold <= 0:
            raise ValueError("up_pct_threshold 应 > 0")
        if upper_wick_pct_max < 0:
            raise ValueError("upper_wick_pct_max 应 >= 0")
        if vol_lookback_n < 1:
            raise ValueError("vol_lookback_n 应 >= 1")
        if vol_multiple <= 0:
            raise ValueError("vol_multiple 应 > 0")
        if close_lt_zxdq_mult <= 0:
            raise ValueError("close_lt_zxdq_mult 应 > 0")

        self.up_pct_threshold = float(up_pct_threshold)
        self.upper_wick_pct_max = float(upper_wick_pct_max)
        self.vol_lookback_n = int(vol_lookback_n)
        self.vol_multiple = float(vol_multiple)
        self.require_bullish_close = bool(require_bullish_close)
        self.ignore_zero_volume = bool(ignore_zero_volume)
        self.close_lt_zxdq_mult = float(close_lt_zxdq_mult)
        self.min_history = int(min_history) if min_history is not None else (self.vol_lookback_n + 2)

    def _to_float(x) -> float:
        try:
            return float(x)
        except Exception:
            return float("nan")

    def _upper_wick_pct(self, o: float, h: float, c: float) -> float:
        return (h - max(o, c)) / max(o, c)

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        """
        过滤逻辑
        """
        if hist is None or hist.empty:
            return False

        hist = hist.sort_values("date").copy()

        if len(hist) < self.min_history:
            return False
        if len(hist) < (self.vol_lookback_n + 2):
            return False

        today = hist.iloc[-1]
        prev = hist.iloc[-2]

        oT = self._to_float(today.get("open"))
        hT = self._to_float(today.get("high"))
        lT = self._to_float(today.get("low"))
        cT = self._to_float(today.get("close"))
        vT = self._to_float(today.get("volume"))
        cP = self._to_float(prev.get("close"))

        # 基础合法性
        if not (np.isfinite(oT) and np.isfinite(hT) and np.isfinite(lT) and np.isfinite(cT) and np.isfinite(vT) and np.isfinite(cP)):
            return False
        if cP <= 0 or cT <= 0:
            return False
        if hT < max(oT, cT) or lT > min(oT, cT):
            return False

        # (可选) 要求当日收阳
        if self.require_bullish_close and not (cT >= oT):
            return False

        # 1) 长阳：涨幅 > 阈值
        pct_chg = cT / cP - 1.0
        if pct_chg <= self.up_pct_threshold:
            return False

        # 2) 上影线百分比 < 阈值
        wick_pct = self._upper_wick_pct(oT, hT, cT)
        if not np.isfinite(wick_pct):
            return False
        if wick_pct >= self.upper_wick_pct_max:
            return False

        # 3) 放量：当日成交量 > 前 n 日均量 * 倍数
        vol_hist = hist["volume"].iloc[-(self.vol_lookback_n + 1):-1].astype(float)
        if self.ignore_zero_volume:
            vol_hist = vol_hist.replace(0, np.nan).dropna()

        if len(vol_hist) < max(3, int(self.vol_lookback_n * 0.6)):
            return False

        avg_vol = float(vol_hist.mean())
        if not (np.isfinite(avg_vol) and avg_vol > 0):
            return False

        if vT < self.vol_multiple * avg_vol:
            return False

        # 4) 偏离短线小于阈值 - 直接使用数据库列
        try:
            zxdq_T = float(hist.iloc[-1]['zxdq'])
        except Exception:
            zxdq_T = float("nan")

        if not np.isfinite(zxdq_T):
            return False
        else:
            if not (cT < zxdq_T * self.close_lt_zxdq_mult):
                return False

        return True

    def select(self, date: pd.Timestamp, data: Dict[str, pd.DataFrame]) -> List[str]:
        picks: List[str] = []
        need_len = max(self.min_history, self.vol_lookback_n + 2)

        for code, df in data.items():
            if df is None or df.empty:
                continue
            hist = df[df["date"] <= date].tail(need_len)
            if len(hist) < need_len:
                continue
            if self._passes_filters(hist):
                picks.append(code)

        return picks