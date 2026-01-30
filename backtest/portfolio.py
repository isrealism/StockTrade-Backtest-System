"""
Portfolio management module.

Handles positions, cash, order generation, and position sizing.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .data_structures import Position, Order, Trade, OrderAction, OrderStatus
from .execution import ExecutionEngine, T1SettlementTracker


class PortfolioManager:
    """
    Manages portfolio positions and cash.

    Responsibilities:
    - Track positions and cash
    - Generate buy/sell orders
    - Execute orders with T+1 settlement
    - Position sizing
    - Trade history
    """

    def __init__(
        self,
        initial_capital: float,
        max_positions: int = 10,
        position_sizing: str = "equal_weight",
        execution_engine: Optional[ExecutionEngine] = None
    ):
        """
        Initialize portfolio manager.

        Args:
            initial_capital: Starting capital
            max_positions: Maximum number of positions
            position_sizing: Position sizing method ("equal_weight", "risk_based")
            execution_engine: Execution engine (creates default if None)
        """
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.position_sizing = position_sizing

        # Cash tracking
        self.cash = initial_capital
        self.total_value = initial_capital

        # Positions
        self.positions: Dict[str, Position] = {}

        # Orders
        self.pending_orders: List[Order] = []

        # Trade history
        self.trades: List[Trade] = []

        # Execution
        self.execution_engine = execution_engine or ExecutionEngine()
        self.settlement_tracker = T1SettlementTracker()

        # Equity curve tracking
        self.equity_curve: List[Dict] = []

    def update_equity_curve(self, date: datetime, market_data: Dict[str, pd.Series]):
        """
        Update equity curve for current date.

        Args:
            date: Current date
            market_data: Market data for all stocks {code: data_series}
        """
        # Calculate position values
        position_value = 0.0
        for code, position in self.positions.items():
            if code in market_data:
                current_price = market_data[code]['close']
                position_value += position.shares * current_price

        # Total value
        self.total_value = self.cash + position_value

        # Record
        self.equity_curve.append({
            'date': date,
            'cash': self.cash,
            'position_value': position_value,
            'total_value': self.total_value,
            'num_positions': len(self.positions),
            'frozen_cash': self.settlement_tracker.get_total_frozen_cash(),
            'pending_proceeds': self.settlement_tracker.get_total_pending_proceeds()
        })

    def update_positions(self, date: datetime, market_data: Dict[str, pd.Series]):
        """
        Update position metrics (highest price, days held).

        Args:
            date: Current date
            market_data: Market data for all stocks
        """
        for code, position in self.positions.items():
            if code in market_data:
                data = market_data[code]
                position.update_highest_price(data['close'], data['high'])
                position.increment_days_held()

    def can_open_new_position(self) -> bool:
        """
        Check if can open new position.

        Checks both position limit and available cash.

        Returns:
            True if can open new position
        """
        # Check position limit
        total_positions = len(self.positions) + self._count_pending_buy_orders()
        if total_positions >= self.max_positions:
            return False

        # Check if we have any available cash
        available_cash = self.get_available_cash()

        # Need at least some cash to open position (min ~10k for 100 shares @ 10 RMB)
        min_required_cash = 10000

        return available_cash >= min_required_cash

    def _count_pending_buy_orders(self) -> int:
        """Count number of pending buy orders."""
        count = 0
        for order in self.pending_orders:
            if order.action == OrderAction.BUY and order.status == OrderStatus.PENDING:
                count += 1
        return count

    def calculate_position_size(
        self,
        code: str,
        price: float,
        market_data: Optional[pd.DataFrame] = None
    ) -> int:
        """
        Calculate position size based on sizing method.

        Args:
            code: Stock code
            price: Current price
            market_data: Historical data (needed for risk-based sizing)

        Returns:
            Number of shares to buy
        """
        if self.position_sizing == "equal_weight":
            # Equal weight allocation based on AVAILABLE cash
            # Account for existing positions and pending orders
            total_positions = len(self.positions) + self._count_pending_buy_orders()
            available_cash = self.get_available_cash()

            # Calculate allocation: distribute available cash among remaining slots
            remaining_slots = max(1, self.max_positions - total_positions + 1)
            target_per_position = available_cash / remaining_slots

            if target_per_position <= 0:
                return 0

            shares = self.execution_engine.calculate_max_shares(
                target_per_position,
                price
            )
            return shares

        elif self.position_sizing == "risk_based":
            # Risk-based using ATR (if we have data)
            if market_data is None or len(market_data) < 14:
                # Fallback to equal weight
                return self.calculate_position_size(code, price, None)

            # Calculate ATR
            atr = self._calculate_atr(market_data, period=14)
            if atr is None or atr <= 0:
                return self.calculate_position_size(code, price, None)

            # Risk 1% of capital per position
            risk_per_position = self.initial_capital * 0.01
            stop_distance = atr * 2  # 2 ATR stop
            shares_for_risk = risk_per_position / stop_distance

            # Calculate max shares within cash limit
            max_shares = self.execution_engine.calculate_max_shares(self.cash, price)

            # Take minimum
            shares = min(int(shares_for_risk), max_shares)
            return self.execution_engine.round_to_lot_size(shares)

        else:
            raise ValueError(f"Unknown position sizing method: {self.position_sizing}")

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> Optional[float]:
        """Calculate Average True Range."""
        if len(df) < period:
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
        tr[0] = high[0] - low[0]  # First TR

        atr = np.mean(tr[-period:])
        return float(atr)

    def generate_buy_order(
        self,
        code: str,
        signal_date: datetime,
        price: float,
        buy_strategy: str,
        market_data: Optional[pd.DataFrame] = None
    ) -> Optional[Order]:
        """
        Generate buy order for T+1 execution.

        Args:
            code: Stock code
            signal_date: Signal generation date (T)
            price: Current price
            buy_strategy: Name of buy strategy
            market_data: Historical data for risk-based sizing

        Returns:
            Order object or None if cannot buy
        """
        # Check if can open new position
        if not self.can_open_new_position():
            return None

        # Check if already have position
        if code in self.positions:
            return None

        # Calculate position size
        shares = self.calculate_position_size(code, price, market_data)
        if shares == 0:
            return None

        # Create order for T+1 execution
        execution_date = signal_date + timedelta(days=1)
        order = Order(
            code=code,
            action=OrderAction.BUY,
            shares=shares,
            signal_date=signal_date,
            execution_date=execution_date,
            buy_strategy=buy_strategy
        )

        self.pending_orders.append(order)
        return order

    def generate_sell_order(
        self,
        code: str,
        signal_date: datetime,
        reason: str
    ) -> Optional[Order]:
        """
        Generate sell order for T+1 execution.

        Args:
            code: Stock code
            signal_date: Signal generation date (T)
            reason: Exit reason

        Returns:
            Order object or None if cannot sell
        """
        # Check if have position
        if code not in self.positions:
            return None

        # Check if position is sellable (T+1 settlement)
        if not self.settlement_tracker.can_sell_position(code, signal_date):
            return None

        position = self.positions[code]

        # Create order for T+1 execution
        execution_date = signal_date + timedelta(days=1)
        order = Order(
            code=code,
            action=OrderAction.SELL,
            shares=position.shares,
            signal_date=signal_date,
            execution_date=execution_date,
            reason=reason,
            buy_strategy=position.buy_strategy
        )

        self.pending_orders.append(order)
        return order

    def execute_pending_orders(
        self,
        current_date: datetime,
        market_data: Dict[str, pd.DataFrame]
    ) -> List[Order]:
        """
        Execute pending orders for current date.

        Args:
            current_date: Current date (T+1)
            market_data: Market data for all stocks {code: full_dataframe}

        Returns:
            List of executed/failed orders
        """
        executed_orders = []
        remaining_orders = []

        for order in self.pending_orders:
            # Check if order is for today
            if order.execution_date != current_date:
                remaining_orders.append(order)
                continue

            # Get market data
            if order.code not in market_data:
                order.fail()
                executed_orders.append(order)
                continue

            df = market_data[order.code]
            df_today = df[df['date'] == current_date]

            if len(df_today) == 0:
                order.fail()
                executed_orders.append(order)
                continue

            current_data = df_today.iloc[-1]

            # Get previous close for price limit check
            df_prev = df[df['date'] < current_date]
            if len(df_prev) == 0:
                order.fail()
                executed_orders.append(order)
                continue

            prev_close = df_prev.iloc[-1]['close']

            # Validate data
            if not self.execution_engine.validate_data(current_data):
                order.fail()
                executed_orders.append(order)
                continue

            # Check if can execute
            can_execute, fail_reason = self.execution_engine.can_execute_order(
                order, current_data, prev_close
            )

            if not can_execute:
                order.fail()
                order.reason = fail_reason if order.reason is None else order.reason
                executed_orders.append(order)
                continue

            # Execute order
            open_price = current_data['open']
            success = self.execution_engine.execute_order(order, open_price)

            if success:
                # Update portfolio
                if order.action == OrderAction.BUY:
                    self._execute_buy(order, current_date)
                else:
                    self._execute_sell(order, current_date, current_data)

                executed_orders.append(order)

        self.pending_orders = remaining_orders
        return executed_orders

    def _execute_buy(self, order: Order, execution_date: datetime):
        """Execute buy order and create position."""
        # Deduct cash
        self.cash -= order.total_cost

        # Create position
        position = Position(
            code=order.code,
            entry_date=execution_date,
            entry_price=order.execution_price,
            shares=order.shares,
            cost_basis=order.total_cost,
            buy_strategy=order.buy_strategy
        )

        self.positions[order.code] = position

        # T+1 settlement: position sellable on next day
        self.settlement_tracker.freeze_position(
            order.code,
            execution_date + timedelta(days=1)
        )

    def _execute_sell(self, order: Order, execution_date: datetime, current_data: pd.Series):
        """Execute sell order and close position."""
        # Get position
        position = self.positions[order.code]

        # Calculate max unrealized P&L during holding
        max_unrealized_pnl_pct = (position.highest_price_since_entry - position.entry_price) / position.entry_price

        # Create trade record
        trade = Trade(
            code=order.code,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            shares=position.shares,
            entry_cost=position.cost_basis,
            buy_strategy=position.buy_strategy,
            exit_date=execution_date,
            exit_price=order.execution_price,
            exit_proceeds=order.net_proceeds,
            exit_reason=order.reason or "Unknown",
            holding_days=position.days_held,
            max_unrealized_pnl_pct=max_unrealized_pnl_pct
        )

        self.trades.append(trade)

        # Add proceeds (T+1 settlement)
        settlement_date = execution_date + timedelta(days=1)
        self.settlement_tracker.add_pending_proceeds(order.net_proceeds, settlement_date)
        
        # Add proceeds immediately (T+0 availability for trading)
        # In A-shares, sell proceeds are immediately available for new buys
        #self.cash += order.net_proceeds

        # Remove position
        del self.positions[order.code]

    def process_settlement(self, current_date: datetime):
        """
        Process T+1 settlement for current date.

        Args:
            current_date: Current date
        """
        released_cash, received_proceeds = self.settlement_tracker.settle(current_date)
        self.cash += received_proceeds

    def get_available_cash(self) -> float:
        """
        Get available cash for trading.

        Returns:
            Available cash (excluding frozen cash)
        """
        return self.cash - self.settlement_tracker.get_total_frozen_cash()

    def get_position(self, code: str) -> Optional[Position]:
        """Get position for stock code."""
        return self.positions.get(code)

    def has_position(self, code: str) -> bool:
        """Check if has position in stock."""
        return code in self.positions

    def get_equity_curve_df(self) -> pd.DataFrame:
        """Get equity curve as DataFrame."""
        if not self.equity_curve:
            return pd.DataFrame()
        return pd.DataFrame(self.equity_curve)

    def get_trades_df(self) -> pd.DataFrame:
        """Get trade history as DataFrame."""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([trade.to_dict() for trade in self.trades])
