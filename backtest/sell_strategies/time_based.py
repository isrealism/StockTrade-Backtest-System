"""
Time-based exit strategies.

Implements:
1. TimedExitStrategy    - Maximum holding period
2. EarlyExitStrategy    - Sideways/consolidation detection:
                          if daily returns stay within a narrow band for
                          N consecutive days → no momentum → exit
"""

from datetime import datetime
from typing import Tuple
import pandas as pd
import numpy as np

from .base import SellStrategy
from ..data_structures import Position


class TimedExitStrategy(SellStrategy):
    """
    Maximum holding period exit.

    Forces exit after N days to prevent dead capital.
    """

    def __init__(self, max_holding_days: int = 60, **params):
        """
        Args:
            max_holding_days: Maximum holding period in days
        """
        super().__init__(**params)
        self.max_holding_days = max_holding_days

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame,
        **kwargs,
    ) -> Tuple[bool, str]:
        """Check if maximum holding period reached."""
        if position.days_held >= self.max_holding_days:
            current_close = current_data["close"]
            pnl_pct = position.unrealized_pnl_pct(current_close) * 100
            return (
                True,
                f"Max Holding Period ({self.max_holding_days} days) reached "
                f"(P&L: {pnl_pct:+.2f}%)",
            )
        return False, ""

    def get_name(self) -> str:
        return f"TimedExit({self.max_holding_days}d)"


class EarlyExitStrategy(SellStrategy):
    """
    横盘无动能出局策略（连续 N 天涨幅在区间内 → 卖出）

    逻辑
    ----
    买入后若连续 ``consecutive_days`` 个交易日，每日涨幅（当日收盘 vs 前日收盘）
    均低于 daily_upper 区间，认为股票处于横盘状态、缺乏启动动能，
    直接平仓释放资金。

    "强势股"买入后应在 1~2 天内出现明显方向性突破（日涨幅超出区间上界）；
    连续磨蹭说明信号质量不佳或时机不对。

    参数选择建议（A 股）
    --------------------
    - consecutive_days = 3   : 3 天没方向就放弃，资金利用率优先
    - daily_upper     = +0.03: 每天涨幅不超 3%（超过 3% 说明有动能，应继续持有）

    注意事项
    --------
    - 只看每日日内收益，不看从入场到当天的累计盈亏
    - 需要 hist_data 中包含入场日期之后的所有日期（含当日）
    - 不满足"已持仓 consecutive_days 天"时本策略不触发，避免误杀第一天
    """

    def __init__(
        self,
        consecutive_days: int = 3,
        daily_upper: float = 0.03,    # 每日涨幅上界（含），+3%
        **params,
    ):
        """
        Args:
            consecutive_days: 连续横盘天数阈值（默认 3）
            daily_upper:      每日涨幅区间上界，小数（默认 +0.03 即 +3%）
        """
        super().__init__(**params)
        self.consecutive_days = consecutive_days
        self.daily_upper = daily_upper

        if self.consecutive_days < 1:
            raise ValueError("consecutive_days 必须 >= 1")

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame,
        **kwargs,
    ) -> Tuple[bool, str]:
        """
        检查最近 consecutive_days 天的每日涨幅是否全部处于横盘区间。

        触发条件（同时满足）：
          1. 已持仓天数 >= consecutive_days（确保有足够的观察窗口）
          2. 最近 consecutive_days 天的每日涨幅均在 [daily_lower, daily_upper] 内
        """
        # ── 条件 1：持仓时间不足，不触发 ──────────────────────────────
        if position.days_held < self.consecutive_days:
            return False, ""

        # ── 截取入场日以来的数据 ───────────────────────────────────────
        entry_date = position.entry_date
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()

        # hist_data 中找到入场日或其后最近一行
        if "date" in hist_data.columns:
            date_col = pd.to_datetime(hist_data["date"])
        else:
            date_col = pd.to_datetime(hist_data.index)

        entry_ts = pd.Timestamp(entry_date)
        since_entry = hist_data[date_col >= entry_ts].copy()

        # 需要 consecutive_days + 1 行才能算出 consecutive_days 个日涨幅
        # （第一行作为前一日基准，后续 consecutive_days 行各算一次）
        required_rows = self.consecutive_days + 1
        if len(since_entry) < required_rows:
            return False, ""

        # ── 取最近 (consecutive_days + 1) 行，计算每日涨幅 ───────────
        window = since_entry.tail(required_rows)
        closes = window["close"].values.astype(float)

        # daily_returns[i] = (closes[i+1] - closes[i]) / closes[i]
        prev_closes = closes[:-1]
        curr_closes = closes[1:]

        with np.errstate(divide="ignore", invalid="ignore"):
            daily_returns = np.where(
                prev_closes > 0,
                (curr_closes - prev_closes) / prev_closes,
                np.nan,
            )

        # 有 NaN 说明数据有问题，跳过
        if np.any(np.isnan(daily_returns)):
            return False, ""

        # ── 判断：全部日涨幅都在横盘区间内 ──────────────────────────
        all_sideways = bool(
            np.all(daily_returns <= self.daily_upper)
        )

        if all_sideways:
            current_close = float(current_data["close"])
            cumulative_pnl = position.unrealized_pnl_pct(current_close) * 100

            # 格式化每日涨幅，方便 debug
            returns_str = ", ".join(f"{r*100:+.2f}%" for r in daily_returns)

            return True, (
                f"EarlyExit: 连续 {self.consecutive_days} 天横盘 "
                f"[{returns_str}] "
                f" 涨幅均在 {self.daily_upper*100:.1f}%] 内 "
                f"(累计 P&L: {cumulative_pnl:+.2f}%)"
            )

        return False, ""

    def get_name(self) -> str:
        return (
            f"EarlyExit({self.consecutive_days}d×"
            f"[{self.daily_upper*100:.1f}%])"
        )