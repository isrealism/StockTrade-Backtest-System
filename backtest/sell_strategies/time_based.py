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


class EarlyExitStrategy(SellStrategy):
    """
    早期震荡出局策略。

    买入后 N 天内（默认3天），若累计涨跌幅处于 [lower_bound, upper_bound] 区间，
    视为"无效启动"，直接卖出，释放资金等待更好信号。

    典型配置：3天内涨跌在 -2%～+3% 之间 → 卖出
    逻辑：真正强势股买入后应迅速突破上界；在区间内磨蹭说明动能不足。
    """

    def __init__(
        self,
        window_days: int = 3,
        lower_bound: float = -0.02,   # -2%
        upper_bound: float = 0.03,    # +3%
        **params
    ):
        """
        Args:
            window_days  : 观察窗口（交易日），默认3天
            lower_bound  : 区间下界（小数，负数为亏损），默认 -0.02
            upper_bound  : 区间上界（小数），默认 0.03
        """
        super().__init__(**params)
        self.window_days = window_days
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """
        仅在持仓 window_days 天内判断；超过窗口期后本策略不再触发。
        """
        if position.days_held > self.window_days:
            return False, ""

        current_close = float(current_data['close'])
        pnl_pct = position.unrealized_pnl_pct(current_close)   # 小数形式

        if self.lower_bound <= pnl_pct <= self.upper_bound:
            return True, (
                f"EarlyExit: {position.days_held}d内涨幅 {pnl_pct*100:+.2f}% "
                f"处于震荡区间 [{self.lower_bound*100:.1f}%, {self.upper_bound*100:.1f}%]"
            )

        return False, ""

    def get_name(self) -> str:
        return (
            f"EarlyExit({self.window_days}d, "
            f"{self.lower_bound*100:.1f}%~{self.upper_bound*100:.1f}%)"
        )