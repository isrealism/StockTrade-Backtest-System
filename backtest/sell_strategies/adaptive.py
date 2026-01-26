"""
Adaptive exit strategy based on market volatility.

Implements:
1. AdaptiveVolatilityExitStrategy - Adjusts stop based on volatility regime
"""

from datetime import datetime
from typing import Tuple
import pandas as pd
import numpy as np

from .base import SellStrategy
from ..data_structures import Position


class AdaptiveVolatilityExitStrategy(SellStrategy):
    """
    Adaptive exit based on volatility regime.

    - In high volatility: Widens stop to avoid whipsaw
    - In low volatility: Tightens stop to protect profits

    Uses historical volatility percentile to determine regime.
    """

    def __init__(
        self,
        volatility_period: int = 20,
        lookback_period: int = 120,
        low_vol_percentile: float = 30,
        high_vol_percentile: float = 70,
        low_vol_stop_pct: float = 0.05,
        normal_vol_stop_pct: float = 0.08,
        high_vol_stop_pct: float = 0.12,
        **params
    ):
        """
        Initialize strategy.

        Args:
            volatility_period: Period for volatility calculation
            lookback_period: Lookback for volatility percentile
            low_vol_percentile: Percentile for low volatility (e.g., 30)
            high_vol_percentile: Percentile for high volatility (e.g., 70)
            low_vol_stop_pct: Stop percentage in low volatility
            normal_vol_stop_pct: Stop percentage in normal volatility
            high_vol_stop_pct: Stop percentage in high volatility
            **params: Additional parameters
        """
        super().__init__(**params)
        self.volatility_period = volatility_period
        self.lookback_period = lookback_period
        self.low_vol_percentile = low_vol_percentile
        self.high_vol_percentile = high_vol_percentile
        self.low_vol_stop_pct = low_vol_stop_pct
        self.normal_vol_stop_pct = normal_vol_stop_pct
        self.high_vol_stop_pct = high_vol_stop_pct

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if adaptive stop hit."""
        # Calculate current volatility
        current_vol = self._calculate_volatility(hist_data, self.volatility_period)

        if current_vol is None:
            return False, ""

        # Calculate volatility percentile
        vol_percentile = self._calculate_volatility_percentile(
            hist_data,
            current_vol,
            self.volatility_period,
            self.lookback_period
        )

        if vol_percentile is None:
            return False, ""

        # Determine stop percentage based on volatility regime
        if vol_percentile < self.low_vol_percentile:
            # Low volatility: tight stop
            stop_pct = self.low_vol_stop_pct
            regime = "Low Vol"
        elif vol_percentile > self.high_vol_percentile:
            # High volatility: wide stop
            stop_pct = self.high_vol_stop_pct
            regime = "High Vol"
        else:
            # Normal volatility
            stop_pct = self.normal_vol_stop_pct
            regime = "Normal Vol"

        # Calculate stop level
        stop_level = position.highest_price_since_entry * (1 - stop_pct)

        # Check if stop hit
        current_close = current_data['close']

        if current_close <= stop_level:
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"Adaptive Stop ({regime}, {stop_pct*100:.1f}%, vol_pct={vol_percentile:.0f}) hit at {current_close:.2f} (stop: {stop_level:.2f}, P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def _calculate_volatility(self, df: pd.DataFrame, period: int) -> float:
        """
        Calculate historical volatility.

        Uses standard deviation of log returns.
        """
        if len(df) < period + 1:
            return None

        close = df['close'].tail(period + 1)

        if len(close) < 2:
            return None

        # Log returns
        log_returns = np.log(close / close.shift(1))

        # Volatility = std(log_returns)
        vol = log_returns.std()

        return float(vol) if not pd.isna(vol) else None

    def _calculate_volatility_percentile(
        self,
        df: pd.DataFrame,
        current_vol: float,
        vol_period: int,
        lookback_period: int
    ) -> float:
        """
        Calculate percentile rank of current volatility.

        Args:
            df: Historical data
            current_vol: Current volatility
            vol_period: Period for volatility calculation
            lookback_period: Lookback for percentile

        Returns:
            Percentile (0-100)
        """
        if len(df) < lookback_period + vol_period:
            return None

        # Calculate rolling volatility over lookback period
        vols = []

        for i in range(len(df) - lookback_period, len(df)):
            if i < vol_period:
                continue

            window = df.iloc[i - vol_period:i + 1]
            vol = self._calculate_volatility(window, vol_period)

            if vol is not None:
                vols.append(vol)

        if len(vols) == 0:
            return None

        # Calculate percentile
        vols = np.array(vols)
        percentile = (vols < current_vol).sum() / len(vols) * 100

        return float(percentile)

    def get_name(self) -> str:
        return f"AdaptiveVolatilityExit({self.low_vol_stop_pct*100:.0f}%-{self.high_vol_stop_pct*100:.0f}%)"
