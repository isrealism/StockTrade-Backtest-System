"""
Profit target exit strategies.

Implements 2 profit target strategies:
1. FixedProfitTargetStrategy - Exit at predetermined profit level
2. MultipleRExitStrategy - Exit at N× initial risk (R-multiple)
"""

from datetime import datetime
from typing import Tuple
import pandas as pd
import numpy as np

from .base import SellStrategy
from ..data_structures import Position


class FixedProfitTargetStrategy(SellStrategy):
    """
    Fixed profit target exit.

    Exits when profit reaches target percentage (e.g., +15%, +20%).

    Optional: Can do partial exit (e.g., sell 50% at target, let rest run).
    """

    def __init__(
        self,
        target_pct: float = 0.15,
        partial_exit: bool = False,
        partial_exit_pct: float = 0.5,
        **params
    ):
        """
        Initialize strategy.

        Args:
            target_pct: Target profit percentage (e.g., 0.15 for 15%)
            partial_exit: If True, only exit partial_exit_pct of position
            partial_exit_pct: Percentage to exit if partial_exit=True
            **params: Additional parameters
        """
        super().__init__(**params)
        self.target_pct = target_pct
        self.partial_exit = partial_exit
        self.partial_exit_pct = partial_exit_pct

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if profit target reached."""
        current_close = current_data['close']
        current_profit_pct = position.unrealized_pnl_pct(current_close)

        if current_profit_pct >= self.target_pct:
            exit_type = "Partial" if self.partial_exit else "Full"
            return True, f"{exit_type} Profit Target ({self.target_pct*100:.1f}%) reached at {current_close:.2f} (P&L: {current_profit_pct*100:+.2f}%)"

        return False, ""

    def get_name(self) -> str:
        exit_type = "Partial" if self.partial_exit else "Full"
        return f"{exit_type}ProfitTarget({self.target_pct*100:.1f}%)"


class MultipleRExitStrategy(SellStrategy):
    """
    Risk-reward based exit (R-multiple).

    Exits when profit = N × initial risk.

    R = initial risk (e.g., entry ATR × stop_multiplier)
    Exit when profit >= N × R

    Example: If initial risk is 2%, exit at 3R = 6% profit.
    """

    def __init__(
        self,
        r_multiple: float = 3.0,
        atr_period: int = 14,
        stop_multiplier: float = 2.0,
        **params
    ):
        """
        Initialize strategy.

        Args:
            r_multiple: Target R-multiple (e.g., 3.0 for 3R)
            atr_period: Period for ATR calculation (to determine R)
            stop_multiplier: Multiplier for initial stop (e.g., 2.0 for 2 ATR)
            **params: Additional parameters
        """
        super().__init__(**params)
        self.r_multiple = r_multiple
        self.atr_period = atr_period
        self.stop_multiplier = stop_multiplier

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Check if R-multiple target reached."""
        # Calculate initial R (risk at entry)
        entry_idx = hist_data[hist_data['date'] == position.entry_date].index

        if len(entry_idx) == 0:
            return False, ""

        entry_idx = entry_idx[0]

        # Get data up to entry for ATR calculation
        data_up_to_entry = hist_data.loc[:entry_idx]

        if len(data_up_to_entry) < self.atr_period + 1:
            # Insufficient data for ATR, use simple percentage as fallback
            initial_risk_pct = 0.02 * self.stop_multiplier
        else:
            # Calculate ATR at entry
            atr_at_entry = self._calculate_atr(data_up_to_entry, self.atr_period)
            if atr_at_entry is None or atr_at_entry <= 0:
                initial_risk_pct = 0.02 * self.stop_multiplier
            else:
                # Risk = (ATR × stop_multiplier) / entry_price
                initial_risk_pct = (atr_at_entry * self.stop_multiplier) / position.entry_price

        # Target profit = R × r_multiple
        target_profit_pct = initial_risk_pct * self.r_multiple

        # Check if target reached
        current_close = current_data['close']
        current_profit_pct = position.unrealized_pnl_pct(current_close)

        if current_profit_pct >= target_profit_pct:
            return True, f"{self.r_multiple}R Target reached at {current_close:.2f} (R={initial_risk_pct*100:.2f}%, P&L: {current_profit_pct*100:+.2f}%)"

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
        return f"MultipleRTarget({self.r_multiple}R)"
