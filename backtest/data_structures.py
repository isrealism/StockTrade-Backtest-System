"""
Core data structures for backtesting system.

Defines Position, Order, Trade, and BuySignal classes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


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

    Generated by existing 6 buy strategies from Selector.py.
    """
    code: str
    date: datetime
    strategy_name: str  # e.g., "BBIKDJSelector"
    strategy_alias: str  # e.g., "少妇战法"

    # Score for ranking signals (higher = better)
    score: float = 0.0

    # Optional: Store indicator values at signal time for analysis
    signal_data: Optional[Dict[str, Any]] = None


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
