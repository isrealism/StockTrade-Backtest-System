"""
Trailing stop strategies for risk management.

Implements 3 trailing stop strategies:
1. ATRTrailingStopStrategy - Adaptive stop using Average True Range
2. ChandelierStopStrategy - Conservative variant using highest high
3. PercentageTrailingStopStrategy - Simple percentage stop
"""

from datetime import datetime
from typing import Tuple
import pandas as pd
import numpy as np

from .base import SellStrategy
from ..data_structures import Position


class ATRTrailingStopStrategy(SellStrategy):
    """
    ATR-based trailing stop.

    Stop level = highest_close - (ATR × multiplier)

    Adapts to market volatility automatically - wider stops in volatile markets,
    tighter stops in calm markets.
    """

    def __init__(self, atr_period: int = 14, atr_multiplier: float = 2.0, **params):
        """
        Initialize strategy.

        Args:
            atr_period: Period for ATR calculation
            atr_multiplier: Multiplier for ATR (e.g., 2.0 for 2 ATR stop)
            **params: Additional parameters
        """
        super().__init__(**params)
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if current price hit ATR trailing stop."""
        # Calculate ATR
        atr = self._calculate_atr(hist_data, self.atr_period)

        if atr is None or atr <= 0:
            return False, ""

        # Stop level = highest close since entry - (ATR × multiplier)
        stop_level = position.highest_price_since_entry - (atr * self.atr_multiplier)

        # Check if current close below stop
        current_close = current_data['close']

        if current_close <= stop_level:
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"ATR Trailing Stop ({self.atr_multiplier}x) hit at {current_close:.2f} (stop: {stop_level:.2f}, P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def _calculate_atr(self, df: pd.DataFrame, period: int) -> float:
        """
        Calculate Average True Range.

        Args:
            df: Historical OHLC data
            period: ATR period

        Returns:
            ATR value or None if insufficient data
        """
        if len(df) < period + 1:
            return None

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        tr = np.maximum(
            high - low,
            np.maximum(
                np.abs(high - np.roll(close, 1)),
                np.abs(low - np.roll(close, 1))
            )
        )

        # First TR is just high - low
        tr[0] = high[0] - low[0]

        # ATR = average of last N true ranges
        atr = np.mean(tr[-period:])

        return float(atr)

    def get_name(self) -> str:
        return f"ATRTrailingStop({self.atr_multiplier}x)"


class ChandelierStopStrategy(SellStrategy):
    """
    Chandelier stop - conservative variant of ATR stop.

    Stop level = highest_high(N) - (ATR × multiplier)

    Uses highest high instead of highest close, which provides
    less whipsaw than ATR stop.
    """

    def __init__(
        self,
        lookback_period: int = 22,
        atr_period: int = 14,
        atr_multiplier: float = 3.0,
        **params
    ):
        """
        Initialize strategy.

        Args:
            lookback_period: Period for highest high calculation
            atr_period: Period for ATR calculation
            atr_multiplier: Multiplier for ATR
            **params: Additional parameters
        """
        super().__init__(**params)
        self.lookback_period = lookback_period
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if current price hit Chandelier stop."""
        # Calculate ATR
        atr = self._calculate_atr(hist_data, self.atr_period)

        if atr is None or atr <= 0:
            return False, ""

        # Highest high in lookback period (since entry)
        entry_idx = hist_data[hist_data['date'] == position.entry_date].index
        if len(entry_idx) == 0:
            return False, ""

        entry_idx = entry_idx[0]
        data_since_entry = hist_data.loc[entry_idx:]

        if len(data_since_entry) == 0:
            return False, ""

        # Use min(lookback_period, days since entry)
        lookback = min(self.lookback_period, len(data_since_entry))
        highest_high = data_since_entry['high'].tail(lookback).max()

        # Stop level = highest high - (ATR × multiplier)
        stop_level = highest_high - (atr * self.atr_multiplier)

        # Check if current close below stop
        current_close = current_data['close']

        if current_close <= stop_level:
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"Chandelier Stop ({self.atr_multiplier}x) hit at {current_close:.2f} (stop: {stop_level:.2f}, P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def _calculate_atr(self, df: pd.DataFrame, period: int) -> float:
        """Calculate ATR."""
        if len(df) < period + 1:
            return None

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
        tr[0] = high[0] - low[0]

        atr = np.mean(tr[-period:])
        return float(atr)

    def get_name(self) -> str:
        return f"ChandelierStop({self.atr_multiplier}x)"


class PercentageTrailingStopStrategy(SellStrategy):
    """
    Simple percentage-based trailing stop.

    Stop level = highest_close × (1 - trailing_pct)

    Optional: Can activate only after profit threshold reached.
    """

    def __init__(
        self,
        trailing_pct: float = 0.08,
        activate_after_profit_pct: float = 0.0,
        **params
    ):
        """
        Initialize strategy.

        Args:
            trailing_pct: Trailing stop percentage (e.g., 0.08 for 8%)
            activate_after_profit_pct: Only activate after this profit level
                                      (e.g., 0.05 means activate after +5%)
            **params: Additional parameters
        """
        super().__init__(**params)
        self.trailing_pct = trailing_pct
        self.activate_after_profit_pct = activate_after_profit_pct

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if current price hit percentage trailing stop."""
        current_close = current_data['close']

        # Check if activation threshold met
        if self.activate_after_profit_pct > 0:
            current_profit_pct = position.unrealized_pnl_pct(current_close)
            max_profit_pct = (position.highest_price_since_entry - position.entry_price) / position.entry_price

            # Only activate if we've reached profit threshold
            if max_profit_pct < self.activate_after_profit_pct:
                return False, ""

        # Stop level = highest close × (1 - trailing_pct)
        stop_level = position.highest_price_since_entry * (1 - self.trailing_pct)

        if current_close <= stop_level:
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"Percentage Trailing Stop ({self.trailing_pct*100:.1f}%) hit at {current_close:.2f} (stop: {stop_level:.2f}, P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def get_name(self) -> str:
        if self.activate_after_profit_pct > 0:
            return f"PercentageTrailingStop({self.trailing_pct*100:.1f}%, activate>{self.activate_after_profit_pct*100:.1f}%)"
        return f"PercentageTrailingStop({self.trailing_pct*100:.1f}%)"
