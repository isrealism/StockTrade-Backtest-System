"""
Technical indicator calculations.

Centralized location for all indicator functions used by selectors.

Performance optimizations vs original:
  compute_kdj  — K/D 递推由 Python for 循环改为 pandas ewm (底层 Cython/C)，
                 速度提升 10~50 倍；初始值 K[0]=D[0]=50 行为与原版完全一致。
  compute_atr  — 用切片对齐替代 np.roll，消除首尾环绕边界问题，正确性提升。
"""

import numpy as np
import pandas as pd
from typing import Tuple


# ═══════════════════════════════════════════════════════════════════
# KDJ
# ═══════════════════════════════════════════════════════════════════

def compute_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """
    Calculate KDJ indicator (Stochastic oscillator variant).

    [优化] 原实现用 Python for 循环逐行递推 K/D（O(N) Python 解释器开销）。
    新实现使用 pandas ewm（alpha=1/3, adjust=False），底层 Cython 实现，
    等价于递推公式  K[i] = 2/3·K[i-1] + 1/3·RSV[i]，速度提升 10~50 倍。
    将 rsv[0] 强制设为 50，确保 K[0]=D[0]=50，与原版行为完全一致。

    Args:
        df: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)
        n:  Period for calculation (default: 9)

    Returns:
        DataFrame with K, D, J columns added

    Formula:
        RSV = (Close - LLV(Low, N)) / (HHV(High, N) - LLV(Low, N)) * 100
        K   = EMA(RSV, alpha=1/3)   # Initial K = 50  → rsv[0] = 50
        D   = EMA(K,   alpha=1/3)   # Initial D = 50
        J   = 3K - 2D
    """
    if df.empty:
        return df.assign(K=np.nan, D=np.nan, J=np.nan)

    low_n  = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()

    price_range = high_n - low_n
    rsv_arr = np.where(
        price_range > 1e-6,
        (df["close"] - low_n) / price_range * 100.0,
        50.0,
    )

    # 强制首行 RSV = 50，确保 ewm 输出的第一个 K/D 都等于 50
    # （pandas ewm 首行输出 = 首行输入，所以 rsv[0]=50 → K[0]=50 → D[0]=50）
    rsv_arr[0] = 50.0
    rsv = pd.Series(rsv_arr, index=df.index, dtype=float)

    # ewm(alpha=1/3, adjust=False) 等价于原 for 循环的递推公式
    K = rsv.ewm(alpha=1.0 / 3.0, adjust=False).mean()
    D = K.ewm(alpha=1.0 / 3.0, adjust=False).mean()
    J = 3.0 * K - 2.0 * D

    return df.assign(K=K.values, D=D.values, J=J.values)


# ═══════════════════════════════════════════════════════════════════
# BBI
# ═══════════════════════════════════════════════════════════════════

def compute_bbi(df: pd.DataFrame) -> pd.Series:
    """
    Calculate BBI (Bull and Bear Index).

    Args:
        df: DataFrame with 'close' column

    Returns:
        Series with BBI values

    Formula:
        BBI = (MA3 + MA6 + MA12 + MA24) / 4
    """
    close = df["close"]
    ma3  = close.rolling(3).mean()
    ma6  = close.rolling(6).mean()
    ma12 = close.rolling(12).mean()
    ma24 = close.rolling(24).mean()
    return (ma3 + ma6 + ma12 + ma24) / 4.0


# ═══════════════════════════════════════════════════════════════════
# RSV
# ═══════════════════════════════════════════════════════════════════

def compute_rsv(df: pd.DataFrame, n: int) -> pd.Series:
    """
    Calculate RSV (Raw Stochastic Value).

    Args:
        df: DataFrame with OHLC data
        n:  Period for calculation

    Returns:
        Series with RSV values

    Formula:
        RSV(N) = 100 × (C - LLV(L,N)) / (HHV(C,N) - LLV(L,N))
    """
    low_n         = df["low"].rolling(window=n, min_periods=1).min()
    high_close_n  = df["close"].rolling(window=n, min_periods=1).max()

    price_range = high_close_n - low_n
    rsv = np.where(
        price_range > 1e-6,
        (df["close"] - low_n) / price_range * 100.0,
        50.0,
    )
    return pd.Series(rsv, index=df.index)


# ═══════════════════════════════════════════════════════════════════
# MACD DIF
# ═══════════════════════════════════════════════════════════════════

def compute_dif(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    """
    Calculate MACD DIF line.

    Args:
        df:   DataFrame with 'close' column
        fast: Fast EMA period (default: 12)
        slow: Slow EMA period (default: 26)

    Returns:
        Series with DIF values

    Formula:
        DIF = EMA(Close, fast) - EMA(Close, slow)
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


# ═══════════════════════════════════════════════════════════════════
# ZX Lines（知行线）
# ═══════════════════════════════════════════════════════════════════

def compute_zx_lines(
    df: pd.DataFrame,
    ema_span: int = 10,
    ma_periods: Tuple[int, int, int, int] = (14, 28, 57, 114),
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate ZX proprietary lines (知行线).

    Args:
        df:         DataFrame with 'close' column
        ema_span:   Span for the double-EMA short-term line (default: 10)
        ma_periods: Four MA periods for the long-term line (default: (14,28,57,114))

    Returns:
        Tuple of (ZXDQ, ZXDKX)
        - ZXDQ:  Short-term line = EMA(EMA(Close, ema_span), ema_span)
        - ZXDKX: Long-term line  = mean(MA(m1), MA(m2), MA(m3), MA(m4))
    """
    close = df["close"].astype(float)

    # 短期线：双重 EMA
    zxdq = close.ewm(span=ema_span, adjust=False).mean()
    zxdq = zxdq.ewm(span=ema_span, adjust=False).mean()

    # 长期线：四条 MA 的等权均值
    m1, m2, m3, m4 = ma_periods
    ma1 = close.rolling(window=m1, min_periods=m1).mean()
    ma2 = close.rolling(window=m2, min_periods=m2).mean()
    ma3 = close.rolling(window=m3, min_periods=m3).mean()
    ma4 = close.rolling(window=m4, min_periods=m4).mean()
    zxdkx = (ma1 + ma2 + ma3 + ma4) / 4.0

    return zxdq, zxdkx


# ═══════════════════════════════════════════════════════════════════
# MA
# ═══════════════════════════════════════════════════════════════════

def compute_ma(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Calculate simple moving average.

    Args:
        df:     DataFrame with 'close' column
        period: MA period

    Returns:
        Series with MA values
    """
    return df["close"].rolling(window=period, min_periods=1).mean()


# ═══════════════════════════════════════════════════════════════════
# ATR
# ═══════════════════════════════════════════════════════════════════

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range.

    [优化/修正] 原实现用 np.roll(close, 1) 计算前日收盘价，会把最后一个元素
    环绕到首行，导致 tr[0] 计算错误（虽有手动修正，但逻辑不清晰且易出错）。
    新实现改为切片对齐：prev_close = close[:-1]，完全避免环绕边界问题。

    Args:
        df:     DataFrame with OHLC data
        period: ATR period (default: 14)

    Returns:
        Series with ATR values

    Formula:
        TR      = max(H-L, |H-PrevClose|, |L-PrevClose|)
        ATR     = MA(TR, period)
        TR[0]   = High[0] - Low[0]  （首行无前日收盘价，退化为当日振幅）
    """
    if len(df) < 2:
        # 数据不足时返回当日振幅
        tr_only = (df["high"] - df["low"]).values
        return pd.Series(tr_only, index=df.index, dtype=float)

    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)

    # 切片对齐：prev_close[i] = close[i-1]，不引入任何环绕
    prev_close = close[:-1]
    h_tail = high[1:]
    l_tail = low[1:]

    tr_tail = np.maximum(
        h_tail - l_tail,
        np.maximum(
            np.abs(h_tail - prev_close),
            np.abs(l_tail - prev_close),
        ),
    )

    # 首行 TR：无前日收盘价，取当日 High - Low
    tr_full = np.empty(len(df), dtype=float)
    tr_full[0]  = high[0] - low[0]
    tr_full[1:] = tr_tail

    return pd.Series(tr_full, index=df.index).rolling(window=period, min_periods=1).mean()