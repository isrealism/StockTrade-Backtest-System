"""
Core data structures for backtesting system.

Defines Position, Order, Trade, and BuySignal classes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import numpy as np


class OrderAction(Enum):
    """Order action type."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order execution status."""
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class Position:
    """
    Represents a stock position.

    Tracks entry details, current holdings, and metrics needed
    for sell strategy decisions.
    """
    code: str
    entry_date: datetime
    entry_price: float
    shares: int
    cost_basis: float  # Total cost including commission

    # Tracking metrics for sell strategies
    highest_price_since_entry: float = field(init=False)
    highest_close_since_entry: float = field(init=False)
    highest_close_date: Optional[datetime] = field(init=False)
    lowest_close_since_entry: float = field(init=False)
    lowest_close_date: Optional[datetime] = field(init=False)
    highest_high_since_entry: float = field(init=False)
    highest_high_date: Optional[datetime] = field(init=False)
    lowest_low_since_entry: float = field(init=False)
    lowest_low_date: Optional[datetime] = field(init=False)
    days_held: int = 0

    # Optional metadata
    buy_strategy: Optional[str] = None
    buy_signal_data: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize tracking metrics."""
        self.highest_price_since_entry = self.entry_price
        self.highest_close_since_entry = self.entry_price
        self.highest_close_date = self.entry_date
        self.lowest_close_since_entry = self.entry_price
        self.lowest_close_date = self.entry_date
        self.highest_high_since_entry = self.entry_price
        self.highest_high_date = self.entry_date
        self.lowest_low_since_entry = self.entry_price
        self.lowest_low_date = self.entry_date

    def update_price_stats(self, date: datetime, close: float, high: float, low: float):
        """Update highest/lowest price trackers and timestamps."""
        if close > self.highest_price_since_entry:
            self.highest_price_since_entry = close
        if close > self.highest_close_since_entry:
            self.highest_close_since_entry = close
            self.highest_close_date = date
        if close < self.lowest_close_since_entry:
            self.lowest_close_since_entry = close
            self.lowest_close_date = date
        if high > self.highest_high_since_entry:
            self.highest_high_since_entry = high
            self.highest_high_date = date
        if low < self.lowest_low_since_entry:
            self.lowest_low_since_entry = low
            self.lowest_low_date = date

    def increment_days_held(self):
        """Increment holding period counter."""
        self.days_held += 1

    @property
    def initial_value(self) -> float:
        """Initial position value (Principal) at entry price."""
        return self.shares * self.entry_price

    def market_value(self, current_price: float) -> float:
        """Calculate current market value based on provided price."""
        return self.shares * current_price

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L."""
        return self.shares * current_price - self.cost_basis

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """Calculate unrealized P&L percentage."""
        return (self.shares * current_price - self.cost_basis) / self.cost_basis


@dataclass
class Order:
    """
    Represents a pending order for T+1 execution.

    Orders are generated on day T and executed on day T+1 open.
    """
    code: str
    action: OrderAction
    shares: int
    signal_date: datetime  # Day T (signal generation)
    execution_date: datetime  # Day T+1 (execution)

    # Execution details (filled after execution)
    status: OrderStatus = OrderStatus.PENDING
    execution_price: Optional[float] = None
    commission: Optional[float] = None
    stamp_tax: Optional[float] = None
    slippage: Optional[float] = None
    total_cost: Optional[float] = None  # For buys: price + commission
    net_proceeds: Optional[float] = None  # For sells: price - commission - tax

    # Context
    reason: Optional[str] = None  # For sells: exit reason
    buy_strategy: Optional[str] = None  # For buys: which selector triggered

    def execute(
        self,
        price: float,
        commission_rate: float,
        stamp_tax_rate: float,
        slippage_rate: float
    ):
        """
        Execute the order with realistic costs.

        Args:
            price: Execution price (open price on T+1)
            commission_rate: Commission rate (e.g., 0.0003 for 0.03%)
            stamp_tax_rate: Stamp tax rate (e.g., 0.001 for 0.1%, sells only)
            slippage_rate: Slippage rate (e.g., 0.001 for 0.1%)
        """
        if self.action == OrderAction.BUY:
            # Adverse slippage for buys (pay more)
            self.execution_price = price * (1 + slippage_rate)
            self.slippage = self.shares * price * slippage_rate
            self.commission = self.shares * self.execution_price * commission_rate
            self.stamp_tax = 0.0
            self.total_cost = self.shares * self.execution_price + self.commission
            self.net_proceeds = None
        else:  # SELL
            # Adverse slippage for sells (receive less)
            self.execution_price = price * (1 - slippage_rate)
            self.slippage = self.shares * price * slippage_rate
            self.commission = self.shares * self.execution_price * commission_rate
            self.stamp_tax = self.shares * self.execution_price * stamp_tax_rate
            self.net_proceeds = self.shares * self.execution_price - self.commission - self.stamp_tax
            self.total_cost = None

        self.status = OrderStatus.EXECUTED

    def fail(self):
        """Mark order as failed (e.g., due to price limit)."""
        self.status = OrderStatus.FAILED

    def cancel(self):
        """Cancel the order."""
        self.status = OrderStatus.CANCELLED


@dataclass
class BuySignal:
    """
    Represents a buy signal from a selector.

    Score is automatically computed from the four raw indicator inputs
    in __post_init__; it is NOT passed as a constructor argument.

    Score formula (0–100):
        score = KDJ×40% + Volume×30% + Momentum×20% + BBI×10%

    Indicator inputs
    ----------------
    kdj_j        : KDJ J值。J越低分越高（J=0→100分，J=100→0分）
    volume_ratio : 当日成交量 / 20日均量。量比1→0分，量比3→100分，线性插值
    daily_return : 单日涨幅（小数）。最优区间+1%~+3%；+2%→100分，+5%→50分（避免追高）
    bbi_slope    : BBI 5日斜率（归一化，小数/天）。斜率0.5%/天→100分，线性缩放
    """

    # ── 必填字段 ────────────────────────────────────────────────
    code: str
    date: datetime
    strategy_name: str   # e.g., "BBIKDJSelector"
    strategy_alias: str  # e.g., "少妇战法"

    # ── 评分原始指标（均有默认值，缺失时对应子分为 0） ─────────────
    kdj_j: float = float('nan')  # J 值；nan 时 kdj_score = 0
    volume_ratio: float = 0.0    # 量比
    daily_return: float = 0.0    # 单日涨幅（小数）
    bbi_slope: float = 0.0       # BBI 斜率（小数/天）

    # ── 可选元数据 ──────────────────────────────────────────────
    signal_data: Optional[Dict[str, Any]] = None

    # ── 自动计算字段（不参与构造，由 __post_init__ 填充） ──────────
    score: float = field(init=False)
    kdj_score: float = field(init=False)
    volume_score: float = field(init=False)
    momentum_score: float = field(init=False)
    bbi_score: float = field(init=False)

    def __post_init__(self) -> None:
        """根据四个原始指标计算综合分及各子分。"""
        # KDJ 分：J 值越低分越高，区间 [0, 100] 反转
        if np.isnan(self.kdj_j):
            self.kdj_score = 0.0
        else:
            self.kdj_score = max(0.0, min(100.0, 100.0 - self.kdj_j))

        # 量能分：量比 1→0 分，量比 3→100 分，线性插值
        self.volume_score = max(0.0, min(100.0, (self.volume_ratio - 1.0) / 2.0 * 100.0))

        # 动量分：分段线性，避免追高
        r = self.daily_return
        if r <= 0.0:
            self.momentum_score = 0.0
        elif r <= 0.02:
            self.momentum_score = (r / 0.02) * 100.0
        elif r <= 0.05:
            self.momentum_score = 100.0 - ((r - 0.02) / 0.03) * 50.0
        else:
            self.momentum_score = 50.0
        self.momentum_score = max(0.0, min(100.0, self.momentum_score))

        # BBI 分：斜率 0.5%/天 → 100 分
        self.bbi_score = (
            max(0.0, min(100.0, (self.bbi_slope / 0.005) * 100.0))
            if self.bbi_slope > 0.0 else 0.0
        )

        # 综合分
        self.score = (
            0.4 * self.kdj_score
            + 0.3 * self.volume_score
            + 0.2 * self.momentum_score
            + 0.1 * self.bbi_score
        )


@dataclass
class Trade:
    """
    Represents a completed trade (buy + sell).

    Generated after a position is closed.
    """
    code: str

    # Entry
    entry_date: datetime
    entry_price: float
    shares: int
    entry_cost: float  # Total cost with commission

    # Exit
    exit_date: datetime
    exit_price: float
    exit_proceeds: float  # Net proceeds after commission and tax

    # Optional fields (with defaults)
    buy_strategy: Optional[str] = None
    exit_reason: str = ""

    # P&L (calculated in __post_init__)
    gross_pnl: float = field(init=False)
    gross_pnl_pct: float = field(init=False)
    net_pnl: float = field(init=False)
    net_pnl_pct: float = field(init=False)

    # Metrics
    holding_days: int = 0
    max_unrealized_pnl_pct: float = 0.0  # Peak profit during holding

    def __post_init__(self):
        """Calculate P&L metrics."""
        self.gross_pnl = self.shares * (self.exit_price - self.entry_price)
        self.gross_pnl_pct = (self.exit_price - self.entry_price) / self.entry_price
        self.net_pnl = self.exit_proceeds - self.entry_cost
        self.net_pnl_pct = self.net_pnl / self.entry_cost

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            'code': self.code,
            'entry_date': self.entry_date.strftime('%Y-%m-%d'),
            'entry_price': round(self.entry_price, 2),
            'exit_date': self.exit_date.strftime('%Y-%m-%d'),
            'exit_price': round(self.exit_price, 2),
            'shares': self.shares,
            'holding_days': self.holding_days,
            'gross_pnl': round(self.gross_pnl, 2),
            'gross_pnl_pct': round(self.gross_pnl_pct * 100, 2),
            'net_pnl': round(self.net_pnl, 2),
            'net_pnl_pct': round(self.net_pnl_pct * 100, 2),
            'max_unrealized_pnl_pct': round(self.max_unrealized_pnl_pct * 100, 2),
            'exit_reason': self.exit_reason,
            'buy_strategy': self.buy_strategy or 'Unknown'
        }