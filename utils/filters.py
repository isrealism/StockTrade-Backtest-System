"""
Common filtering functions for stock selectors.

Provides unified filtering logic shared across all selectors.

All thresholds are exposed as parameters so callers can pass values
read from configs.json, keeping every hard-coded constant configurable.
"""

import pandas as pd
import numpy as np
from typing import Optional

from .indicators import compute_zx_lines


# ─────────────────────────────────────────────
# 1. 当日约束过滤
# ─────────────────────────────────────────────

def passes_day_constraints_today(
    hist: pd.DataFrame,
    *,
    pct_limit: float = 0.02,
    amp_limit: float = 0.07,
) -> bool:
    """
    所有战法的统一当日过滤。

    Constraints
    -----------
    1. 当前交易日涨跌幅（绝对值）< pct_limit
    2. 当日振幅（High - Low）/ Low < amp_limit

    Parameters
    ----------
    hist : pd.DataFrame
        至少包含 2 行，列名 'open', 'high', 'low', 'close'。
    pct_limit : float
        涨跌幅上限（绝对值，比例，默认 0.02 即 2%）。
        对应 configs.json 中的 day_filter.pct_limit。
    amp_limit : float
        振幅上限（比例，默认 0.07 即 7%）。
        对应 configs.json 中的 day_filter.amp_limit。

    Returns
    -------
    bool
        True 表示通过约束，可以继续后续过滤。

    Notes
    -----
    - 振幅基准为当日最低价（与 Selector.py 原实现保持一致）。
    - 任何价格 <= 0 时直接返回 False。
    """
    if len(hist) < 2:
        return False

    last = hist.iloc[-1]
    prev = hist.iloc[-2]

    close_today = float(last["close"])
    close_yest  = float(prev["close"])
    high_today  = float(last["high"])
    low_today   = float(last["low"])

    if close_yest <= 0 or low_today <= 0:
        return False

    pct_chg   = abs(close_today / close_yest - 1.0)
    amplitude = (high_today - low_today) / low_today   # 振幅基准：当日 low

    return (pct_chg < pct_limit) and (amplitude < amp_limit)


# ─────────────────────────────────────────────
# 2. 知行条件过滤
# ─────────────────────────────────────────────

def zx_condition_at_positions(
    df: pd.DataFrame,
    *,
    require_close_gt_long: bool = True,
    require_short_gt_long: bool = True,
    pos: Optional[int] = None,
) -> bool:
    """
    在指定位置检查"知行约束"（ZX discipline constraints）。

    Parameters
    ----------
    df : pd.DataFrame
        历史数据，必须包含 'close' 列；以及可选的预计算列
        'zxdq', 'zxdkx'（若存在则直接读取，否则实时计算）。
    require_close_gt_long : bool
        是否要求 close > ZXDKX（长期线），默认 True。
    require_short_gt_long : bool
        是否要求 ZXDQ（短期线）> ZXDKX（长期线），默认 True。
    pos : int or None
        要检查的 iloc 位置；None 表示最新一行（当日）。

    Returns
    -------
    bool
        True 表示满足知行约束。

    Notes
    -----
    - 若 ZXDKX 或 ZXDQ 为 NaN，直接返回 False。
    - 与 Selector.py 中的同名函数签名完全对齐（单 pos 而非 list）。
    - 若 df 中已有 'zxdq'/'zxdkx' 预计算列，则跳过实时计算（高性能模式）。
    """
    if df.empty:
        return False

    if pos is None:
        pos = len(df) - 1

    if pos < 0 or pos >= len(df):
        return False

    # 优先使用预计算列，缺失时实时计算
    if "zxdq" in df.columns and "zxdkx" in df.columns:
        s     = float(df["zxdq"].iloc[pos])
        l_raw = df["zxdkx"].iloc[pos]
        l_val = float(l_raw) if pd.notna(l_raw) else float("nan")
    else:
        zxdq_s, zxdkx_s = compute_zx_lines(df)
        s     = float(zxdq_s.iloc[pos])
        l_raw = zxdkx_s.iloc[pos]
        l_val = float(l_raw) if pd.notna(l_raw) else float("nan")

    c = float(df["close"].iloc[pos])

    if not np.isfinite(l_val) or not np.isfinite(s):
        return False

    if require_close_gt_long and not (c > l_val):
        return False
    if require_short_gt_long and not (s > l_val):
        return False

    return True


# ─────────────────────────────────────────────
# 3. BBI 趋势判断
# ─────────────────────────────────────────────

def bbi_deriv_uptrend(
    bbi: pd.Series,
    *,
    min_window: int,
    max_window: Optional[int] = None,
    q_threshold: float = 0.0,
) -> bool:
    """
    判断 BBI 是否处于"整体上升"趋势（自适应窗口 + 分位数容忍）。

    Algorithm
    ---------
    令最新交易日为 T，在区间 [T-w+1, T]（min_window <= w <= max_window）内：
      1. 将 BBI 归一化：BBI_norm(t) = BBI(t) / BBI(T-w+1)
      2. 计算一阶差分 delta(t) = BBI_norm(t) - BBI_norm(t-1)
      3. 若 delta 的第 q_threshold 分位数 >= 0，则该窗口通过
    自最长窗口开始搜索，找到任意满足条件的窗口即返回 True。

    Parameters
    ----------
    bbi : pd.Series
        BBI 序列（最新值在最后一位）。
    min_window : int
        检测窗口的最小长度（必填，keyword-only）。
        对应 configs.json 中的 selector.bbi_min_window。
    max_window : int or None
        检测窗口的最大长度；None 表示不限。
        对应 configs.json 中的 selector.max_window。
    q_threshold : float
        允许一阶差分为负的比例（0 <= q_threshold <= 1），默认 0.0。
        q_threshold=0 退化为严格单调不降。
        对应 configs.json 中的 selector.bbi_q_threshold。

    Returns
    -------
    bool
        True 表示 BBI 满足上升趋势条件。

    Raises
    ------
    ValueError
        q_threshold 不在 [0, 1] 时。
    """
    if not 0.0 <= q_threshold <= 1.0:
        raise ValueError("q_threshold 必须位于 [0, 1] 区间内")

    bbi = bbi.dropna()
    if len(bbi) < min_window:
        return False

    longest = min(len(bbi), max_window) if max_window is not None else len(bbi)

    # 自最长窗口向下搜索，任意通过即返回 True
    for w in range(longest, min_window - 1, -1):
        seg   = bbi.iloc[-w:]         # 区间 [T-w+1, T]
        norm  = seg / seg.iloc[0]     # 归一化（起点 = 1）
        diffs = np.diff(norm.values)  # 一阶差分

        if np.quantile(diffs, q_threshold) >= 0:
            return True

    return False


# ─────────────────────────────────────────────
# 4. MA 有效上穿检测
# ─────────────────────────────────────────────

def last_valid_ma_cross_up(
    close: pd.Series,
    ma: pd.Series,
    lookback_n: Optional[int] = None,
) -> Optional[int]:
    """
    查找"有效上穿 MA"的最后一个位置 T：
        close[T-1] < ma[T-1]  且  close[T] >= ma[T]

    Parameters
    ----------
    close : pd.Series
        收盘价序列。
    ma : pd.Series
        移动均线序列（与 close 同索引）。
    lookback_n : int or None
        仅在最近 N 根 K 线内查找；None 表示搜索全历史。
        对应 configs.json 中的 selector.lookback_n。

    Returns
    -------
    int or None
        上穿点的 **iloc 整数位置**（可直接用于 df.iloc[pos]）；
        未找到时返回 None。

    Notes
    -----
    - 上穿判定：T-1 收盘**严格低于** MA（< 而非 <=），T 收盘**大于等于** MA。
    - 返回值为原始序列的 iloc 位置，与 Selector.py 原实现完全对齐。
    """
    n     = len(close)
    start = 1  # 至少从 1 起，需要看 T-1

    if lookback_n is not None:
        start = max(start, n - lookback_n)

    for i in range(n - 1, start - 1, -1):
        if i - 1 < 0:
            continue
        c_prev, c_now = close.iloc[i - 1], close.iloc[i]
        m_prev, m_now = ma.iloc[i - 1],    ma.iloc[i]

        if pd.notna(c_prev) and pd.notna(c_now) and pd.notna(m_prev) and pd.notna(m_now):
            if c_prev < m_prev and c_now >= m_now:   # 严格下方 -> 上穿或持平
                return i

    return None


# ─────────────────────────────────────────────
# 5. OHLC 数据有效性验证
# ─────────────────────────────────────────────

def validate_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """
    验证 OHLC 数据的自洽性并移除无效行。

    Checks
    ------
    - low  <= open  <= high
    - low  <= close <= high
    - low  >= 0（不允许负价格）

    Parameters
    ----------
    df : pd.DataFrame
        包含 'open', 'high', 'low', 'close' 列的 DataFrame。

    Returns
    -------
    pd.DataFrame
        仅保留 OHLC 逻辑自洽的行。
    """
    invalid = df[
        (df["low"]  > df["open"])  |
        (df["low"]  > df["close"]) |
        (df["high"] < df["open"])  |
        (df["high"] < df["close"]) |
        (df["low"]  < 0)
    ]

    if len(invalid) > 0:
        print(f"Warning: {len(invalid)} invalid OHLC rows detected and removed")

    return df.drop(invalid.index)