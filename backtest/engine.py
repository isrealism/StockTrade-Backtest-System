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
        slippage_rate: float = 0.001,
        buy_config: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Any] = None,
        use_indicator_db: bool = False,  # 新增：是否使用指标数据库
        indicator_db_path: str = "./data/indicators.db"  # 新增：数据库路径
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
            use_indicator_db: Whether to use pre-computed indicator database
            indicator_db_path: Path to indicator database
        """
        self.data_dir = Path(data_dir)
        self.buy_config_path = buy_config_path
        self.buy_config = buy_config
        self.sell_strategy_config = sell_strategy_config
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)

        # Indicator database (新增)
        self.use_indicator_db = use_indicator_db
        self.indicator_db_path = indicator_db_path
        self.indicator_store = None

        if use_indicator_db:
            from .indicator_store import IndicatorStore
            self.indicator_store = IndicatorStore(indicator_db_path)

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

        # Selector combination config
        self.combination_mode = "OR"  # Default to OR for backward compatibility
        self.time_window_days = 5
        self.required_selectors = []

        # Signal history tracking (for TIME_WINDOW mode)
        self.signal_history: Dict[datetime, Dict[str, List[str]]] = {}
        # Structure: {date: {selector_name: [code1, code2, ...]}}

        # Sequential confirmation settings (for SEQUENTIAL_CONFIRMATION mode)
        self.trigger_selectors: List[str] = []
        self.trigger_logic = "OR"
        self.confirm_selectors: List[str] = []
        self.confirm_logic = "OR"
        self.buy_timing = "confirmation_day"

        # Track pending trigger signals waiting for confirmation
        # Structure: {code: {
        #   'trigger_date': datetime,
        #   'expiration_date': datetime,
        #   'trigger_signal': BuySignal,
        #   'triggered_by': [selector_names]
        # }}
        self.pending_triggers: Dict[str, Dict[str, Any]] = {}

        # Sell strategy
        self.sell_strategy = None

        # Logging
        self.logs: List[str] = []
        self.log_callback = log_callback

        # Data preparation cache (新增：数据准备缓存)
        self.data_cache: Dict[str, pd.DataFrame] = {}  # {code: df_up_to_current_date}
        self.cache_date: Optional[datetime] = None     # 缓存对应的日期

        # Log indicator database mode
        if self.use_indicator_db:
            self.log(f"Using indicator database: {self.indicator_db_path}")
        else:
            self.log("Using CSV data with real-time indicator computation")

    def _ensure_project_root_on_path(self):
        """Ensure project root is on sys.path for Selector imports."""
        import sys
        if self.buy_config_path:
            root = Path(self.buy_config_path).parent.parent
        else:
            root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

    def _get_data_up_to_date(self, date: datetime) -> Dict[str, pd.DataFrame]:
        """
        获取截至指定日期的数据（缓存机制）

        核心优化：
        - 缓存已过滤的 DataFrame 视图，避免重复过滤
        - 相同日期直接返回缓存
        - 新日期直接重新切片（由于 market_data 已预加载，切片很快）

        关键改进：去除 .copy()，使用视图而非副本

        Args:
            date: 目标日期

        Returns:
            Dict[股票代码, DataFrame截至date的数据]
        """
        # 如果是同一天，直接返回缓存（最常见的情况）
        if date == self.cache_date and self.data_cache:
            return self.data_cache

        # 需要更新缓存
        self.data_cache = {}
        for code, df in self.market_data.items():
            # 关键优化：去除 .copy()，直接返回视图
            # 选股器不应该修改数据，所以视图是安全的
            df_filtered = df[df['date'] <= date]
            if len(df_filtered) > 0:
                self.data_cache[code] = df_filtered

        self.cache_date = date
        return self.data_cache

    def load_data(self, stock_codes: Optional[List[str]] = None, lookback_days: int = 200):
        """
        Load historical data from CSV files or indicator database.

        Args:
            stock_codes: List of stock codes (e.g., ['000001', '000002'])
                        If None, loads all files in data_dir
            lookback_days: Number of calendar days before start_date to load for indicator calculations
                          Default 200 days ensures ~140 trading days for MA120, BBI, etc.
        """
        if self.use_indicator_db and self.indicator_store:
            self._load_data_from_db(stock_codes, lookback_days)
        else:
            self._load_data_from_csv(stock_codes, lookback_days)

    def _load_data_from_db(self, stock_codes: Optional[List[str]], lookback_days: int):
        """从指标数据库加载数据（新模式）"""
        self.log("Loading data from indicator database...")

        # Calculate data load start date
        data_start_date = self.start_date - timedelta(days=lookback_days)
        self.log(f"Loading data from {data_start_date.date()} (backtest starts {self.start_date.date()})")

        # Get stock codes
        if stock_codes is None:
            # Query all stocks from database
            codes = self.indicator_store.get_all_codes()
        else:
            codes = stock_codes

        # 优化：一次性批量读取所有代码的数据，避免对 SQLite 的 N 次往返查询
        loaded_count = 0
        try:
            df_all = self.indicator_store.get_indicators_for_codes(
                codes,
                start_date=data_start_date.strftime('%Y-%m-%d'),
                end_date=self.end_date.strftime('%Y-%m-%d'),
            )

            if df_all.empty:
                self.log("No indicator rows returned for requested codes/date range")
            else:
                # 按 code 分组并分配到 market_data
                for code, group in df_all.groupby('code'):
                    g = group.sort_values('date').reset_index(drop=True)
                    self.market_data[code] = g
                    loaded_count += 1

            self.log(f"Loaded {loaded_count} stocks from indicator database")

        except Exception as e:
            self.log(f"Error loading indicators in bulk from DB: {e}")

        # Build trading dates
        all_dates = set()
        for df in self.market_data.values():
            backtest_dates = df[(df['date'] >= self.start_date) & (df['date'] <= self.end_date)]['date'].tolist()
            all_dates.update(backtest_dates)

        self.trading_dates = sorted(list(all_dates))

        # Validate trading dates
        if len(self.trading_dates) == 0:
            raise ValueError(
                f"No trading dates found in database. "
                f"Check if database contains data for the backtest period "
                f"({self.start_date.date()} to {self.end_date.date()})"
            )

        self.log(f"Trading dates: {len(self.trading_dates)} days from {self.trading_dates[0].date()} to {self.trading_dates[-1].date()}")

        # Validate data quality
        self.validate_data_quality()

    def _load_data_from_csv(self, stock_codes: Optional[List[str]], lookback_days: int):
        """从 CSV 文件加载数据（原有逻辑）"""
        self.log("Loading market data from CSV files...")

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
                # NOTE: Pre-loading to end_date is for efficiency. Lookahead bias is prevented
                # by filtering to current_date during signal generation (see get_buy_signals, check_sell_signals)
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

        # Validate trading dates
        if len(self.trading_dates) == 0:
            raise ValueError(
                f"No trading dates found in data. "
                f"Check if data files exist in {self.data_dir} and cover the backtest period "
                f"({self.start_date.date()} to {self.end_date.date()})"
            )

        self.log(f"Trading dates: {len(self.trading_dates)} days from {self.trading_dates[0].date()} to {self.trading_dates[-1].date()}")

        # Validate data quality
        self.validate_data_quality()

    def validate_data_quality(self):
        """Check if data meets selector requirements and validate OHLC consistency."""
        self.log("\nValidating data quality...")

        if not self.market_data:
            self.log("  WARNING: No market data loaded")
            return

        # Track OHLC inconsistencies
        ohlc_issues = []
        price_issues = []

        # Check OHLC consistency: low <= open/close <= high
        for code, df in self.market_data.items():
            # Check for negative prices
            if (df['low'] < 0).any():
                price_issues.append(f"{code}: negative prices detected")

            # Check OHLC consistency
            invalid_rows = df[
                (df['low'] > df['open']) |
                (df['low'] > df['close']) |
                (df['high'] < df['open']) |
                (df['high'] < df['close'])
            ]
            if len(invalid_rows) > 0:
                ohlc_issues.append(f"{code}: {len(invalid_rows)} rows violate OHLC constraints")

        if ohlc_issues:
            self.log("  WARNING: OHLC consistency issues found:")
            for issue in ohlc_issues[:10]:  # Show first 10
                self.log(f"    - {issue}")
            if len(ohlc_issues) > 10:
                self.log(f"    ... and {len(ohlc_issues) - 10} more")

        if price_issues:
            self.log("  WARNING: Price validation issues:")
            for issue in price_issues[:5]:
                self.log(f"    - {issue}")

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

        if self.buy_config is not None:
            config = self.buy_config
        else:
            with open(self.buy_config_path, 'r', encoding='utf-8') as f:        # 初始化 BacktestEngine 时传入的路径，指向configs，以只读模式打开并自动关闭
                config = json.load(f)       # 读取JSON内容并解析为Python字典

        # Load combination settings
        if 'selector_combination' in config:
            comb = config['selector_combination']
            self.combination_mode = comb.get('mode', 'OR')
            self.time_window_days = comb.get('time_window_days', 5)
            self.required_selectors = comb.get('required_selectors', [])
            self.log(f"Selector combination mode: {self.combination_mode}")

            if self.combination_mode == "TIME_WINDOW":
                self.log(f"  Time window: {self.time_window_days} days")

            if self.combination_mode == "SEQUENTIAL_CONFIRMATION":
                # Load sequential confirmation settings
                self.trigger_selectors = comb.get('trigger_selectors', [])
                self.trigger_logic = comb.get('trigger_logic', 'OR')
                self.confirm_selectors = comb.get('confirm_selectors', [])
                self.confirm_logic = comb.get('confirm_logic', 'OR')
                self.buy_timing = comb.get('buy_timing', 'confirmation_day')

                # Validation
                if not self.trigger_selectors:
                    raise ValueError("SEQUENTIAL_CONFIRMATION mode requires 'trigger_selectors'")
                if not self.confirm_selectors:
                    raise ValueError("SEQUENTIAL_CONFIRMATION mode requires 'confirm_selectors'")

                self.log(f"  Trigger selectors ({self.trigger_logic}): {', '.join(self.trigger_selectors)}")
                self.log(f"  Confirm selectors ({self.confirm_logic}): {', '.join(self.confirm_selectors)}")
                self.log(f"  Time window: {self.time_window_days} days")
                self.log(f"  Buy timing: {self.buy_timing}")

            if self.required_selectors:
                self.log(f"  Required selectors: {', '.join(self.required_selectors)}")
        else:
            # Default: OR mode (backward compatibility)
            self.combination_mode = "OR"
            self.log("Selector combination mode: OR (default)")

        # Import Selector module
        import sys      # 导入 sys 模块以操作模块搜索路径
        self._ensure_project_root_on_path()
        import backtest.Selector as Selector

        for selector_config in config.get('selectors', []):     # 遍历配置文件中的每个选股器配置
            if not selector_config.get('activate', False):      # 检查配置中的 'activate' 字段是否为 True，若为 False 则跳过该选股器
                continue

            class_name = selector_config['class']
            params = selector_config.get('params', {})
            if not isinstance(params, dict):
                self.log(f"Warning: {class_name} params invalid (expected dict), got {type(params)}")
                continue

            # Get class from Selector module
            if not hasattr(Selector, class_name):
                self.log(f"Warning: {class_name} not found in Selector.py")
                continue

            selector_class = getattr(Selector, class_name)

            # 如果使用指标数据库，尝试传入 indicator_store（只在选股器支持时）
            if self.use_indicator_db and self.indicator_store:
                import inspect
                sig = inspect.signature(selector_class.__init__)
                if 'indicator_store' in sig.parameters:
                    params['indicator_store'] = self.indicator_store

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

        # ============ 安全获取策略名称 ============
        # 如果是字典，尝试获取 name 或 class
        if isinstance(self.sell_strategy_config, dict):
            strategy_name = (
                self.sell_strategy_config.get('name') or 
                self.sell_strategy_config.get('class') or 
                'Unknown'
            )
        # 如果是列表，显示策略数量
        elif isinstance(self.sell_strategy_config, list):
            strategy_name = f"Multiple Strategies ({len(self.sell_strategy_config)})"
        # 其他情况
        else:
            strategy_name = 'Unknown'
        
        self.log(f"Loaded sell strategy: {strategy_name}")
 

    def get_buy_signals(self, date: datetime, cancel_check=None):
        """
        获取买入信号。

        核心逻辑：
        - 无论是否使用指标数据库，都直接调用 selector.select()。
        - 当 use_indicator_db=True 时，self.market_data 里的 DataFrame 已经包含
          所有预计算指标列（kdj_j、bbi、ma60、dif、zxdq 等），选股器内部的
          _passes_filters_with_db() 会直接读取这些列，无需任何实时计算。
        - 当 use_indicator_db=False 时，DataFrame 只含 OHLCV，选股器走
          _passes_filters_legacy()，行为与原来完全一致。
        - 两条路径共用同一套 selector.select() 接口，代码统一、无冗余。
        """

        import time

        self.log(f"\n{'='*80}")
        self.log(f"GETTING BUY SIGNALS FOR {date.date()}")
        self.log(f"{'='*80}")

        # 获取截至当前日期的数据（含全部指标列，来自 DB 或纯 OHLCV）
        t0 = time.perf_counter()
        data_up_to_date = self._get_data_up_to_date(date)
        self.log(f"  Data slice ready: {len(data_up_to_date)} stocks in {time.perf_counter()-t0:.3f}s")

        # 执行每个选股器
        signals_by_selector: Dict[str, List[BuySignal]] = {}

        for selector_info in self.buy_selectors:
            if cancel_check and cancel_check():
                break

            alias = selector_info['alias']
            class_name = selector_info['class']
            selector = selector_info['instance']

            try:
                self.log(f"  Running {alias}...")
                t1 = time.perf_counter()

                # selector.select() 返回符合条件的股票代码列表
                picked_codes: List[str] = selector.select(date, data_up_to_date)

                elapsed = time.perf_counter() - t1
                self.log(f"    → {len(picked_codes)} picks in {elapsed:.3f}s")

                # 将代码列表转换为 BuySignal 列表（附带评分）
                signals: List[BuySignal] = []
                for code in picked_codes:
                    score, indicator_data = self._compute_signal_score(
                        code, date,
                        indicators=data_up_to_date[code].iloc[-1] if code in data_up_to_date else None
                    )
                    signal = BuySignal(
                        code=code,
                        score=score,
                        strategy_name=alias,
                        indicators=indicator_data
                    )
                    signals.append(signal)

                signals_by_selector[class_name] = signals

            except Exception as e:
                import traceback
                self.log(f"  ERROR in {alias}: {e}\n{traceback.format_exc()}")
                signals_by_selector[class_name] = []

        final_signals = self._apply_combination_logic(signals_by_selector, date)
        final_signals.sort(key=lambda s: s.score, reverse=True)

        self.log(f"  Total signals after combination: {len(final_signals)}")
        return final_signals

    def _apply_combination_logic(
        self,
        signals_by_selector: Dict[str, List[BuySignal]],
        current_date: datetime
    ) -> List[BuySignal]:
        """
        Apply selector combination logic.

        Args:
            signals_by_selector: {selector_class: [BuySignal, ...]}
            current_date: Current trading date

        Returns:
            List of BuySignals after applying combination logic
        """
        if self.combination_mode == "OR":
            # Default: Collect all signals from all selectors
            all_signals = []
            for signals in signals_by_selector.values():
                all_signals.extend(signals)

            # Remove duplicates (same stock picked by multiple selectors)
            # Keep the one with highest score
            signals_by_code = {}
            for signal in all_signals:
                if signal.code not in signals_by_code:
                    signals_by_code[signal.code] = signal
                else:
                    # Keep higher score
                    if signal.score > signals_by_code[signal.code].score:
                        signals_by_code[signal.code] = signal

            return list(signals_by_code.values())

        elif self.combination_mode == "AND":
            # Only keep stocks selected by ALL required selectors
            if not self.required_selectors:
                # If no required selectors specified, require ALL active selectors
                required = list(signals_by_selector.keys())
            else:
                required = self.required_selectors

            # Group signals by stock code
            signals_by_code: Dict[str, List[BuySignal]] = {}
            for selector_name, signals in signals_by_selector.items():
                if selector_name not in required:
                    continue
                for signal in signals:
                    if signal.code not in signals_by_code:
                        signals_by_code[signal.code] = []
                    signals_by_code[signal.code].append(signal)

            # Only keep stocks that have signals from ALL required selectors
            final_signals = []
            for code, signals in signals_by_code.items():
                selector_names = {s.strategy_name for s in signals}
                if len(selector_names) >= len(required):
                    # All required selectors picked this stock
                    # Use the signal with highest score
                    best_signal = max(signals, key=lambda s: s.score)
                    final_signals.append(best_signal)

            return final_signals

        elif self.combination_mode == "TIME_WINDOW":
            # Track signal history
            self._update_signal_history(signals_by_selector, current_date)

            # For each stock, check if it was picked by multiple selectors
            # within the time window
            final_signals = []

            # Get date range for window
            window_dates = [
                d for d in self.signal_history.keys()
                if (current_date - d).days <= self.time_window_days
            ]

            # For each current signal, check if another selector picked it
            # within the window
            for selector_name, signals in signals_by_selector.items():
                for signal in signals:
                    code = signal.code

                    # Check if this stock was picked by other selectors in window
                    picked_by_selectors = {selector_name}

                    for hist_date in window_dates:
                        for hist_selector, hist_codes in self.signal_history[hist_date].items():
                            if code in hist_codes:
                                picked_by_selectors.add(hist_selector)

                    # If picked by required number of selectors, add to final
                    if self.required_selectors:
                        required_count = len(self.required_selectors)
                    else:
                        required_count = 2  # Default: at least 2 selectors

                    if len(picked_by_selectors) >= required_count:
                        final_signals.append(signal)

            # Remove duplicates (keep highest score)
            signals_by_code = {}
            for signal in final_signals:
                if signal.code not in signals_by_code:
                    signals_by_code[signal.code] = signal
                else:
                    if signal.score > signals_by_code[signal.code].score:
                        signals_by_code[signal.code] = signal

            return list(signals_by_code.values())

        elif self.combination_mode == "SEQUENTIAL_CONFIRMATION":
            return self._apply_sequential_confirmation(
                signals_by_selector,
                current_date
            )

        else:
            raise ValueError(f"Unknown combination mode: {self.combination_mode}")

    def _update_signal_history(
        self,
        signals_by_selector: Dict[str, List[BuySignal]],
        current_date: datetime
    ):
        """Update signal history for TIME_WINDOW mode."""
        # Record today's signals
        self.signal_history[current_date] = {}
        for selector_name, signals in signals_by_selector.items():
            codes = [s.code for s in signals]
            self.signal_history[current_date][selector_name] = codes

        # Clean up old history (beyond window)
        cutoff_date = current_date - timedelta(days=self.time_window_days + 1)
        dates_to_remove = [d for d in self.signal_history.keys() if d < cutoff_date]
        for d in dates_to_remove:
            del self.signal_history[d]

    def _apply_sequential_confirmation(
        self,
        signals_by_selector: Dict[str, List[BuySignal]],
        current_date: datetime
    ) -> List[BuySignal]:
        """
        Apply sequential confirmation logic.

        Process:
        1. Check for new trigger signals from trigger_selectors
        2. Add new triggers to pending_triggers
        3. Check if pending triggers are confirmed by confirm_selectors
        4. Generate buy signals for confirmed triggers
        5. Clean up expired pending triggers

        Args:
            signals_by_selector: {selector_class: [BuySignal, ...]}
            current_date: Current trading date

        Returns:
            List of BuySignals (only for confirmed triggers)
        """
        # Step 1: Separate trigger signals and confirmation signals
        trigger_signals: Dict[str, List[BuySignal]] = {}
        confirm_signals: Dict[str, List[BuySignal]] = {}

        for selector_name, signals in signals_by_selector.items():
            if selector_name in self.trigger_selectors:
                trigger_signals[selector_name] = signals
            if selector_name in self.confirm_selectors:
                confirm_signals[selector_name] = signals

        # Step 2: Check for NEW trigger signals
        new_triggers = self._evaluate_trigger_logic(trigger_signals)

        # Add new triggers to pending (not yet confirmed)
        for signal in new_triggers:
            if signal.code not in self.pending_triggers:
                expiration_date = current_date + timedelta(days=self.time_window_days)
                self.pending_triggers[signal.code] = {
                    'trigger_date': current_date,
                    'expiration_date': expiration_date,
                    'trigger_signal': signal,
                    'triggered_by': [s.strategy_name for s in trigger_signals.values() for s in s if s.code == signal.code]
                }
                self.log(f"  TRIGGER: {signal.code} ({signal.strategy_alias}) - awaiting confirmation by {expiration_date.date()}")

        # Step 3: Check for CONFIRMATIONS
        confirmed_codes = self._evaluate_confirm_logic(confirm_signals)
        confirmed_signals = []

        for code in confirmed_codes:
            if code in self.pending_triggers:
                pending = self.pending_triggers[code]

                # Confirmation found!
                self.log(f"  CONFIRMED: {code} (trigger: {pending['trigger_date'].date()}, confirm: {current_date.date()})")

                # Determine buy signal timing
                if self.buy_timing == "trigger_day":
                    # Use original trigger signal (but only if we're still before expiration)
                    buy_signal = pending['trigger_signal']
                else:  # confirmation_day (default)
                    # Create new signal with confirmation date
                    buy_signal = BuySignal(
                        code=code,
                        date=current_date,  # Use confirmation date
                        strategy_name=pending['trigger_signal'].strategy_name,
                        strategy_alias=f"{pending['trigger_signal'].strategy_alias} (confirmed)",
                        score=pending['trigger_signal'].score,
                        signal_data=pending['trigger_signal'].signal_data
                    )

                confirmed_signals.append(buy_signal)

                # Remove from pending (confirmed)
                del self.pending_triggers[code]

        # Step 4: Clean up expired pending triggers
        expired_codes = [
            code for code, pending in self.pending_triggers.items()
            if current_date > pending['expiration_date']
        ]

        for code in expired_codes:
            pending = self.pending_triggers[code]
            self.log(f"  EXPIRED: {code} (triggered {pending['trigger_date'].date()}, no confirmation)")
            del self.pending_triggers[code]

        return confirmed_signals

    def _evaluate_trigger_logic(
        self,
        trigger_signals: Dict[str, List[BuySignal]]
    ) -> List[BuySignal]:
        """
        Evaluate trigger logic (AND/OR) on trigger_selectors.

        Returns list of BuySignals that satisfy trigger conditions.
        """
        if self.trigger_logic == "OR":
            # Any trigger selector can activate
            all_signals = []
            for signals in trigger_signals.values():
                all_signals.extend(signals)

            # Deduplicate by code (keep highest score)
            signals_by_code = {}
            for signal in all_signals:
                if signal.code not in signals_by_code:
                    signals_by_code[signal.code] = signal
                elif signal.score > signals_by_code[signal.code].score:
                    signals_by_code[signal.code] = signal

            return list(signals_by_code.values())

        elif self.trigger_logic == "AND":
            # All trigger selectors must pick the same stock
            if len(trigger_signals) < len(self.trigger_selectors):
                # Not all trigger selectors fired
                return []

            # Find stocks selected by ALL trigger selectors
            signals_by_code: Dict[str, List[BuySignal]] = {}
            for selector_name, signals in trigger_signals.items():
                for signal in signals:
                    if signal.code not in signals_by_code:
                        signals_by_code[signal.code] = []
                    signals_by_code[signal.code].append(signal)

            # Keep only stocks selected by ALL required selectors
            final_signals = []
            for code, signals in signals_by_code.items():
                selector_names = {s.strategy_name for s in signals}
                if len(selector_names) >= len(self.trigger_selectors):
                    # Use signal with highest score
                    best_signal = max(signals, key=lambda s: s.score)
                    final_signals.append(best_signal)

            return final_signals

        else:
            raise ValueError(f"Unknown trigger_logic: {self.trigger_logic}")

    def _evaluate_confirm_logic(
        self,
        confirm_signals: Dict[str, List[BuySignal]]
    ) -> List[str]:
        """
        Evaluate confirmation logic (AND/OR) on confirm_selectors.

        Returns list of stock codes that satisfy confirmation conditions.
        """
        if self.confirm_logic == "OR":
            # Any confirm selector can confirm
            confirmed_codes = set()
            for signals in confirm_signals.values():
                for signal in signals:
                    confirmed_codes.add(signal.code)
            return list(confirmed_codes)

        elif self.confirm_logic == "AND":
            # All confirm selectors must pick the same stock
            if len(confirm_signals) < len(self.confirm_selectors):
                # Not all confirm selectors fired
                return []

            # Find stocks selected by ALL confirm selectors
            signals_by_code: Dict[str, List[str]] = {}
            for selector_name, signals in confirm_signals.items():
                for signal in signals:
                    if signal.code not in signals_by_code:
                        signals_by_code[signal.code] = []
                    signals_by_code[signal.code].append(selector_name)

            # Keep only stocks confirmed by ALL required selectors
            confirmed_codes = []
            for code, selector_names in signals_by_code.items():
                if len(set(selector_names)) >= len(self.confirm_selectors):
                    confirmed_codes.append(code)

            return confirmed_codes

        else:
            raise ValueError(f"Unknown confirm_logic: {self.confirm_logic}")

    def check_sell_signals(self, date: datetime, cancel_check: Optional[Any] = None) -> List[tuple[str, str]]:
        """
        Check sell conditions for all positions.

        CRITICAL: Prevents lookahead bias by only using data up to current date.

        Args:
            date: Current date
            cancel_check: Optional function to check if backtest should be cancelled

        Returns:
            List of (code, exit_reason) tuples
        """
        sell_signals = []

        # Ensure data cache is up to date for the current date
        self._get_data_up_to_date(date)

        for code, position in list(self.portfolio.positions.items()):       # 遍历当前持仓中的每只股票
            # Check for cancellation before processing each position
            if cancel_check and cancel_check():
                break

            # Get historical data up to current date (from cache)
            df_up_to_date = self.data_cache.get(code)
            if df_up_to_date is None:
                # 缓存中没有（不应该发生，但作为后备）
                if code not in self.market_data:
                    continue
                df = self.market_data[code]
                df_up_to_date = df[df['date'] <= date].copy()

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
                    hist_data=df_up_to_date,
                    indicators=current_data if self.use_indicator_db else None
                )

                if should_sell:
                    sell_signals.append((code, reason))     # 如果满足卖出条件，将股票代码和卖出原因添加到sell_signals列表中

            except Exception as e:
                self.log(f"Error checking sell for {code}: {e}")

        return sell_signals

    def _process_buy_signals_with_fallback(
        self,
        date: datetime,
        buy_signals: List[BuySignal],
        current_market_data: Dict[str, pd.Series]
    ) -> int:
        """
        Process buy signals with fallback mechanism.

        When an order cannot be generated (insufficient cash, position limit),
        move to next signal. This ensures maximum capital utilization.

        Args:
            date: Current date
            buy_signals: List of buy signals to process
            current_market_data: Current market data for all stocks

        Returns:
            Number of orders created
        """
        signals_attempted = 0
        orders_created = 0

        for signal in buy_signals:
            # Stop if position limit reached
            if not self.portfolio.can_open_new_position():
                self.log(
                    f"  Position limit reached ({self.portfolio.max_positions}), "
                    f"stopping signal processing"
                )
                break

            # Get current price
            if signal.code not in current_market_data:
                signals_attempted += 1
                self.log(f"  SKIPPED: {signal.code} ({signal.strategy_alias}) - no market data")
                continue

            current_price = current_market_data[signal.code]['close']

            # Get historical data for position sizing (from cache)
            df_up_to_date = self.data_cache.get(signal.code)
            if df_up_to_date is None:
                # 缓存中没有（不应该发生，但作为后备）
                df = self.market_data[signal.code]
                df_up_to_date = df[df['date'] <= date]

            # Attempt to generate order
            order = self.portfolio.generate_buy_order(
                code=signal.code,
                signal_date=date,
                price=current_price,
                buy_strategy=signal.strategy_alias,
                market_data=df_up_to_date
            )

            signals_attempted += 1

            if order:
                orders_created += 1
                self.log(
                    f"  BUY SIGNAL #{orders_created}: {signal.code} "
                    f"({signal.strategy_alias}) {order.shares} shares @ ~{current_price:.2f}"
                )
            else:
                # Log why signal was skipped
                self.log(
                    f"  SKIPPED: {signal.code} ({signal.strategy_alias}) @ {current_price:.2f} - "
                    f"insufficient cash or duplicate position"
                )

        self.log(
            f"  Buy signal summary: {len(buy_signals)} total, "
            f"{signals_attempted} attempted, {orders_created} orders created"
        )

        return orders_created

    def run(self, progress_callback: Optional[Any] = None, cancel_check: Optional[Any] = None):
        """
        Run backtest.

        Main event loop over trading dates.
        """
        self.log("\n" + "="*80)
        self.log("BACKTEST START")
        self.log("="*80)

        total_days = len(self.trading_dates)
        for idx, date in enumerate(self.trading_dates, start=1):
            if cancel_check and cancel_check():
                self.log("BACKTEST CANCELLED")
                break
            self.log(f"\n--- {date.date()} ---")

            # Log cash status at start of day
            self.log(
                f"  Cash: {self.portfolio.cash:,.2f}, "
                f"Available: {self.portfolio.get_available_cash():,.2f}, "
                f"Positions: {len(self.portfolio.positions)}"
            )

            # 1. Process T+1 settlement
            self.portfolio.process_settlement(date)     # 处理T+1结算，更新持仓和现金等信息

            # Log settlement impact
            proceeds = self.portfolio.settlement_tracker.pending_proceeds.get(date, 0)
            if proceeds > 0:
                self.log(f"  Settlement: +{proceeds:,.2f} proceeds received")

            # 2. Execute pending orders (from T-1)
            market_data_today = {
                code: df for code, df in self.market_data.items()       # 获取当天的市场数据
            }
            executed_orders = self.portfolio.execute_pending_orders(date, market_data_today)    # 执行待处理订单

            # Log individual order results
            for order in executed_orders:
                if order.status.value == "EXECUTED":
                    self.log(f"  EXECUTED {order.action.value}: {order.code} x {order.shares} @ {order.execution_price:.2f}")
                else:
                    self.log(f"  FAILED {order.action.value}: {order.code} - {order.reason}")

            # Log execution summary
            from .data_structures import OrderAction, OrderStatus
            buy_executed = sum(1 for o in executed_orders if o.action == OrderAction.BUY and o.status == OrderStatus.EXECUTED)
            sell_executed = sum(1 for o in executed_orders if o.action == OrderAction.SELL and o.status == OrderStatus.EXECUTED)
            buy_failed = sum(1 for o in executed_orders if o.action == OrderAction.BUY and o.status == OrderStatus.FAILED)

            if buy_executed > 0 or sell_executed > 0 or buy_failed > 0:
                self.log(
                    f"  Execution summary: {buy_executed} buys, {sell_executed} sells, "
                    f"{buy_failed} buy failures | Cash: {self.portfolio.cash:,.2f}"
                )

            # 3. Update position metrics
            current_market_data = {}
            for code in self.market_data:
                df = self.market_data[code]
                df_today = df[df['date'] == date]
                if len(df_today) > 0:
                    current_market_data[code] = df_today.iloc[-1]

            self.portfolio.update_positions(date, current_market_data)      # 更新持仓的最高价格和持有天数

            # 4. Check sell signals
            sell_signals = self.check_sell_signals(date, cancel_check=cancel_check)    # 检查卖出信号，传递 cancel_check
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
            buy_signals = self.get_buy_signals(date, cancel_check=cancel_check)        # 获取买入信号，传递 cancel_check

            # 6. Generate buy orders for T+1 with fallback mechanism
            self._process_buy_signals_with_fallback(date, buy_signals, current_market_data)

            # 7. Update equity curve
            self.portfolio.update_equity_curve(date, current_market_data)

            # Log portfolio summary
            self.log(f"  Portfolio: {len(self.portfolio.positions)} positions, Cash: {self.portfolio.cash:,.0f}, Total: {self.portfolio.total_value:,.0f}")
            if progress_callback:
                progress_callback(idx, total_days, date)

        # Force liquidate all positions at the end of backtest
        if len(self.portfolio.positions) > 0:
            self.log("\n" + "="*80)
            self.log("FORCE LIQUIDATION - Closing all positions")
            self.log("="*80)

            # Get the last trading date
            last_date = self.trading_dates[-1]

            # Generate sell orders for all positions
            positions_to_close = list(self.portfolio.positions.keys())
            for code in positions_to_close:
                self.portfolio.generate_sell_order(code, last_date, "End of backtest - forced liquidation")
                self.log(f"  Generated sell order for {code}")

            # Create a virtual next trading day to execute these orders
            # Use last_date + 1 day for execution
            virtual_execution_date = last_date + timedelta(days=1)

            self.log(f"\n--- Virtual Execution Date: {virtual_execution_date.date()} ---")

            # Process settlement
            self.portfolio.process_settlement(virtual_execution_date)

            # Execute pending orders
            # Prepare market data: use last trading date's prices for execution
            # (virtual date doesn't exist in data, so we use last available data)
            market_data_virtual = {}
            for code, df in self.market_data.items():
                df_last = df[df['date'] == last_date]
                if len(df_last) > 0:
                    # Create a virtual row with last_date's prices but virtual_execution_date
                    df_virtual = df_last.copy()
                    df_virtual['date'] = virtual_execution_date
                    # Append to original df for execute_pending_orders to find
                    market_data_virtual[code] = pd.concat([df, df_virtual], ignore_index=True)
                else:
                    market_data_virtual[code] = df

            executed_orders = self.portfolio.execute_pending_orders(virtual_execution_date, market_data_virtual)

            # Log execution results
            from .data_structures import OrderAction, OrderStatus
            for order in executed_orders:
                if order.status.value == "EXECUTED":
                    self.log(f"  EXECUTED {order.action.value}: {order.code} x {order.shares} @ {order.execution_price:.2f}")
                else:
                    self.log(f"  FAILED {order.action.value}: {order.code} - {order.reason}")

            # Update equity curve one final time
            # Use last available market data for position valuation
            final_market_data = {}
            for code in self.market_data:
                df = self.market_data[code]
                df_last = df[df['date'] == last_date]
                if len(df_last) > 0:
                    final_market_data[code] = df_last.iloc[-1]

            self.portfolio.update_equity_curve(virtual_execution_date, final_market_data)

            self.log(f"  Final portfolio: {len(self.portfolio.positions)} positions, Cash: {self.portfolio.cash:,.0f}, Total: {self.portfolio.total_value:,.0f}")

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
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass

    def _compute_signal_score(
        self, 
        code: str, 
        date: datetime,
        indicators: Optional[pd.Series] = None  # ← 新增参数
    ) -> tuple[float, Dict[str, Any]]:
        """
        计算买入信号评分（优化版）
        
        优化点：
        1. 优先使用批量查询传入的indicators
        2. 回退到数据库单独查询
        3. 最后才实时计算
        """
        
            # 优先使用传入的指标
        if indicators is not None:
        if indicators is not None and 'kdj_j' in indicators:
            # Only use provided indicators if they contain required fields (e.g. from DB)
            return self._compute_score_from_indicators(code, indicators)
        
        # 回退：从数据库查询
        if self.use_indicator_db and self.indicator_store:
            date_str = date.strftime('%Y-%m-%d')
            try:
                df = self.indicator_store.get_indicators(code, date_str, date_str)
                if not df.empty:
                    indicators = df.iloc[0]
                    return self._compute_score_from_indicators(code, indicators)
            except Exception:
                pass
        
        # 最后回退：实时计算
        return self._compute_score_legacy(code)


    def _compute_score_from_indicators(
            self,
            code: str,
            indicators: pd.Series
        ) -> tuple[float, Dict[str, Any]]:
            """从预计算指标计算评分"""
            
            try:
                # 提取指标
                kdj_j = float(indicators.get('kdj_j', np.nan))
                volume = float(indicators.get('volume', 0))
                close = float(indicators.get('close', 0))
                
                # volume_ratio
                if 'volume_ratio' in indicators and not pd.isna(indicators['volume_ratio']):
                    volume_ratio = float(indicators['volume_ratio'])
                else:
                    ma20_volume = float(indicators.get('ma20_volume', volume))
                    volume_ratio = volume / ma20_volume if ma20_volume > 0 else 0.0
                
                # daily_return
                if 'daily_return' in indicators and not pd.isna(indicators['daily_return']):
                    daily_return = float(indicators['daily_return'])
                else:
                    daily_return = 0.0
                
                # bbi_slope
                if 'bbi_slope_5d' in indicators and not pd.isna(indicators['bbi_slope_5d']):
                    bbi_slope = float(indicators['bbi_slope_5d'])
                else:
                    bbi_slope = 0.0
                
            except (KeyError, ValueError, TypeError) as e:
                return 0.0, {'code': code, 'reason': f'invalid_data: {e}'}
            
            # 验证
            if np.isnan(kdj_j) or close == 0:
                return 0.0, {'code': code, 'reason': 'invalid_indicators'}
            
            # 计算分数
            kdj_score = max(0.0, min(100.0, 100.0 - kdj_j))
            volume_score = max(0.0, min(100.0, (volume_ratio - 1.0) / 2.0 * 100.0))
            
            if daily_return <= 0:
                momentum_score = 0.0
            elif daily_return <= 0.02:
                momentum_score = (daily_return / 0.02) * 100.0
            elif daily_return <= 0.05:
                momentum_score = 100.0 - ((daily_return - 0.02) / 0.03) * 50.0
            else:
                momentum_score = 50.0
            momentum_score = max(0.0, min(100.0, momentum_score))
            
            bbi_score = max(0.0, min(100.0, (bbi_slope / 0.005) * 100.0)) if bbi_slope > 0 else 0.0
            
            composite = (
                0.4 * kdj_score +
                0.3 * volume_score +
                0.2 * momentum_score +
                0.1 * bbi_score
            )
            
            indicator_data = {
                'kdj_j': kdj_j,
                'volume_ratio': volume_ratio,
                'momentum_pct': daily_return,
                'bbi_slope': bbi_slope,
                'score_breakdown': {
                    'kdj': kdj_score,
                    'volume': volume_score,
                    'momentum': momentum_score,
                    'bbi': bbi_score
                }
            }
            
            return float(composite), indicator_data

    def _compute_score_legacy(self, code: str, df: Optional[pd.DataFrame]) -> tuple[float, Dict[str, Any]]:
        """Compute composite score and indicator data for a buy signal."""
        if df is None or df.empty:
            return 0.0, {'code': code, 'reason': 'no_data'}

        self._ensure_project_root_on_path()
        from backtest.Selector import compute_kdj, compute_bbi  # noqa: WPS433

        df = df.copy()
        df = df.sort_values('date')

        # KDJ score
        kdj_df = compute_kdj(df)
        current_j = float(kdj_df['J'].iloc[-1]) if 'J' in kdj_df.columns else float('nan')
        kdj_score = max(0.0, min(100.0, 100.0 - current_j)) if not np.isnan(current_j) else 0.0

        # Volume score (20-day avg)
        volume = float(df['volume'].iloc[-1]) if 'volume' in df.columns else 0.0
        avg_volume = float(df['volume'].tail(20).mean()) if 'volume' in df.columns else 0.0
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0.0
        volume_score = max(0.0, min(100.0, (volume_ratio - 1.0) / 2.0 * 100.0))

        # Momentum score (daily return)
        if len(df) >= 2:
            prev_close = float(df['close'].iloc[-2])
            current_close = float(df['close'].iloc[-1])
            momentum_pct = (current_close / prev_close - 1.0) if prev_close > 0 else 0.0
        else:
            momentum_pct = 0.0

        if momentum_pct <= 0:
            momentum_score = 0.0
        elif momentum_pct <= 0.02:
            momentum_score = (momentum_pct / 0.02) * 100.0
        elif momentum_pct <= 0.05:
            momentum_score = 100.0 - ((momentum_pct - 0.02) / 0.03) * 50.0
        else:
            momentum_score = 50.0
        momentum_score = max(0.0, min(100.0, momentum_score))

        # BBI slope score
        bbi = compute_bbi(df)
        bbi = bbi.dropna()
        bbi_slope = 0.0
        if len(bbi) >= 2:
            window = bbi.tail(5)
            if len(window) >= 2 and window.iloc[0] != 0:
                bbi_slope = (window.iloc[-1] - window.iloc[0]) / window.iloc[0] / (len(window) - 1)
        bbi_score = max(0.0, min(100.0, (bbi_slope / 0.005) * 100.0)) if bbi_slope > 0 else 0.0

        # Composite score
        composite = (
            0.4 * kdj_score +
            0.3 * volume_score +
            0.2 * momentum_score +
            0.1 * bbi_score
        )

        indicator_data = {
            'kdj_j': current_j,
            'volume_ratio': volume_ratio,
            'momentum_pct': momentum_pct,
            'bbi_slope': bbi_slope,
            'score_breakdown': {
                'kdj': kdj_score,
                'volume': volume_score,
                'momentum': momentum_score,
                'bbi': bbi_score
            }
        }

        return float(composite), indicator_data 