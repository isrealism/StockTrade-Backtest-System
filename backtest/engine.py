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


def _selector_chunk_worker(args):
    """
    模块级 worker 函数，供 ProcessPoolExecutor 跨进程调用。
    必须定义在模块顶层才能被 pickle 序列化。

    args: (selector_class_name, selector_params, indicator_db_path, date, chunk_codes, data_chunk)
    """
    selector_class_name, selector_params, indicator_db_path, date, chunk_codes, data_chunk = args

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import backtest.Selector as Selector_module
    selector_cls = getattr(Selector_module, selector_class_name)

    # 重建 IndicatorStore
    indicator_store = None
    if indicator_db_path:
        try:
            from backtest.indicator_store import IndicatorStore
            indicator_store = IndicatorStore(indicator_db_path)
        except Exception:
            pass

    # 重建 selector
    try:
        local_selector = selector_cls(**selector_params)
    except TypeError:
        local_selector = selector_cls()

    if indicator_store is not None and hasattr(local_selector, 'indicator_store'):
        local_selector.indicator_store = indicator_store

    return local_selector.select(date, data_chunk)


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
        use_indicator_db: bool = True,
        indicator_db_path: str = "./data/indicators.duckdb",
        # ── Score 百分位过滤 ──────────────────────────────────────
        score_filter_enabled: bool = False,
        score_percentile_threshold: float = 60.0,
        score_min_history: int = 20,
        score_warmup_lookback_days: int = 20,   # 预热最多回看多少个交易日，默认20
        # ── 换仓 (Rotation) ───────────────────────────────────────
        rotation_enabled: bool = False,
        rotation_min_stop_threshold: float = 0.05,
        rotation_max_per_day: int = 2,
        rotation_score_ratio: float = 1.2,
        rotation_min_score_improvement: float = 10.0,
        rotation_no_score_policy: str = "skip",
        # ── 并行选股 ──────────────────────────────────────────────
        parallel_workers: int = 0,   # 0 = 自动检测 CPU 核数
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

        # ── Score 百分位过滤 ──────────────────────────────────────
        if not (0.0 < score_percentile_threshold < 100.0):
            raise ValueError(f"score_percentile_threshold must be in (0,100), got {score_percentile_threshold}")
        if score_min_history < 1:
            raise ValueError(f"score_min_history must be >= 1, got {score_min_history}")
        self.score_filter_enabled: bool = score_filter_enabled
        self.score_percentile_threshold: float = score_percentile_threshold
        self.score_min_history: int = score_min_history
        self.score_warmup_lookback_days: int = score_warmup_lookback_days
        self.score_history: List[float] = []
        self.score_warmup_complete: bool = False

        # ── 换仓 (Rotation) ───────────────────────────────────────
        self.rotation_manager = None
        if rotation_enabled:
            from .rotation_manager import RotationManager
            self.rotation_manager = RotationManager(
                min_stop_threshold=rotation_min_stop_threshold,
                max_rotations_per_day=rotation_max_per_day,
                score_ratio_threshold=rotation_score_ratio,
                min_score_improvement=rotation_min_score_improvement,
                no_score_position_policy=rotation_no_score_policy,
                score_history_ref=self.score_history,
            )
            self.log(
                f"Rotation enabled: min_loss={rotation_min_stop_threshold*100:.1f}%, "
                f"max/day={rotation_max_per_day}, "
                f"score_ratio>={rotation_score_ratio}x, "
                f"score_improvement>={rotation_min_score_improvement}pts"
            )

        # ── 并行选股 ──────────────────────────────────────────────
        import os
        self.parallel_workers: int = parallel_workers if parallel_workers > 0 else os.cpu_count() or 1
        self.log(f"Parallel workers: {self.parallel_workers}")

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
 

    def _parallel_select(
        self,
        selector,
        date: datetime,
        data_up_to_date: Dict[str, pd.DataFrame],
    ) -> List[str]:
        """
        并行版 selector.select()：把股票池按 worker 数量分片，
        用 ProcessPoolExecutor 并行跑 _passes_filters，最后合并结果。

        worker 函数定义在模块顶层（_selector_chunk_worker），可被 pickle 序列化。
        子进程重建 selector 时同步重建 IndicatorStore，确保走 DB 路径。
        """
        from concurrent.futures import ProcessPoolExecutor, as_completed

        codes = list(data_up_to_date.keys())
        n = self.parallel_workers

        if n <= 1 or len(codes) <= n:
            return selector.select(date, data_up_to_date)

        chunk_size = max(1, len(codes) // n)
        chunks = [codes[i:i + chunk_size] for i in range(0, len(codes), chunk_size)]

        selector_class_name = type(selector).__name__
        selector_params = {
            k: v for k, v in vars(selector).items()
            if not k.startswith('_') and k != 'indicator_store'
        }
        indicator_db_path = self.indicator_db_path if self.use_indicator_db else None

        # 每个 chunk 的入参打包成 tuple 传给模块级 worker
        tasks = [
            (
                selector_class_name,
                selector_params,
                indicator_db_path,
                date,
                chunk,
                {c: data_up_to_date[c] for c in chunk if c in data_up_to_date},
            )
            for chunk in chunks
        ]

        picks: List[str] = []
        with ProcessPoolExecutor(max_workers=n) as executor:
            futures = {executor.submit(_selector_chunk_worker, task): task for task in tasks}
            for future in as_completed(futures):
                try:
                    picks.extend(future.result())
                except Exception as e:
                    self.log(f"  [parallel_select] chunk error: {e}")

        return picks

    def get_buy_signals(self, date: datetime, cancel_check=None) -> List[BuySignal]:
        """
        获取当日原始买入信号（未经 score 百分位过滤）。

        selector.select() 返回代码列表 → 逐支提取四个原始指标 → 实例化 BuySignal
        → BuySignal.__post_init__ 自动计算 score 及四个子分。
        score 计算逻辑完全封装在 BuySignal 内，engine 不再承担评分职责。
        """
        import time

        self.log(f"\n{'='*80}")
        self.log(f"GETTING BUY SIGNALS FOR {date.date()}")
        self.log(f"{'='*80}")

        t0 = time.perf_counter()
        data_up_to_date = self._get_data_up_to_date(date)
        self.log(f"  Data slice ready: {len(data_up_to_date)} stocks in {time.perf_counter()-t0:.3f}s")

        signals_by_selector: Dict[str, List[BuySignal]] = {}

        for selector_info in self.buy_selectors:
            if cancel_check and cancel_check():
                break

            alias      = selector_info['alias']
            class_name = selector_info['class']
            selector   = selector_info['instance']

            try:
                self.log(f"  Running {alias}...")
                t1 = time.perf_counter()

                picked_codes: List[str] = self._parallel_select(selector, date, data_up_to_date)
                self.log(f"    → {len(picked_codes)} picks in {time.perf_counter()-t1:.3f}s ({self.parallel_workers} workers)")

                signals: List[BuySignal] = []
                for code in picked_codes:
                    if code not in data_up_to_date:
                        continue
                    df_code  = data_up_to_date[code]
                    last_row = df_code.iloc[-1]
                    # 始终传入 df_code 作为 df_full，让 DB 路径在列缺失时能 fallback 实时计算
                    ind = self._extract_indicators(code, last_row, df_code)
                    signal = BuySignal(
                        code=code,
                        date=date,
                        strategy_name=class_name,
                        strategy_alias=alias,
                        kdj_j=ind['kdj_j'],
                        volume_ratio=ind['volume_ratio'],
                        daily_return=ind['daily_return'],
                        bbi_slope=ind['bbi_slope'],
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
                    # Create new signal with confirmation date; inherit raw indicators from
                    # trigger signal so score is identical and stays encapsulated in BuySignal
                    trig = pending['trigger_signal']
                    buy_signal = BuySignal(
                        code=code,
                        date=current_date,
                        strategy_name=trig.strategy_name,
                        strategy_alias=f"{trig.strategy_alias} (confirmed)",
                        kdj_j=trig.kdj_j,
                        volume_ratio=trig.volume_ratio,
                        daily_return=trig.daily_return,
                        bbi_slope=trig.bbi_slope,
                        signal_data=trig.signal_data,
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
                market_data=df_up_to_date,
                signal_score=signal.score,
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

    # ══════════════════════════════════════════════════════════════════
    #  Score 百分位过滤相关方法
    # ══════════════════════════════════════════════════════════════════

    def warmup_score_history(self, force_legacy: bool = True) -> None:
        """
        Bootstrap 预热：用 lookback_days 历史数据预填充 score_history。

        在 setup_selectors() 和 load_sell_strategy() 之后、run() 之前调用。
        预热期完整复用选股器管线（含 combination_logic），确保历史分布与
        主循环信号口径一致。预热期内压制普通日志，但保留错误收集，完成后统一输出摘要。

        Parameters
        ----------
        force_legacy : bool, default True
            True 时预热期强制走实时计算（legacy）路径，忽略 indicator_db。
            适用于 DB 数据尚未完整的情况。False 时沿用 engine 当前的 use_indicator_db 设置。
        """
        if not self.score_filter_enabled and self.rotation_manager is None:
            return

        if not self.buy_selectors:
            self.log("warmup_score_history: no selectors loaded, skipping")
            return

        # 从 market_data 中提取严格早于 start_date 的交易日
        # 注意：trading_dates 只含 [start_date, end_date] 区间内的日期，
        # lookback 期的日期仅存在于 market_data 的 DataFrame 里，需要直接提取。
        warmup_date_set: set = set()
        for df in self.market_data.values():
            pre_dates = df[df['date'] < self.start_date]['date']
            warmup_date_set.update(pre_dates.tolist())
        all_warmup_dates = sorted(warmup_date_set)

        if not all_warmup_dates:
            self.log("warmup_score_history: no warmup dates available (check lookback_days)")
            return

        # 只取最近的 score_warmup_lookback_days 个交易日，避免全量预热太慢
        warmup_dates = all_warmup_dates[-self.score_warmup_lookback_days:]
        skipped = len(all_warmup_dates) - len(warmup_dates)
        if skipped > 0:
            self.log(
                f"  warmup_score_history: using last {len(warmup_dates)} of "
                f"{len(all_warmup_dates)} available pre-start dates "
                f"(set score_warmup_lookback_days to adjust)"
            )

        mode_str = "legacy (real-time)" if force_legacy else ("DB" if self.use_indicator_db else "legacy (real-time)")
        self.log(f"\nWarming up score history over {len(warmup_dates)} pre-start dates [{mode_str} mode]...")

        # force_legacy：临时把每个 selector 的 indicator_store 置 None，
        # 强制走 _passes_filters_legacy()；engine 侧也临时关闭 DB 模式，
        # 使 _extract_indicators 走实时计算路径。
        saved_engine_db = self.use_indicator_db
        saved_selector_stores = {}
        if force_legacy and self.use_indicator_db:
            self.use_indicator_db = False
            for info in self.buy_selectors:
                sel = info['instance']
                if hasattr(sel, 'indicator_store'):
                    saved_selector_stores[id(sel)] = sel.indicator_store
                    sel.indicator_store = None

        collected  = 0
        date_errors: List[str] = []

        try:
            for date in warmup_dates:
                try:
                    signals, day_errors = self._get_raw_signals_for_date(date, silent=True)
                    date_errors.extend(day_errors)
                    for s in signals:
                        self.score_history.append(s.score)
                        collected += 1
                except Exception as e:
                    date_errors.append(f"{date.date()}: {e}")
        finally:
            # 无论成功与否，都恢复原始设置
            if force_legacy and saved_engine_db:
                self.use_indicator_db = saved_engine_db
                for info in self.buy_selectors:
                    sel = info['instance']
                    if id(sel) in saved_selector_stores:
                        sel.indicator_store = saved_selector_stores[id(sel)]

        self.score_warmup_complete = True

        # 有报错时统一输出（取前10条，避免刷屏）
        if date_errors:
            self.log(f"  [Warmup] {len(date_errors)} error(s) during warmup "
                     f"(showing first 10):")
            for err in date_errors[:10]:
                self.log(f"    ✗ {err}")

        if self.score_history:
            arr = np.array(self.score_history)
            self.log(
                f"  Warmup complete: {collected} scores collected | "
                f"p25={np.percentile(arr, 25):.1f} "
                f"p50={np.percentile(arr, 50):.1f} "
                f"p{self.score_percentile_threshold:.0f}={np.percentile(arr, self.score_percentile_threshold):.1f} "
                f"p75={np.percentile(arr, 75):.1f} "
                f"p90={np.percentile(arr, 90):.1f}"
            )
        else:
            self.log(
                "  Warmup complete: 0 scores collected. "
                "Possible causes: selectors erroring out (see errors above), "
                "or no stocks passed filters in warmup period."
            )

    def _get_raw_signals_for_date(
        self, date: datetime, silent: bool = False
    ) -> tuple:
        """
        获取指定日期的原始信号（不做 score 过滤，不追加 score_history）。

        供 warmup_score_history 和主循环复用同一管线。

        Returns
        -------
        (signals, errors) : (List[BuySignal], List[str])
            signals : 当日信号列表
            errors  : 选股器报错列表（silent=True 时收集而非打印）
        """
        errors: List[str] = []

        if silent:
            orig_log = self.log
            self.log = lambda _: None

        try:
            data_up_to_date = self._get_data_up_to_date(date)
            signals_by_selector: Dict[str, List[BuySignal]] = {}

            for selector_info in self.buy_selectors:
                alias      = selector_info['alias']
                class_name = selector_info['class']
                selector   = selector_info['instance']
                try:
                    picked_codes: List[str] = self._parallel_select(selector, date, data_up_to_date)
                    signals: List[BuySignal] = []
                    for code in picked_codes:
                        if code not in data_up_to_date:
                            continue
                        df_code  = data_up_to_date[code]
                        last_row = df_code.iloc[-1]
                        ind = self._extract_indicators(code, last_row, df_code)
                        signals.append(BuySignal(
                            code=code,
                            date=date,
                            strategy_name=class_name,
                            strategy_alias=alias,
                            kdj_j=ind['kdj_j'],
                            volume_ratio=ind['volume_ratio'],
                            daily_return=ind['daily_return'],
                            bbi_slope=ind['bbi_slope'],
                        ))
                    signals_by_selector[class_name] = signals
                except Exception as e:
                    import traceback
                    err_msg = f"{date.date()} [{alias}]: {e} | {traceback.format_exc().splitlines()[-1]}"
                    if silent:
                        errors.append(err_msg)
                    else:
                        self.log(f"  ERROR in {alias}: {e}\n{traceback.format_exc()}")
                    signals_by_selector[class_name] = []

            final = self._apply_combination_logic(signals_by_selector, date)
            final.sort(key=lambda s: s.score, reverse=True)
            return final, errors

        finally:
            if silent:
                self.log = orig_log  # type: ignore[assignment]

    def filter_signals_by_score(
        self, raw_signals: List[BuySignal], date: datetime
    ) -> List[BuySignal]:
        """
        将当日信号 score 追加进 score_history，然后按百分位阈值过滤。

        注意：先追加再过滤，保证今日 score 不参与今日阈值计算（防未来函数）。
        历史样本不足 score_min_history 时退化为不过滤（输出警告）。
        """
        if not self.score_filter_enabled:
            return raw_signals

        # 先追加（今日 score 进入历史，但不用于计算今日阈值）
        for s in raw_signals:
            self.score_history.append(s.score)

        if len(self.score_history) < self.score_min_history:
            self.log(
                f"  [ScoreFilter] History too short ({len(self.score_history)} < {self.score_min_history}), "
                f"skipping filter"
            )
            return raw_signals

        threshold = float(np.percentile(self.score_history, self.score_percentile_threshold))
        filtered  = [s for s in raw_signals if s.score >= threshold]

        self.log(
            f"  [ScoreFilter] threshold={threshold:.1f} (p{self.score_percentile_threshold:.0f}) | "
            f"{len(raw_signals)} → {len(filtered)} signals"
        )
        return filtered

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
            sell_signals = self.check_sell_signals(date, cancel_check=cancel_check)
            sell_triggered_codes: set = set()
            for code, reason in sell_signals:
                if code in current_market_data:
                    current_price = current_market_data[code]['close']
                    position = self.portfolio.get_position(code)
                    if position:
                        unrealized_pnl_pct = position.unrealized_pnl_pct(current_price) * 100
                        self.log(f"  SELL SIGNAL: {code} ({reason}) P&L: {unrealized_pnl_pct:+.2f}%")
                self.portfolio.generate_sell_order(code, date, reason)
                sell_triggered_codes.add(code)

            # 5. Get buy signals（原始）→ score 过滤
            raw_signals, _  = self._get_raw_signals_for_date(date)
            buy_signals  = self.filter_signals_by_score(raw_signals, date)

            # 5.5. Rotation（换仓）
            if self.rotation_manager is not None and buy_signals:
                current_prices = {
                    code: float(current_market_data[code]['close'])
                    for code in current_market_data
                }
                rotation_pairs = self.rotation_manager.find_rotation_pairs(
                    positions=self.portfolio.positions,
                    good_signals=buy_signals,
                    current_prices=current_prices,
                    date=date,
                    sell_triggered_codes=sell_triggered_codes,
                )
                if rotation_pairs:
                    self.log(f"  Rotation: {len(rotation_pairs)} pair(s) found")
                    r_sells, r_buys = self.rotation_manager.execute_rotations(
                        pairs=rotation_pairs,
                        portfolio=self.portfolio,
                        date=date,
                        current_prices=current_prices,
                        market_data_cache=self.data_cache,
                        log_fn=self.log,
                    )
                    # 从信号池中移除已被换仓消耗的代码，避免重复建仓
                    rotation_entry_codes = {o.code for o in r_buys}
                    buy_signals = [s for s in buy_signals if s.code not in rotation_entry_codes]
                    for pair in rotation_pairs:
                        sell_triggered_codes.add(pair.exit_position.code)

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

        if self.rotation_manager is not None:
            results['rotation_summary'] = self.rotation_manager.get_rotation_summary()

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

    def _extract_indicators(
        self,
        code: str,
        last_row: pd.Series,
        df_full: Optional[pd.DataFrame] = None,
    ) -> Dict[str, float]:
        """
        从行数据或完整 DataFrame 中提取 BuySignal 所需的四个原始指标。

        优先级：
        1. last_row 已含预计算指标列（DB 模式）→ 直接读取
        2. last_row 无指标但传入 df_full（legacy 模式）→ 实时计算
        3. 两者均不满足 → 返回全零（score 自然为 0）

        Returns
        -------
        dict with keys: kdj_j, volume_ratio, daily_return, bbi_slope
        """
        # ── 路径1：DB 模式，last_row 含指标列 ─────────────────────
        if last_row is not None and 'kdj_j' in last_row.index:
            kdj_j = float(last_row.get('kdj_j', float('nan')))

            # volume_ratio：优先取预计算列，否则用 ma20_volume 估算，再否则从 df_full 实时算
            volume = float(last_row.get('volume', 0))
            if 'volume_ratio' in last_row.index and not pd.isna(last_row['volume_ratio']):
                volume_ratio = float(last_row['volume_ratio'])
            elif 'ma20_volume' in last_row.index and not pd.isna(last_row['ma20_volume']):
                ma20_vol = float(last_row['ma20_volume'])
                volume_ratio = volume / ma20_vol if ma20_vol > 0 else 0.0
            elif df_full is not None and len(df_full) >= 2 and 'volume' in df_full.columns:
                avg_vol = float(df_full['volume'].tail(20).mean())
                volume_ratio = volume / avg_vol if avg_vol > 0 else 0.0
            else:
                volume_ratio = 0.0

            # daily_return：优先取预计算列，否则从 df_full 或 last_row 前一行实时算
            if 'daily_return' in last_row.index and not pd.isna(last_row['daily_return']):
                daily_return = float(last_row['daily_return'])
            elif df_full is not None and len(df_full) >= 2 and 'close' in df_full.columns:
                df_sorted = df_full.sort_values('date')
                prev  = float(df_sorted['close'].iloc[-2])
                curr  = float(df_sorted['close'].iloc[-1])
                daily_return = (curr / prev - 1.0) if prev > 0 else 0.0
            elif 'prev_close' in last_row.index and not pd.isna(last_row['prev_close']):
                prev_close = float(last_row['prev_close'])
                close      = float(last_row.get('close', 0))
                daily_return = (close / prev_close - 1.0) if prev_close > 0 else 0.0
            else:
                daily_return = 0.0

            # bbi_slope：优先取预计算列，否则从 df_full 实时算
            if 'bbi_slope_5d' in last_row.index and not pd.isna(last_row['bbi_slope_5d']):
                bbi_slope = float(last_row['bbi_slope_5d'])
            elif df_full is not None and len(df_full) >= 5:
                try:
                    self._ensure_project_root_on_path()
                    from backtest.Selector import compute_bbi  # noqa: WPS433
                    bbi = compute_bbi(df_full.sort_values('date')).dropna()
                    bbi_slope = 0.0
                    if len(bbi) >= 2:
                        win = bbi.tail(5)
                        if len(win) >= 2 and win.iloc[0] != 0:
                            bbi_slope = (win.iloc[-1] - win.iloc[0]) / win.iloc[0] / (len(win) - 1)
                except Exception:
                    bbi_slope = 0.0
            else:
                bbi_slope = 0.0

            return dict(kdj_j=kdj_j, volume_ratio=volume_ratio,
                        daily_return=daily_return, bbi_slope=bbi_slope)

        # ── 路径2：Legacy 模式，实时计算 ──────────────────────────
        if df_full is None or df_full.empty:
            return dict(kdj_j=float('nan'), volume_ratio=0.0,
                        daily_return=0.0, bbi_slope=0.0)

        self._ensure_project_root_on_path()
        from backtest.Selector import compute_kdj, compute_bbi  # noqa: WPS433

        df = df_full.sort_values('date').copy()

        # KDJ J 值
        try:
            kdj_df = compute_kdj(df)
            kdj_j  = float(kdj_df['J'].iloc[-1]) if 'J' in kdj_df.columns else float('nan')
        except Exception:
            kdj_j  = float('nan')

        # 量比
        volume     = float(df['volume'].iloc[-1]) if 'volume' in df.columns else 0.0
        avg_vol    = float(df['volume'].tail(20).mean()) if 'volume' in df.columns else 0.0
        volume_ratio = volume / avg_vol if avg_vol > 0 else 0.0

        # 单日涨幅
        if len(df) >= 2 and 'close' in df.columns:
            prev  = float(df['close'].iloc[-2])
            curr  = float(df['close'].iloc[-1])
            daily_return = (curr / prev - 1.0) if prev > 0 else 0.0
        else:
            daily_return = 0.0

        # BBI 5日斜率
        try:
            bbi    = compute_bbi(df).dropna()
            bbi_slope = 0.0
            if len(bbi) >= 2:
                win = bbi.tail(5)
                if len(win) >= 2 and win.iloc[0] != 0:
                    bbi_slope = (win.iloc[-1] - win.iloc[0]) / win.iloc[0] / (len(win) - 1)
        except Exception:
            bbi_slope = 0.0

        return dict(kdj_j=kdj_j, volume_ratio=volume_ratio,
                    daily_return=daily_return, bbi_slope=bbi_slope)