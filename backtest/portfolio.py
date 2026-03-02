"""
Portfolio management module.

Handles positions, cash, order generation, and position sizing.

修复日志
--------
v2 (current):
  FIX-1  _execute_sell: 删除 add_pending_proceeds，卖出收益只加一次（原来双重计账）
  FIX-2  process_settlement: 不再把 received_proceeds 加回 cash（双重计账的另一端）
  FIX-3  generate_buy_order / generate_sell_order: 用 _next_trading_date() 替代
         timedelta(days=1)，避免周末/节假日产生永不执行的僵尸订单
  FIX-4  execute_pending_orders: 过期订单（execution_date < current_date）直接取消，
         防止僵尸订单永久占据仓位名额和可用资金
  FIX-5  get_available_cash: 扣除 pending buy orders 成本，但只计算真实交易日的订单
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
import numpy as np

from .data_structures import Position, Order, Trade, OrderAction, OrderStatus
from .execution import ExecutionEngine, T1SettlementTracker


class PortfolioManager:
    """
    Manages portfolio positions and cash.
    """

    def __init__(
        self,
        initial_capital: float,
        max_positions: int = 10,
        position_sizing: str = "equal_weight",
        execution_engine: Optional[ExecutionEngine] = None
    ):
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

        # FIX-3: 交易日列表，由 engine.run() 在主循环前注入
        # 用于 _next_trading_date() 找到真实的下一交易日
        self._trading_dates: List[datetime] = []
        self._trading_dates_set: Set[datetime] = set()

    # ──────────────────────────────────────────────────────────────
    # FIX-3: 核心辅助方法
    # ──────────────────────────────────────────────────────────────

    def _next_trading_date(self, signal_date: datetime) -> datetime:
        """
        返回 signal_date 之后（不含当天）的下一个真实交易日。

        若 trading_dates 未注入（旧用法兼容），退化为日历 +1 天。
        这是修复"周末僵尸订单"的关键：周五信号 → 下一个交易日是下周一，
        而非日历上的周六（周六永远不会被 execute_pending_orders 处理到）。
        """
        if self._trading_dates:
            for td in self._trading_dates:
                if td > signal_date:
                    return td
        # 未注入或超出范围，退化为 +1
        return signal_date + timedelta(days=1)

    def set_trading_dates(self, trading_dates: List[datetime]) -> None:
        """由 engine.run() 在主循环前调用，注入交易日历。"""
        self._trading_dates = sorted(trading_dates)
        self._trading_dates_set = set(trading_dates)

    # ──────────────────────────────────────────────────────────────
    # Equity curve
    # ──────────────────────────────────────────────────────────────

    def update_equity_curve(self, date: datetime, market_data: Dict[str, pd.Series]):
        position_value = 0.0
        for code, position in self.positions.items():
            if code in market_data:
                current_price = market_data[code]['close']
                position_value += position.shares * current_price

        self.total_value = self.cash + position_value

        self.equity_curve.append({
            'date': date,
            'cash': self.cash,
            'position_value': position_value,
            'total_value': self.total_value,
            'num_positions': len(self.positions),
            'frozen_cash': self.settlement_tracker.get_total_frozen_cash(),
            'pending_proceeds': self.settlement_tracker.get_total_pending_proceeds(),
        })

    def update_positions(self, date: datetime, market_data: Dict[str, pd.Series]):
        for code, position in self.positions.items():
            if code in market_data:
                data = market_data[code]
                if float(data.get('volume', 0)) == 0:
                    continue
                position.update_price_stats(
                    date=date,
                    close=float(data['close']),
                    high=float(data['high']),
                    low=float(data['low'])
                )
                position.increment_days_held()

    # ──────────────────────────────────────────────────────────────
    # Position limits
    # ──────────────────────────────────────────────────────────────

    def can_open_new_position(self) -> bool:
        total_positions = len(self.positions) + self._count_pending_buy_orders()
        return total_positions < self.max_positions

    def _count_pending_buy_orders(self) -> int:
        """只计算真实交易日的 pending buy orders，排除僵尸订单。"""
        count = 0
        for order in self.pending_orders:
            if (order.action == OrderAction.BUY
                    and order.status == OrderStatus.PENDING):
                # 若 trading_dates 已注入，只计算 execution_date 在已知交易日内的订单
                if (not self._trading_dates_set
                        or order.execution_date in self._trading_dates_set):
                    count += 1
        return count

    # ──────────────────────────────────────────────────────────────
    # FIX-5: get_available_cash
    # ──────────────────────────────────────────────────────────────

    def get_available_cash(self) -> float:
        """
        返回当前可用于交易的现金。

        扣除 frozen_cash（买入时预占）和真实待执行买单的预估成本。
        僵尸订单（execution_date 不在交易日集合内）不参与扣减。
        """
        pending_buy_cost = sum(
            order.total_cost
            for order in self.pending_orders
            if (
                order.action == OrderAction.BUY
                and order.status == OrderStatus.PENDING
                and order.total_cost is not None
                and order.total_cost > 0
                and (not self._trading_dates_set
                     or order.execution_date in self._trading_dates_set)
            )
        )
        return max(0.0,
                   self.cash
                   - self.settlement_tracker.get_total_frozen_cash()
                   - pending_buy_cost)

    def get_projected_cash(self, execution_date: datetime, buffer_pct: float = 0.98) -> float:
        """
        预测 execution_date 当天可用的现金（用于仓位计算）。
        """
        projected = self.cash

        # 加上在 execution_date 结算的卖出收益（当前已归 0，FIX-2 后 pending_proceeds 不再含 sell 数据）
        projected += self.settlement_tracker.pending_proceeds.get(execution_date, 0.0)

        # 减去同一执行日的其他待买订单成本
        for order in self.pending_orders:
            if (order.action == OrderAction.BUY
                    and order.execution_date == execution_date
                    and order.status == OrderStatus.PENDING
                    and order.total_cost is not None
                    and order.total_cost > 0):
                projected -= order.total_cost

        return max(0.0, projected * buffer_pct)

    # ──────────────────────────────────────────────────────────────
    # Position sizing
    # ──────────────────────────────────────────────────────────────

    def calculate_position_size(
        self,
        code: str,
        price: float,
        market_data: Optional[pd.DataFrame] = None,
        projected_cash: Optional[float] = None,
    ) -> int:
        if self.position_sizing == "equal_weight":
            total_positions = len(self.positions) + self._count_pending_buy_orders()
            available_cash = projected_cash if projected_cash is not None else self.get_available_cash()

            remaining_slots = max(1, self.max_positions - total_positions)
            target_per_position = available_cash / remaining_slots

            if target_per_position <= 0:
                return 0

            shares = self.execution_engine.calculate_max_shares(target_per_position, price)

            if shares > 0:
                estimated_cost = self.execution_engine.estimate_buy_cost(shares, price)
                if estimated_cost > available_cash:
                    return 0

            return shares

        elif self.position_sizing == "risk_based":
            if market_data is None or len(market_data) < 14:
                return self.calculate_position_size(code, price, None, projected_cash=projected_cash)

            atr = self._calculate_atr(market_data, period=14)
            if atr is None or atr <= 0:
                return self.calculate_position_size(code, price, None)

            risk_per_position = self.initial_capital * 0.01
            stop_distance = atr * 2
            shares_for_risk = risk_per_position / stop_distance

            cash_limit = projected_cash if projected_cash is not None else self.cash
            max_shares = self.execution_engine.calculate_max_shares(cash_limit, price)

            shares = min(int(shares_for_risk), max_shares)
            return self.execution_engine.round_to_lot_size(shares)

        else:
            raise ValueError(f"Unknown position sizing method: {self.position_sizing}")

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> Optional[float]:
        if len(df) < period:
            return None

        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        close = df['close'].values.astype(float)

        # 用切片对齐替代 np.roll（避免边界问题）
        prev_close = np.concatenate([[close[0]], close[:-1]])
        tr = np.maximum(
            high - low,
            np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
        )
        tr[0] = high[0] - low[0]

        return float(np.mean(tr[-period:]))

    # ──────────────────────────────────────────────────────────────
    # Order generation — FIX-3: 用真实下一交易日
    # ──────────────────────────────────────────────────────────────

    def generate_buy_order(
        self,
        code: str,
        signal_date: datetime,
        price: float,
        buy_strategy: str,
        market_data: Optional[pd.DataFrame] = None,
        signal_score: float = 0.0,
    ) -> Optional[Order]:
        if not self.can_open_new_position():
            return None
        if code in self.positions:
            return None

        # FIX-3: 用下一个真实交易日，而非日历 +1
        execution_date = self._next_trading_date(signal_date)

        projected_cash = self.get_projected_cash(execution_date)
        shares = self.calculate_position_size(code, price, market_data, projected_cash=projected_cash)
        if shares == 0:
            return None

        order = Order(
            code=code,
            action=OrderAction.BUY,
            shares=shares,
            signal_date=signal_date,
            execution_date=execution_date,
            buy_strategy=buy_strategy,
        )
        estimated_cost = self.execution_engine.estimate_buy_cost(shares, price)
        order.total_cost = estimated_cost
        order._signal_score = signal_score

        self.pending_orders.append(order)
        return order

    def generate_sell_order(
        self,
        code: str,
        signal_date: datetime,
        reason: str,
    ) -> Optional[Order]:
        if code not in self.positions:
            return None
        if not self.settlement_tracker.can_sell_position(code, signal_date):
            return None

        for o in self.pending_orders:
            if o.code == code and o.action == OrderAction.SELL:
                return None  # 已有卖单，不再重复生成

        position = self.positions[code]

        # FIX-3: 同样用下一个真实交易日
        execution_date = self._next_trading_date(signal_date)

        order = Order(
            code=code,
            action=OrderAction.SELL,
            shares=position.shares,
            signal_date=signal_date,
            execution_date=execution_date,
            reason=reason,
            buy_strategy=position.buy_strategy,
        )
        self.pending_orders.append(order)
        return order

    # ──────────────────────────────────────────────────────────────
    # Order execution — FIX-4: 过期订单自动取消
    # ──────────────────────────────────────────────────────────────

    def execute_pending_orders(
        self,
        current_date: datetime,
        market_data: Dict[str, pd.DataFrame],
    ) -> List[Order]:
        executed_orders = []
        remaining_orders = []

        for order in self.pending_orders:
            # FIX-4: 过期订单（execution_date 已过但从未执行）→ 直接取消
            # 这种情况发生在 trading_dates 未注入时（退化路径），或数据缺失时
            if order.execution_date < current_date:
                order.fail()
                order.reason = (
                    f"EXPIRED: scheduled for {order.execution_date.date()}, "
                    f"executed on {current_date.date()} — cancelled"
                )
                executed_orders.append(order)
                continue

            # 还没到执行日，保留
            if order.execution_date != current_date:
                remaining_orders.append(order)
                continue

            # ── 以下是原有执行逻辑（不变）────────────────────────────────
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

            df_prev = df[df['date'] < current_date]
            if len(df_prev) == 0:
                order.fail()
                executed_orders.append(order)
                continue

            prev_close = df_prev.iloc[-1]['close']

            if not self.execution_engine.validate_data(current_data):
                order.fail()
                executed_orders.append(order)
                continue

            can_execute, fail_reason = self.execution_engine.can_execute_order(
                order, current_data, prev_close
            )
            if not can_execute:
                order.fail()
                order.reason = fail_reason if order.reason is None else order.reason
                executed_orders.append(order)
                continue

            open_price = current_data['open']
            success = self.execution_engine.execute_order(order, open_price)

            if success:
                if order.action == OrderAction.BUY:
                    self._execute_buy(order, current_date)
                else:
                    self._execute_sell(order, current_date, current_data)

            executed_orders.append(order)

        self.pending_orders = remaining_orders
        return executed_orders

    # ──────────────────────────────────────────────────────────────
    # Internal execution helpers
    # ──────────────────────────────────────────────────────────────

    def _execute_buy(self, order: Order, execution_date: datetime):
        """Execute buy order and create position."""
        if self.cash < order.total_cost:
            print(
                f"WARNING: Insufficient cash for buy order {order.code}: "
                f"cash={self.cash:.2f}, required={order.total_cost:.2f}. Order rejected."
            )
            order.fail()
            return

        self.cash -= order.total_cost

        if self.cash < -1e-6:
            self.cash += order.total_cost
            print(
                f"ERROR: Cash went negative after deduction: {self.cash:.8f}. "
                f"Order rejected for {order.code}."
            )
            order.fail()
            return

        if self.cash < 0:
            self.cash = 0.0

        position = Position(
            code=order.code,
            entry_date=execution_date,
            entry_price=order.execution_price,
            shares=order.shares,
            cost_basis=order.total_cost,
            buy_strategy=order.buy_strategy,
        )

        # 写入 entry_score
        entry_score: float = getattr(order, '_signal_score', 0.0)
        is_rotation = False
        if not entry_score and order.reason and 'entry_score=' in (order.reason or ''):
            try:
                entry_score = float(
                    order.reason.split('entry_score=')[1].split('|')[0].split('\n')[0]
                )
                is_rotation = 'rotation_entry' in order.reason
            except (ValueError, IndexError):
                pass
        if entry_score:
            position.buy_signal_data = {
                'entry_score': entry_score,
                'rotation': is_rotation,
            }

        self.positions[order.code] = position
        self.settlement_tracker.freeze_position(
            order.code,
            execution_date + timedelta(days=1)
        )

    def _execute_sell(self, order: Order, execution_date: datetime, current_data: pd.Series):
        """Execute sell order and close position.
        """
        if order.code not in self.positions:
            print(f"WARNING: _execute_sell called for {order.code} but position not found. Skipping.")
            order.fail()
            return

        position = self.positions[order.code]

        max_unrealized_pnl_pct = (
            (position.highest_price_since_entry - position.entry_price)
            / position.entry_price
        )

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
            max_unrealized_pnl_pct=max_unrealized_pnl_pct,
        )
        self.trades.append(trade)

        # FIX-1: 只加一次 cash，不再调用 add_pending_proceeds
        # A 股规则：卖出当日资金即可用于新买入（T+0 资金可用）
        self.cash += order.net_proceeds

        del self.positions[order.code]

    # ──────────────────────────────────────────────────────────────
    # FIX-2: process_settlement — 不再重复加 cash
    # ──────────────────────────────────────────────────────────────

    def process_settlement(self, current_date: datetime):
        """
        Process T+1 settlement.

        FIX-2: 删除 self.cash += received_proceeds。
               卖出收益在 _execute_sell 时已即时更新，此处不再重复。
               settle() 只负责清理 tracker 内的过期冻结记录。
        """
        # 清理 tracker（frozen_cash / pending_proceeds / frozen_positions）
        self.settlement_tracker.settle(current_date)
        # 注意：不再有 self.cash += received_proceeds

    # ──────────────────────────────────────────────────────────────
    # Accessors
    # ──────────────────────────────────────────────────────────────

    def get_position(self, code: str) -> Optional[Position]:
        return self.positions.get(code)

    def has_position(self, code: str) -> bool:
        return code in self.positions

    def get_equity_curve_df(self) -> pd.DataFrame:
        if not self.equity_curve:
            return pd.DataFrame()
        return pd.DataFrame(self.equity_curve)

    def get_trades_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([trade.to_dict() for trade in self.trades])