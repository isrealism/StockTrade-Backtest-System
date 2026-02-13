"""
Common filtering functions for stock selectors.

Provides unified filtering logic shared across all selectors.
"""

import pandas as pd
import numpy as np
from typing import Optional
from .indicators import compute_zx_lines


def passes_day_constraints_today(hist: pd.DataFrame) -> bool:
    """
    Check if today's price action passes daily constraints.

    Constraints:
    - Price change < 2% (not too volatile)
    - Amplitude < 7% (range within reasonable limit)

    Args:
        hist: Historical data (must have at least 2 rows)

    Returns:
        True if constraints are satisfied

    Note:
        This is a unified filter applied to ALL strategies for consistency.
    """
    if len(hist) < 2:
        return False

    today = hist.iloc[-1]
    yesterday = hist.iloc[-2]

    # Calculate price change
    pct_change = (today["close"] / yesterday["close"] - 1) * 100

    # Calculate amplitude
    amplitude = (today["high"] - today["low"]) / yesterday["close"] * 100

    # Apply constraints
    if abs(pct_change) >= 2:
        return False
    if amplitude >= 7:
        return False

    return True


def zx_condition_at_positions(
    hist: pd.DataFrame,
    positions: list,
    require_close_gt_long: bool = True,
    require_short_gt_long: bool = True
) -> bool:
    """
    Check "知行约束" (ZX discipline constraints) at specified positions.

    Validates market discipline conditions:
    - At reference points: close > long-term line AND short-term > long-term
    - Ensures trades follow established trends

    Args:
        hist: Historical data
        positions: List of iloc positions to check (e.g., [t_pos])
        require_close_gt_long: Require close > ZXDKX (long-term line)
        require_short_gt_long: Require ZXDQ > ZXDKX

    Returns:
        True if all positions satisfy constraints

    Note:
        This is a critical filter ensuring all strategies maintain discipline.
    """
    if hist.empty or not positions:
        return False

    # Compute ZX lines
    zxdq, zxdkx = compute_zx_lines(hist)

    for pos in positions:
        if pos < 0 or pos >= len(hist):
            return False

        close = hist["close"].iloc[pos]
        zxdq_val = zxdq.iloc[pos]
        zxdkx_val = zxdkx.iloc[pos]

        # Check constraints
        if require_close_gt_long and (pd.isna(zxdkx_val) or close <= zxdkx_val):
            return False

        if require_short_gt_long and (pd.isna(zxdq_val) or pd.isna(zxdkx_val) or zxdq_val <= zxdkx_val):
            return False

    return True


def bbi_deriv_uptrend(
    bbi: pd.Series,
    window: int = 5,
    min_slope: float = 0.0003,
    tolerance_pct: float = 0.005
) -> bool:
    """
    Check if BBI is in adaptive uptrend with tolerable pullback.

    Args:
        bbi: BBI series
        window: Window for slope calculation (default: 5)
        min_slope: Minimum slope for uptrend (default: 0.0003)
        tolerance_pct: Allowed pullback percentage (default: 0.5%)

    Returns:
        True if BBI shows uptrend pattern

    Logic:
        - Recent BBI should be higher than earlier values (with tolerance)
        - Slope should be positive and above minimum
    """
    if bbi.empty or len(bbi) < window:
        return False

    recent_bbi = bbi.tail(window)
    if recent_bbi.isna().all():
        return False

    # Get first and last valid values
    valid_values = recent_bbi.dropna()
    if len(valid_values) < 2:
        return False

    first_val = valid_values.iloc[0]
    last_val = valid_values.iloc[-1]

    # Allow small pullback
    if last_val < first_val * (1 - tolerance_pct):
        return False

    # Check slope
    slope = (last_val - first_val) / first_val / len(valid_values)
    if slope < min_slope:
        return False

    return True


def last_valid_ma_cross_up(
    close: pd.Series,
    ma: pd.Series,
    lookback_n: int = 120
) -> Optional[int]:
    """
    Find the last valid MA crossover position (close crosses above MA).

    Args:
        close: Close price series
        ma: Moving average series
        lookback_n: Maximum lookback window

    Returns:
        iloc position of last crossover, or None if not found

    Logic:
        - Searches from recent to past
        - Finds where close crosses above MA (previous day below, current day above)
    """
    if len(close) < 2 or len(ma) < 2:
        return None

    # Get recent data
    recent_close = close.tail(lookback_n)
    recent_ma = ma.tail(lookback_n)

    # Find crossovers (close[i-1] <= ma[i-1] and close[i] > ma[i])
    for i in range(len(recent_close) - 1, 0, -1):
        if pd.isna(recent_ma.iloc[i]) or pd.isna(recent_close.iloc[i]):
            continue
        if pd.isna(recent_ma.iloc[i - 1]) or pd.isna(recent_close.iloc[i - 1]):
            continue

        # Crossover detected
        if recent_close.iloc[i - 1] <= recent_ma.iloc[i - 1] and recent_close.iloc[i] > recent_ma.iloc[i]:
            # Return position in original series
            return close.index.get_loc(recent_close.index[i])

    return None


def validate_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate OHLC data consistency.

    Checks:
    - low <= open <= high
    - low <= close <= high
    - No negative prices

    Args:
        df: DataFrame with OHLC columns

    Returns:
        DataFrame with only valid rows

    Raises:
        Warning if invalid rows are found
    """
    invalid = df[
        (df['low'] > df['open']) |
        (df['low'] > df['close']) |
        (df['high'] < df['open']) |
        (df['high'] < df['close']) |
        (df['low'] < 0)
    ]

    if len(invalid) > 0:
        print(f"Warning: {len(invalid)} invalid OHLC rows detected and removed")

    return df.drop(invalid.index)
