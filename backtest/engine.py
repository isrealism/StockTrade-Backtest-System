"""
Event-driven backtesting engine.

Core orchestrator for backtesting trading strategies on Chinese A-share market.
"""

import os
import json
import importlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import pandas as pd
import numpy as np

from .data_structures import BuySignal
from .portfolio import PortfolioManager
from .execution import ExecutionEngine


class BacktestEngine:
    """
    Event-driven backtesting engine.

    Main loop:
    1. For each trading date:
       - Process T+1 settlement
       - Get buy signals from selectors
       - Check sell conditions for positions
       - Execute pending orders
       - Generate new orders for T+1
       - Update equity curve
    """

    def __init__(
        self,
        data_dir: str,
        buy_config_path: str,
        sell_strategy_config: Dict[str, Any],
        start_date: str,
        end_date: str,
        initial_capital: float = 1000000,
        max_positions: int = 10,
        position_sizing: str = "equal_weight",
        commission_rate: float = 0.0003,
        stamp_tax_rate: float = 0.001,
        slippage_rate: float = 0.001
    ):
        """
        Initialize backtesting engine.

        Args:
            data_dir: Directory with historical data (./data/*.csv)
            buy_config_path: Path to configs.json (buy strategies)
            sell_strategy_config: Sell strategy configuration dict
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            initial_capital: Starting capital
            max_positions: Maximum positions
            position_sizing: Position sizing method
            commission_rate: Commission rate
            stamp_tax_rate: Stamp tax rate
            slippage_rate: Slippage rate
        """
        self.data_dir = Path(data_dir)
        self.buy_config_path = buy_config_path
        self.sell_strategy_config = sell_strategy_config
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)

        # Initialize components
        execution_engine = ExecutionEngine(
            commission_rate=commission_rate,
            stamp_tax_rate=stamp_tax_rate,
            slippage_rate=slippage_rate
        )

        self.portfolio = PortfolioManager(
            initial_capital=initial_capital,
            max_positions=max_positions,
            position_sizing=position_sizing,
            execution_engine=execution_engine
        )

        # Load data
        self.market_data: Dict[str, pd.DataFrame] = {}
        self.trading_dates: List[datetime] = []

        # Buy selectors
        self.buy_selectors: List[Any] = []

        # Sell strategy
        self.sell_strategy = None

        # Logging
        self.logs: List[str] = []

    def load_data(self, stock_codes: Optional[List[str]] = None, lookback_days: int = 200):
        """
        Load historical data from CSV files.

        Args:
            stock_codes: List of stock codes (e.g., ['000001', '000002'])
                        If None, loads all files in data_dir
            lookback_days: Number of calendar days before start_date to load for indicator calculations
                          Default 200 days ensures ~140 trading days for MA120, BBI, etc.
        """
        self.log("Loading market data...")

        # Calculate data load start date (before backtest start for indicator calculations)
        data_start_date = self.start_date - timedelta(days=lookback_days)
        self.log(f"Loading data from {data_start_date.date()} (backtest starts {self.start_date.date()})")

        if stock_codes is None:
            # Load all CSV files
            csv_files = list(self.data_dir.glob("*.csv"))
        else:
            csv_files = [self.data_dir / f"{code}.csv" for code in stock_codes]

        loaded_count = 0
        for csv_file in csv_files:
            if not csv_file.exists():
                continue

            try:
                df = pd.read_csv(csv_file)

                # Parse date column
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                else:
                    self.log(f"Warning: {csv_file.name} missing 'date' column")
                    continue

                # Sort by date
                df = df.sort_values('date').reset_index(drop=True)

                # Load data from lookback period, but only up to backtest end
                # This gives selectors historical context while preventing lookahead bias
                df = df[(df['date'] >= data_start_date) & (df['date'] <= self.end_date)]

                if len(df) == 0:
                    continue

                # Extract code from filename (e.g., "000001.csv" -> "000001")
                code = csv_file.stem

                self.market_data[code] = df
                loaded_count += 1

            except Exception as e:
                self.log(f"Error loading {csv_file.name}: {e}")

        self.log(f"Loaded {loaded_count} stocks")

        # Build trading dates (union of all dates within backtest period)
        all_dates = set()
        for df in self.market_data.values():
            # Only include dates within the backtest period
            backtest_dates = df[(df['date'] >= self.start_date) & (df['date'] <= self.end_date)]['date'].tolist()
            all_dates.update(backtest_dates)

        self.trading_dates = sorted(list(all_dates))
        self.log(f"Trading dates: {len(self.trading_dates)} days from {self.trading_dates[0].date()} to {self.trading_dates[-1].date()}")

        # Validate data quality
        self.validate_data_quality()

    def validate_data_quality(self):
        """Check if data meets selector requirements."""
        self.log("\nValidating data quality...")

        if not self.market_data:
            self.log("  WARNING: No market data loaded")
            return

        # 检查在start_date时每只股票的数据长度，以确保常用指标可计算
        lengths_at_start = []
        for df in self.market_data.values():
            df_at_start = df[df['date'] <= self.start_date]
            if len(df_at_start) > 0:
                lengths_at_start.append(len(df_at_start))

        if not lengths_at_start:
            self.log("  WARNING: No data available at backtest start date")
            return

        self.log(f"  Stocks loaded: {len(self.market_data)}")
        self.log(f"  Data available at backtest start ({self.start_date.date()}):")
        self.log(f"    Min data length: {min(lengths_at_start)} days")
        self.log(f"    Max data length: {max(lengths_at_start)} days")
        self.log(f"    Median data length: {sorted(lengths_at_start)[len(lengths_at_start)//2]} days")

        # 统计不满足常用指标计算要求的股票数量
        insufficient_60ma = sum(1 for l in lengths_at_start if l < 60)
        insufficient_120 = sum(1 for l in lengths_at_start if l < 120)

        self.log(f"    Stocks with <60 days (MA60 won't work): {insufficient_60ma}")
        self.log(f"    Stocks with <120 days (max_window): {insufficient_120}")

        if insufficient_120 > len(lengths_at_start) * 0.5:  
            self.log("  WARNING: >50% of stocks have <120 days data at backtest start")
            self.log("          Consider using later start_date or increase lookback_days")     # 如果多数股票数据不足，建议将回测开始日期推迟或增加预加载天数

    def load_buy_selectors(self):

        """
        从config.json加载买入选股器。将所有选股器的实例、别名和类名存储在self.buy_selectors列表中。
        """

        self.log("Loading buy selectors...")

        with open(self.buy_config_path, 'r', encoding='utf-8') as f:        # 初始化 BacktestEngine 时传入的路径，指向configs，以只读模式打开并自动关闭
            config = json.load(f)       # 读取JSON内容并解析为Python字典

        # Import Selector module
        import sys      # 导入 sys 模块以操作模块搜索路径
        sys.path.insert(0, str(Path(self.buy_config_path).parent.parent))  # buy_config_path 是初始化时传入的配置文件路径，path.parent.parent 获取该路径的父目录的父目录（项目根目录），sys.path.insert(0, ...) 将该目录添加到模块搜索路径的最前面，确保后续导入模块时优先从该目录查找
        import Selector

        for selector_config in config.get('selectors', []):     # 遍历配置文件中的每个选股器配置
            if not selector_config.get('activate', False):      # 检查配置中的 'activate' 字段是否为 True，若为 False 则跳过该选股器
                continue

            class_name = selector_config['class']
            params = selector_config.get('params', {})

            # Get class from Selector module
            if not hasattr(Selector, class_name):
                self.log(f"Warning: {class_name} not found in Selector.py")
                continue

            selector_class = getattr(Selector, class_name)      # 通过类名字符串从 Selector 模块中获取对应的类对象
            selector = selector_class(**params)               # 使用配置中的参数实例化选股器类

            self.buy_selectors.append({
                'instance': selector,
                'alias': selector_config.get('alias', class_name),
                'class': class_name
            })

        self.log(f"Loaded {len(self.buy_selectors)} buy selectors")

    def load_sell_strategy(self):
        """Load sell strategy from configuration."""
        self.log("Loading sell strategy...")

        # Import sell strategy module
        from .sell_strategies.base import create_sell_strategy      # 从 base 模块中导入 create_sell_strategy 函数

        self.sell_strategy = create_sell_strategy(self.sell_strategy_config)        # 使用传入的卖出策略配置创建卖出策略实例
        self.log(f"Loaded sell strategy: {self.sell_strategy_config.get('name', 'Unknown')}")

    def get_buy_signals(self, date: datetime) -> List[BuySignal]:
        """
        Get buy signals from all selectors for given date.

        CRITICAL: Prevents lookahead bias by only using data up to current date.

        Args:
            date: Current date

        Returns:
            List of buy signals
        """
        signals = []

        # Prepare data for selectors (only up to current date)
        data_for_selectors = {}
        for code, df in self.market_data.items():
            df_up_to_date = df[df['date'] <= date].copy()       # 仅使用截至当前日期的数据，防止未来数据泄露
            if len(df_up_to_date) > 0:
                data_for_selectors[code] = df_up_to_date        # 仅包含有数据的股票，将截至当前日期的数据存入字典

        # Log data readiness
        self.log(f"  Data prepared: {len(data_for_selectors)} stocks available")

        # Get signals from each selector
        for selector_info in self.buy_selectors:
            try:
                selected_codes = selector_info['instance'].select(      # 调用Selector模块中各种选股器的select（）函数获取selected_codes
                    date,
                    data_for_selectors
                )

                # Log per-selector results
                self.log(f"  {selector_info['alias']}: {len(selected_codes)} signals")      # 记录每种选股器选出来的信号

                for code in selected_codes:
                    signal = BuySignal(
                        code=code,
                        date=date,
                        strategy_name=selector_info['class'],
                        strategy_alias=selector_info['alias']
                    )
                    signals.append(signal)      #  将每个选中的股票代码封装成BuySignal对象并添加到signals列表中

            except Exception as e:
                # Enhanced error logging with stack trace
                import traceback
                self.log(f"  ERROR in {selector_info['alias']}: {e}")   
                self.log(f"  Traceback: {traceback.format_exc()}")

        # Summary
        self.log(f"  Total signals: {len(signals)}")
        return signals

    def check_sell_signals(self, date: datetime) -> List[tuple[str, str]]:
        """
        Check sell conditions for all positions.

        CRITICAL: Prevents lookahead bias by only using data up to current date.

        Args:
            date: Current date

        Returns:
            List of (code, exit_reason) tuples
        """
        sell_signals = []

        for code, position in list(self.portfolio.positions.items()):       # 遍历当前持仓中的每只股票
            # Get historical data up to current date
            if code not in self.market_data:        # 如果当前持仓股票在市场数据中不存在，跳过
                continue

            df = self.market_data[code]     # 获取该股票的历史数据
            df_up_to_date = df[df['date'] <= date].copy()       # 仅使用截至当前日期的数据，防止未来数据泄露

            if len(df_up_to_date) == 0:     # 如果截至当前日期没有数据，跳过
                continue

            # Get current price data
            df_today = df_up_to_date[df_up_to_date['date'] == date]     # 获取当前日期的行情数据
            if len(df_today) == 0:          # 如果当前日期没有数据，跳过
                continue

            current_data = df_today.iloc[-1]        # 获取当前日期的最后一行数据（通常只有一行）

            # Check sell strategy
            try:
                should_sell, reason = self.sell_strategy.should_sell(       # 调用卖出策略的should_sell（）函数判断是否满足卖出条件
                    position=position,
                    current_date=date,
                    current_data=current_data,
                    hist_data=df_up_to_date
                )

                if should_sell:
                    sell_signals.append((code, reason))     # 如果满足卖出条件，将股票代码和卖出原因添加到sell_signals列表中

            except Exception as e:
                self.log(f"Error checking sell for {code}: {e}")

        return sell_signals

    def run(self):
        """
        Run backtest.

        Main event loop over trading dates.
        """
        self.log("\n" + "="*80)
        self.log("BACKTEST START")
        self.log("="*80)

        for date in self.trading_dates:
            self.log(f"\n--- {date.date()} ---")

            # 1. Process T+1 settlement
            self.portfolio.process_settlement(date)     # 处理T+1结算，更新持仓和现金等信息

            # 2. Execute pending orders (from T-1)
            market_data_today = {
                code: df for code, df in self.market_data.items()       # 获取当天的市场数据
            }
            executed_orders = self.portfolio.execute_pending_orders(date, market_data_today)    # 执行待处理订单

            for order in executed_orders:
                if order.status.value == "EXECUTED":
                    self.log(f"  EXECUTED {order.action.value}: {order.code} x {order.shares} @ {order.execution_price:.2f}")
                else:
                    self.log(f"  FAILED {order.action.value}: {order.code} - {order.reason}")

            # 3. Update position metrics
            current_market_data = {}
            for code in self.market_data:
                df = self.market_data[code]
                df_today = df[df['date'] == date]
                if len(df_today) > 0:
                    current_market_data[code] = df_today.iloc[-1]

            self.portfolio.update_positions(date, current_market_data)      # 更新持仓的最高价格和持有天数

            # 4. Check sell signals
            sell_signals = self.check_sell_signals(date)    # 检查卖出信号
            for code, reason in sell_signals:       
                # Get current price for logging
                if code in current_market_data:
                    current_price = current_market_data[code]['close']
                    position = self.portfolio.get_position(code)
                    if position:
                        unrealized_pnl_pct = position.unrealized_pnl_pct(current_price) * 100
                        self.log(f"  SELL SIGNAL: {code} ({reason}) P&L: {unrealized_pnl_pct:+.2f}%")       # 记录卖出信号、卖出原因和未实现收益率百分比

                # Generate sell order for T+1
                self.portfolio.generate_sell_order(code, date, reason)

            # 5. Get buy signals
            buy_signals = self.get_buy_signals(date)        # 获取买入信号

            # 6. Generate buy orders for T+1
            for signal in buy_signals:
                # Get current price
                if signal.code in current_market_data:
                    current_price = current_market_data[signal.code]['close']       # 获取买入信号的当前收盘

                    # Get historical data for position sizing
                    df = self.market_data[signal.code]
                    df_up_to_date = df[df['date'] <= date]      # 获取信号股票截止当日的数据

                    order = self.portfolio.generate_buy_order(
                        code=signal.code,
                        signal_date=date,
                        price=current_price,
                        buy_strategy=signal.strategy_alias,
                        market_data=df_up_to_date
                    )

                    if order:
                        self.log(f"  BUY SIGNAL: {signal.code} ({signal.strategy_alias}) {order.shares} shares @ ~{current_price:.2f}")

            # 7. Update equity curve
            self.portfolio.update_equity_curve(date, current_market_data)

            # Log portfolio summary
            self.log(f"  Portfolio: {len(self.portfolio.positions)} positions, Cash: {self.portfolio.cash:,.0f}, Total: {self.portfolio.total_value:,.0f}")

        self.log("\n" + "="*80)
        self.log("BACKTEST COMPLETE")
        self.log("="*80 + "\n")

    def get_results(self) -> Dict[str, Any]:
        """
        Get backtest results.

        Returns:
            Dictionary with equity curve, trades, and basic stats
        """
        equity_curve = self.portfolio.get_equity_curve_df()
        trades = self.portfolio.get_trades_df()

        results = {
            'equity_curve': equity_curve.to_dict('records') if not equity_curve.empty else [],
            'trades': trades.to_dict('records') if not trades.empty else [],
            'final_value': self.portfolio.total_value,
            'total_return': (self.portfolio.total_value - self.portfolio.initial_capital) / self.portfolio.initial_capital,
            'num_trades': len(self.portfolio.trades),
            'num_positions': len(self.portfolio.positions)
        }

        return results

    def log(self, message: str):
        """Log message to console and internal log."""
        print(message)
        self.logs.append(message)
