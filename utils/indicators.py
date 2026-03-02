"""
Technical indicator calculations.

Centralized location for all indicator functions used by selectors.
Extracted from Selector.py to reduce code duplication.
"""

import numpy as np
import pandas as pd
from typing import Tuple


def compute_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """
    Calculate KDJ indicator (Stochastic oscillator variant).

    Args:
        df: DataFrame with OHLC data (must have 'high', 'low', 'close' columns)
        n: Period for calculation (default: 9)

    Returns:
        DataFrame with K, D, J columns added

    Formula:
        RSV = (Close - LLV(Low, N)) / (HHV(High, N) - LLV(Low, N)) * 100
        K = EMA(RSV, 2/3)  # Initial K = 50
        D = EMA(K, 2/3)    # Initial D = 50
        J = 3K - 2D
    """
    if df.empty:
        return df.assign(K=np.nan, D=np.nan, J=np.nan)

    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()

    # Avoid division by zero: when high == low (flat price), use neutral RSV of 50
    price_range = high_n - low_n
    rsv = np.where(
        price_range > 1e-6,  # Non-zero range
        (df["close"] - low_n) / price_range * 100,
        50.0  # Neutral value when price is flat
    )

    K = np.zeros_like(rsv, dtype=float)
    D = np.zeros_like(rsv, dtype=float)
    for i in range(len(df)):
        if i == 0:
            K[i] = D[i] = 50.0
        else:
            K[i] = 2 / 3 * K[i - 1] + 1 / 3 * rsv[i]
            D[i] = 2 / 3 * D[i - 1] + 1 / 3 * K[i]
    J = 3 * K - 2 * D
    return df.assign(K=K, D=D, J=J)


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
    ma3 = df["close"].rolling(3).mean()
    ma6 = df["close"].rolling(6).mean()
    ma12 = df["close"].rolling(12).mean()
    ma24 = df["close"].rolling(24).mean()
    return (ma3 + ma6 + ma12 + ma24) / 4


def compute_rsv(df: pd.DataFrame, n: int) -> pd.Series:
    """
    Calculate RSV (Raw Stochastic Value).

    Args:
        df: DataFrame with OHLC data
        n: Period for calculation

    Returns:
        Series with RSV values

    Formula:
        RSV(N) = 100 × (C - LLV(L,N)) / (HHV(C,N) - LLV(L,N))
        - C: Current close (or HHV of close in this implementation)
        - L: Low price
    """
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_close_n = df["close"].rolling(window=n, min_periods=1).max()

    # Avoid division by zero
    price_range = high_close_n - low_n
    rsv = np.where(
        price_range > 1e-6,
        (df["close"] - low_n) / price_range * 100.0,
        50.0
    )
    return pd.Series(rsv, index=df.index)


def compute_dif(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    """
    Calculate MACD DIF line.

    Args:
        df: DataFrame with 'close' column
        fast: Fast EMA period (default: 12).
              Maps to configs.json key: macd.fast
        slow: Slow EMA period (default: 26).
              Maps to configs.json key: macd.slow

    Returns:
        Series with DIF values

    Formula:
        DIF = EMA(Close, fast) - EMA(Close, slow)
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def compute_zx_lines(
    df: pd.DataFrame,
    ema_span: int = 10,
    ma_periods: Tuple[int, int, int, int] = (14, 28, 57, 114),
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate ZX proprietary lines (知行线).

    Args:
        df: DataFrame with 'close' column
        ema_span: Span for the double-EMA short-term line (default: 10).
                  Maps to configs.json key: zx_lines.ema_span
        ma_periods: Four MA periods for the long-term line (default: (14, 28, 57, 114)).
                    Maps to configs.json key: zx_lines.ma_periods

    Returns:
        Tuple of (ZXDQ, ZXDKX)
        - ZXDQ: Short-term line  = EMA(EMA(Close, ema_span), ema_span)
        - ZXDKX: Long-term line  = mean(MA(m1), MA(m2), MA(m3), MA(m4))
    """
    close = df["close"].astype(float)

    # Short-term: double EMA
    zxdq = close.ewm(span=ema_span, adjust=False).mean().ewm(span=ema_span, adjust=False).mean()

    # Long-term: unweighted average of 4 MAs
    m1, m2, m3, m4 = ma_periods
    ma1 = close.rolling(window=m1, min_periods=m1).mean()
    ma2 = close.rolling(window=m2, min_periods=m2).mean()
    ma3 = close.rolling(window=m3, min_periods=m3).mean()
    ma4 = close.rolling(window=m4, min_periods=m4).mean()
    zxdkx = (ma1 + ma2 + ma3 + ma4) / 4.0

    return zxdq, zxdkx


def compute_ma(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Calculate simple moving average.

    Args:
        df: DataFrame with 'close' column
        period: MA period

    Returns:
        Series with MA values
    """
    return df["close"].rolling(window=period, min_periods=1).mean()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range.

    Args:
        df: DataFrame with OHLC data
        period: ATR period (default: 14)

    Returns:
        Series with ATR values

    Formula:
        TR = max(High - Low, |High - PrevClose|, |Low - PrevClose|)
        ATR = MA(TR, period)
    """
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values

    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - np.roll(close, 1)),
            np.abs(low - np.roll(close, 1))
        )
    )
    tr[0] = high[0] - low[0]  # First TR

    atr = pd.Series(tr, index=df.index).rolling(window=period, min_periods=1).mean()
    return atr