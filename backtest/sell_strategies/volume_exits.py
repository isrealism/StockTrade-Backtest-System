"""
Volume-based exit strategy.

Implements:
1. VolumeDryUpExitStrategy - Exit on volume dry-up (loss of momentum)
"""

from datetime import datetime
from typing import Tuple
import pandas as pd

from .base import SellStrategy
from ..data_structures import Position


class VolumeDryUpExitStrategy(SellStrategy):
    """
    Exit on volume dry-up.

    Triggers when volume < X% of N-day average for M consecutive days.

    Indicates loss of momentum and liquidity concerns.
    """

    def __init__(
        self,
        volume_threshold_pct: float = 0.5,
        lookback_period: int = 20,
        consecutive_days: int = 3,
        **params
    ):
        """
        Initialize strategy.

        Args:
            volume_threshold_pct: Volume threshold (e.g., 0.5 for 50% of avg)
            lookback_period: Period for average volume calculation
            consecutive_days: Number of consecutive low-volume days
            **params: Additional parameters
        """
        super().__init__(**params)
        self.volume_threshold_pct = volume_threshold_pct
        self.lookback_period = lookback_period
        self.consecutive_days = consecutive_days

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if volume dried up."""
        if len(hist_data) < self.lookback_period + self.consecutive_days:
            return False, ""

        # Calculate average volume
        avg_volume = hist_data['volume'].tail(self.lookback_period).mean()

        if avg_volume == 0:
            return False, ""

        # Check recent consecutive days
        recent_data = hist_data.tail(self.consecutive_days)

        # Check if all recent days have low volume
        low_volume_days = 0
        for _, row in recent_data.iterrows():
            if row['volume'] < avg_volume * self.volume_threshold_pct:
                low_volume_days += 1

        if low_volume_days >= self.consecutive_days:
            current_close = current_data['close']
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            current_volume = current_data['volume']
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

            return True, f"Volume Dry-Up ({low_volume_days}d < {self.volume_threshold_pct*100:.0f}% avg, ratio={volume_ratio:.2f}) (P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def get_name(self) -> str:
        return f"VolumeDryUp({self.consecutive_days}d<{self.volume_threshold_pct*100:.0f}%avg)"
