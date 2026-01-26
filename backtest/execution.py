"""
Order execution module with Chinese A-share market rules.

Handles T+1 settlement, price limits, transaction costs, and stock suspensions.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict
import pandas as pd

from .data_structures import Order, OrderAction, OrderStatus


class ExecutionEngine:
    """
    Handles realistic order execution for Chinese A-share market.

    Key features:
    - T+1 settlement (signal on day T, execute on day T+1 open)
    - ±10% price limits (orders fail if gap exceeds limit)
    - Transaction costs (commission, stamp tax, slippage)
    - 100-share lot size requirement
    - Stock suspension detection
    """

    def __init__(
        self,
        commission_rate: float = 0.0003,  # 0.03%
        stamp_tax_rate: float = 0.001,    # 0.1% (sells only)
        slippage_rate: float = 0.001,     # 0.1%
        min_commission: float = 5.0       # Minimum commission (5 RMB)
    ):
        """
        Initialize execution engine.

        Args:
            commission_rate: Commission rate (both sides)
            stamp_tax_rate: Stamp tax rate (sells only)
            slippage_rate: Slippage rate (adverse price movement)
            min_commission: Minimum commission per trade
        """
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage_rate = slippage_rate
        self.min_commission = min_commission

    def can_execute_order(
        self,
        order: Order,
        current_data: pd.Series,
        prev_close: float
    ) -> tuple[bool, Optional[str]]:
        """
        Check if order can be executed.

        Args:
            order: The order to execute
            current_data: Market data for execution day (has 'open', 'volume', etc.)
            prev_close: Previous day's close price

        Returns:
            (can_execute, reason_if_failed)
        """
        # Check for stock suspension (volume = 0)
        if current_data.get('volume', 0) == 0:
            return False, "Stock suspended (volume = 0)"

        open_price = current_data['open']

        # Check ±10% price limit
        upper_limit = prev_close * 1.099  # Allow 9.9% to account for rounding
        lower_limit = prev_close * 0.901

        if order.action == OrderAction.BUY:
            # Cannot buy if price gapped up to upper limit
            if open_price >= upper_limit:
                return False, f"Price at upper limit (+10%): {open_price:.2f} >= {upper_limit:.2f}"
        else:  # SELL
            # Cannot sell if price gapped down to lower limit
            if open_price <= lower_limit:
                return False, f"Price at lower limit (-10%): {open_price:.2f} <= {lower_limit:.2f}"

        return True, None

    def execute_order(
        self,
        order: Order,
        execution_price: float
    ) -> bool:
        """
        Execute an order with realistic costs.

        Args:
            order: The order to execute
            execution_price: The execution price (open price on T+1)

        Returns:
            True if executed successfully
        """
        if order.action == OrderAction.BUY:
            # Adverse slippage for buys (pay more)
            actual_price = execution_price * (1 + self.slippage_rate)
            order.execution_price = actual_price
            order.slippage = order.shares * execution_price * self.slippage_rate

            # Commission
            commission = order.shares * actual_price * self.commission_rate
            commission = max(commission, self.min_commission)
            order.commission = commission

            # No stamp tax on buys
            order.stamp_tax = 0.0

            # Total cost
            order.total_cost = order.shares * actual_price + commission
            order.net_proceeds = None

        else:  # SELL
            # Adverse slippage for sells (receive less)
            actual_price = execution_price * (1 - self.slippage_rate)
            order.execution_price = actual_price
            order.slippage = order.shares * execution_price * self.slippage_rate

            # Commission
            commission = order.shares * actual_price * self.commission_rate
            commission = max(commission, self.min_commission)
            order.commission = commission

            # Stamp tax (sells only)
            order.stamp_tax = order.shares * actual_price * self.stamp_tax_rate

            # Net proceeds
            order.net_proceeds = order.shares * actual_price - commission - order.stamp_tax
            order.total_cost = None

        order.status = OrderStatus.EXECUTED
        return True

    def round_to_lot_size(self, shares: float, lot_size: int = 100) -> int:
        """
        Round shares to valid lot size (100 shares for A-shares).

        Args:
            shares: Number of shares (may be fractional)
            lot_size: Lot size (default 100)

        Returns:
            Rounded shares (multiple of lot_size)
        """
        return int(shares // lot_size) * lot_size

    def calculate_max_shares(
        self,
        available_cash: float,
        price: float,
        lot_size: int = 100
    ) -> int:
        """
        Calculate maximum shares that can be bought with available cash.

        Accounts for commission and slippage in the calculation.

        Args:
            available_cash: Available cash
            price: Stock price
            lot_size: Lot size (default 100)

        Returns:
            Maximum shares (multiple of lot_size)
        """
        # Effective price including slippage
        effective_price = price * (1 + self.slippage_rate)

        # Iterative calculation to account for commission
        # shares * effective_price + max(shares * effective_price * commission_rate, min_commission) <= cash

        # First approximation
        max_shares_approx = available_cash / (effective_price * (1 + self.commission_rate))
        max_shares = self.round_to_lot_size(max_shares_approx, lot_size)

        # Verify and adjust
        while max_shares > 0:
            cost = max_shares * effective_price
            commission = max(cost * self.commission_rate, self.min_commission)
            total_cost = cost + commission

            if total_cost <= available_cash:
                return max_shares

            # Reduce by one lot and try again
            max_shares -= lot_size

        return 0

    def validate_data(self, data: pd.Series) -> bool:
        """
        Validate market data quality.

        Args:
            data: Market data row

        Returns:
            True if data is valid
        """
        required_fields = ['open', 'high', 'low', 'close', 'volume']

        # Check required fields exist
        for field in required_fields:
            if field not in data or pd.isna(data[field]):
                return False

        # Check OHLC consistency
        if not (data['low'] <= data['open'] <= data['high']):
            return False
        if not (data['low'] <= data['close'] <= data['high']):
            return False

        # Check for negative values
        if any(data[field] < 0 for field in required_fields):
            return False

        return True


class T1SettlementTracker:
    """
    Tracks T+1 settlement for cash and positions.

    In Chinese A-share market:
    - Sell proceeds available on T+1
    - Bought shares available for sale on T+1
    """

    def __init__(self):
        """Initialize settlement tracker."""
        self.frozen_cash: Dict[datetime, float] = {}  # Date -> frozen amount
        self.pending_proceeds: Dict[datetime, float] = {}  # Date -> expected proceeds
        self.frozen_positions: Dict[str, datetime] = {}  # Code -> earliest sellable date

    def freeze_cash(self, amount: float, settlement_date: datetime):
        """
        Freeze cash until settlement date.

        Args:
            amount: Amount to freeze
            settlement_date: When cash becomes available
        """
        if settlement_date not in self.frozen_cash:
            self.frozen_cash[settlement_date] = 0.0
        self.frozen_cash[settlement_date] += amount

    def add_pending_proceeds(self, amount: float, settlement_date: datetime):
        """
        Add pending proceeds from sell order.

        Args:
            amount: Expected proceeds
            settlement_date: When proceeds become available
        """
        if settlement_date not in self.pending_proceeds:
            self.pending_proceeds[settlement_date] = 0.0
        self.pending_proceeds[settlement_date] += amount

    def freeze_position(self, code: str, settlement_date: datetime):
        """
        Freeze position until settlement date.

        Args:
            code: Stock code
            settlement_date: When position becomes sellable
        """
        self.frozen_positions[code] = settlement_date

    def can_sell_position(self, code: str, current_date: datetime) -> bool:
        """
        Check if position can be sold.

        Args:
            code: Stock code
            current_date: Current date

        Returns:
            True if position can be sold
        """
        if code not in self.frozen_positions:
            return True
        return current_date >= self.frozen_positions[code]

    def settle(self, current_date: datetime) -> tuple[float, float]:
        """
        Process settlement for current date.

        Args:
            current_date: Current date

        Returns:
            (released_cash, received_proceeds)
        """
        released_cash = self.frozen_cash.pop(current_date, 0.0)
        received_proceeds = self.pending_proceeds.pop(current_date, 0.0)

        # Clean up frozen positions
        self.frozen_positions = {
            code: date for code, date in self.frozen_positions.items()
            if date > current_date
        }

        return released_cash, received_proceeds

    def get_total_frozen_cash(self) -> float:
        """Get total frozen cash amount."""
        return sum(self.frozen_cash.values())

    def get_total_pending_proceeds(self) -> float:
        """Get total pending proceeds."""
        return sum(self.pending_proceeds.values())
