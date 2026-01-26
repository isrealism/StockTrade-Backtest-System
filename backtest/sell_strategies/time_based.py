"""
Time-based exit strategy.

Implements:
1. TimedExitStrategy - Maximum holding period
"""

from datetime import datetime
from typing import Tuple
import pandas as pd

from .base import SellStrategy
from ..data_structures import Position


class TimedExitStrategy(SellStrategy):
    """
    Maximum holding period exit.

    Forces exit after N days to prevent dead capital.
    """

    def __init__(self, max_holding_days: int = 60, **params):
        """
        Initialize strategy.

        Args:
            max_holding_days: Maximum holding period in days
            **params: Additional parameters
        """
        super().__init__(**params)
        self.max_holding_days = max_holding_days

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if maximum holding period reached."""
        if position.days_held >= self.max_holding_days:
            current_close = current_data['close']
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return True, f"Max Holding Period ({self.max_holding_days} days) reached (P&L: {pnl_pct:+.2f}%)"

        return False, ""

    def get_name(self) -> str:
        return f"TimedExit({self.max_holding_days}d)"
