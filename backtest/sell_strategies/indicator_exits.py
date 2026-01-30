"""
Indicator-based exit strategies.

Implements 4 technical indicator exit strategies:
1. KDJOverboughtExitStrategy - Exit on KDJ overbought
2. BBIReversalExitStrategy - Exit on BBI downtrend
3. ZXLinesCrossDownExitStrategy - Exit on ZX lines bearish cross
4. MADeathCrossExitStrategy - Exit on MA death cross
"""

from datetime import datetime
from typing import Tuple
import pandas as pd
import numpy as np

from .base import SellStrategy
from ..data_structures import Position


class KDJOverboughtExitStrategy(SellStrategy):
    """
    Exit on KDJ overbought signal.

    Triggers when J > threshold or J > Nth percentile.

    Optional: Wait for J to turn down before exiting.
    """

    def __init__(
        self,
        j_threshold: float = 80,
        wait_for_turndown: bool = False,
        use_percentile: bool = False,
        percentile: float = 90,
        **params
    ):
        """
        Initialize strategy.

        Args:
            j_threshold: J value threshold (e.g., 80)
            wait_for_turndown: If True, wait for J to turn down
            use_percentile: If True, use percentile instead of fixed threshold
            percentile: Percentile for overbought (e.g., 90)
            **params: Additional parameters
        """
        super().__init__(**params)
        self.j_threshold = j_threshold
        self.wait_for_turndown = wait_for_turndown
        self.use_percentile = use_percentile
        self.percentile = percentile

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if KDJ overbought."""
        # Calculate KDJ
        kdj = self._compute_kdj(hist_data )

        if kdj is None or len(kdj) == 0:
            return False, ""

        # Merge with hist_data
        hist = hist_data.copy()
        hist = pd.concat([hist, kdj], axis=1)

        if 'J' not in hist.columns or hist['J'].isna().all():
            return False, ""

        current_j = hist['J'].iloc[-1]

        if pd.isna(current_j):
            return False, ""

        # Determine threshold
        if self.use_percentile:
            # Get data since entry for percentile calculation
            entry_idx = hist[hist['date'] == position.entry_date].index
            if len(entry_idx) > 0:
                data_since_entry = hist.loc[entry_idx[0]:]
                threshold = data_since_entry['J'].quantile(self.percentile / 100.0)
            else:
                threshold = self.j_threshold
        else:
            threshold = self.j_threshold

        # Check if overbought
        if current_j > threshold:
            # Check turndown if required
            if self.wait_for_turndown and len(hist) >= 2:
                prev_j = hist['J'].iloc[-2]
                if pd.isna(prev_j) or current_j >= prev_j:
                    return False, ""  # Not turning down yet

            current_close = current_data['close']
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"KDJ Overbought (J={current_j:.1f} > {threshold:.1f}) (P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def _compute_kdj(self, df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
        """Compute KDJ indicator (from Selector.py)."""
        if len(df) < n:
            return None

        close = df['close'].values
        low = df['low'].values
        high = df['high'].values

        rsv = np.zeros(len(df))
        k = np.zeros(len(df))
        d = np.zeros(len(df))
        j = np.zeros(len(df))

        k[0] = 50.0
        d[0] = 50.0

        for i in range(len(df)):
            if i < n - 1:
                rsv[i] = 50.0
            else:
                window_low = low[i - n + 1:i + 1]
                window_high = high[i - n + 1:i + 1]
                llv = np.min(window_low)
                hhv = np.max(window_high)

                if hhv == llv:
                    rsv[i] = 50.0
                else:
                    rsv[i] = 100 * (close[i] - llv) / (hhv - llv)

            if i > 0:
                k[i] = (m1 - 1) / m1 * k[i - 1] + rsv[i] / m1
                d[i] = (m2 - 1) / m2 * d[i - 1] + k[i] / m2
            else:
                k[i] = rsv[i]
                d[i] = k[i]

            j[i] = 3 * k[i] - 2 * d[i]

        return pd.DataFrame({'K': k, 'D': d, 'J': j}, index=df.index)

    def get_name(self) -> str:
        return f"KDJOverbought(J>{self.j_threshold})"


class BBIReversalExitStrategy(SellStrategy):
    """
    Exit on BBI reversal (downtrend).

    Triggers when BBI declines for N consecutive days,
    mirroring the buy condition (BBI uptrend).
    """

    def __init__(self, consecutive_declines: int = 3, **params):
        """
        Initialize strategy.

        Args:
            consecutive_declines: Number of consecutive BBI declines
            **params: Additional parameters
        """
        super().__init__(**params)
        self.consecutive_declines = consecutive_declines

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if BBI in downtrend."""
        # Calculate BBI
        bbi = self._compute_bbi(hist_data)

        if bbi is None or len(bbi) < self.consecutive_declines + 1:
            return False, ""

        # Check last N consecutive declines
        recent_bbi = bbi.tail(self.consecutive_declines + 1)

        is_declining = True
        for i in range(1, len(recent_bbi)):
            if recent_bbi.iloc[i] >= recent_bbi.iloc[i - 1]:
                is_declining = False
                break

        if is_declining:
            current_close = current_data['close']
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"BBI Reversal ({self.consecutive_declines} consecutive declines) (P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def _compute_bbi(self, df: pd.DataFrame) -> pd.Series:
        """Compute BBI indicator."""
        close = df['close']
        ma3 = close.rolling(window=3, min_periods=1).mean()
        ma6 = close.rolling(window=6, min_periods=1).mean()
        ma12 = close.rolling(window=12, min_periods=1).mean()
        ma24 = close.rolling(window=24, min_periods=1).mean()

        bbi = (ma3 + ma6 + ma12 + ma24) / 4.0
        return bbi

    def get_name(self) -> str:
        return f"BBIReversal({self.consecutive_declines}d)"


class ZXLinesCrossDownExitStrategy(SellStrategy):
    """
    Exit on ZX lines bearish cross.

    Triggers when ZXDQ (short-term) crosses below ZXDKX (long-term).

    This is opposite of buy requirement (ZXDQ > ZXDKX).
    """

    def __init__(self, **params):
        """Initialize strategy."""
        super().__init__(**params)

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if ZX lines cross down."""
        # Calculate ZX lines
        zxdq, zxdkx = self._compute_zx_lines(hist_data)

        if zxdq is None or zxdkx is None:
            return False, ""

        if len(zxdq) < 2 or len(zxdkx) < 2:
            return False, ""

        # Check for bearish cross
        current_zxdq = zxdq.iloc[-1]
        current_zxdkx = zxdkx.iloc[-1]
        prev_zxdq = zxdq.iloc[-2]
        prev_zxdkx = zxdkx.iloc[-2]

        if pd.isna(current_zxdq) or pd.isna(current_zxdkx):
            return False, ""
        if pd.isna(prev_zxdq) or pd.isna(prev_zxdkx):
            return False, ""

        # Cross down: was above, now below
        if prev_zxdq >= prev_zxdkx and current_zxdq < current_zxdkx:
            current_close = current_data['close']
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"ZX Lines Cross Down (ZXDQ < ZXDKX) (P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def _compute_zx_lines(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """Compute ZX lines (from Selector.py)."""
        close = df['close']

        # ZXDQ = EMA(EMA(C,10),10)
        ema10 = close.ewm(span=10, adjust=False).mean()
        zxdq = ema10.ewm(span=10, adjust=False).mean()

        # ZXDKX = (MA(14)+MA(28)+MA(57)+MA(114))/4
        ma14 = close.rolling(window=14, min_periods=1).mean()
        ma28 = close.rolling(window=28, min_periods=1).mean()
        ma57 = close.rolling(window=57, min_periods=1).mean()
        ma114 = close.rolling(window=114, min_periods=1).mean()
        zxdkx = (ma14 + ma28 + ma57 + ma114) / 4.0

        return zxdq, zxdkx

    def get_name(self) -> str:
        return "ZXLinesCrossDown"


class MADeathCrossExitStrategy(SellStrategy):
    """
    Exit on MA death cross.

    Triggers when fast MA crosses below slow MA.

    Default: MA5 crosses below MA20.
    """

    def __init__(self, fast_period: int = 5, slow_period: int = 20, **params):
        """
        Initialize strategy.

        Args:
            fast_period: Fast MA period
            slow_period: Slow MA period
            **params: Additional parameters
        """
        super().__init__(**params)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if MA death cross occurred."""
        if len(hist_data) < max(self.fast_period, self.slow_period) + 1:
            return False, ""

        close = hist_data['close']

        # Calculate MAs
        fast_ma = close.rolling(window=self.fast_period, min_periods=1).mean()
        slow_ma = close.rolling(window=self.slow_period, min_periods=1).mean()

        if len(fast_ma) < 2 or len(slow_ma) < 2:
            return False, ""

        current_fast = fast_ma.iloc[-1]
        current_slow = slow_ma.iloc[-1]
        prev_fast = fast_ma.iloc[-2]
        prev_slow = slow_ma.iloc[-2]

        if pd.isna(current_fast) or pd.isna(current_slow):
            return False, ""
        if pd.isna(prev_fast) or pd.isna(prev_slow):
            return False, ""

        # Death cross: was above, now below
        if prev_fast >= prev_slow and current_fast < current_slow:
            current_close = current_data['close']
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"MA Death Cross (MA{self.fast_period} < MA{self.slow_period}) (P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def get_name(self) -> str:
        return f"MADeathCross(MA{self.fast_period}<MA{self.slow_period})"
