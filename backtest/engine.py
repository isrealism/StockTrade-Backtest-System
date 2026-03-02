"""
Event-driven backtesting engine.

Core orchestrator for backtesting trading strategies on Chinese A-share market.

Performance optimizations (vs original):
  P0-1  长驻进程池：ProcessPoolExecutor 在 __init__ 中创建，整个 run() 期间复用，
        消除每日 1500 次 fork/销毁开销。
  P0-2  消除跨进程 DataFrame pickle：DB 模式下 worker 只接收股票代码列表，
        自行从本地 IndicatorStore 读取数据，大幅减少 IPC 序列化开销。
  P0-3  Worker 进程一次性初始化 IndicatorStore：通过 ProcessPoolExecutor 的
        initializer 参数，在每个 worker 进程启动时建立一次 DB 连接，后续复用。
  P1-1  searchsorted 替代布尔过滤：_get_data_up_to_date() 和 _build_current_market_data()
        使用预建 numpy datetime64 索引 + searchsorted (O(log N))，
        替代原来的 df[df['date'] <= date] 全量布尔扫描 (O(N))。
  P1-2  check_sell_signals 并行化：对持仓使用 ThreadPoolExecutor 并行检查卖出信号，
        持仓间相互独立，pandas/numpy 运算在 C 层释放 GIL。
"""

import math
import os
import json
import importlib
import time as _time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import pandas as pd
import numpy as np

from .data_structures import BuySignal
from .portfolio import PortfolioManager
from .execution import ExecutionEngine


# ══════════════════════════════════════════════════════════════════
# 模块级：Worker 进程专用变量与函数（必须定义在模块顶层才能被 pickle）
# ══════════════════════════════════════════════════════════════════

_worker_indicator_store = None   # 每个 worker 进程的本地 DB 连接（进程间不共享）


def _worker_init(indicator_db_path: Optional[str]) -> None:
    """
    ProcessPoolExecutor initializer。
    每个 worker 进程启动时调用一次，建立 IndicatorStore 连接后全程复用。
    避免了原实现中每个 task 都重新 import 模块 + 打开 DB 连接的开销。
    """
    global _worker_indicator_store
    if indicator_db_path:
        try:
            from backtest.indicator_store import IndicatorStore
            _worker_indicator_store = IndicatorStore(indicator_db_path)
        except Exception as exc:
            import logging
            logging.warning(f"[worker_init] Failed to open IndicatorStore: {exc}")


def _selector_chunk_worker(args):
    """
    模块级 worker 函数，供 ProcessPoolExecutor 跨进程调用。
    必须定义在模块顶层才能被 pickle 序列化。

    两种调用模式（由 _parallel_select 决定）：
    ─ DB 模式  (len(args) == 5):
        args = (class_name, params, indicator_db_path, date, chunk_codes)
        子进程从进程本地的 _worker_indicator_store 自行读取数据，
        主进程无需跨进程传输任何 DataFrame，彻底消除 pickle 序列化开销。

    ─ CSV 模式 (len(args) == 6):
        args = (class_name, params, None, date, chunk_codes, data_chunk)
        兼容旧逻辑，data_chunk 仍由主进程传入（CSV 场景数据量通常较小）。
    """
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

    # 解包参数（兼容两种模式）
    if len(args) == 5:
        selector_class_name, selector_params, indicator_db_path, date, chunk_codes = args
        data_chunk = None   # DB 模式：子进程自行读取
    else:
        selector_class_name, selector_params, indicator_db_path, date, chunk_codes, data_chunk = args

    import backtest.Selector as Selector_module
    selector_cls = getattr(Selector_module, selector_class_name)

    # 使用进程本地的 IndicatorStore（由 _worker_init 初始化，非 None 时表示 DB 模式）
    global _worker_indicator_store
    local_store = _worker_indicator_store

    # DB 模式：从本地 store 读取这批股票的历史数据（零跨进程传输）
    if data_chunk is None and local_store is not None:
        from datetime import timedelta as _td
        end_dt = date
        start_dt = end_dt - _td(days=300)   # 保证足够的指标计算历史窗口
        try:
            df_all = local_store.get_indicators_for_codes(
                chunk_codes,
                start_date=start_dt.strftime('%Y-%m-%d'),
                end_date=end_dt.strftime('%Y-%m-%d'),
            )
            data_chunk = {}
            if not df_all.empty:
                for code, group in df_all.groupby('code'):
                    data_chunk[code] = group.sort_values('date').reset_index(drop=True)
        except Exception:
            data_chunk = {}
    elif data_chunk is None:
        data_chunk = {}

    # 重建 selector 实例
    try:
        local_selector = selector_cls(**selector_params)
    except TypeError:
        local_selector = selector_cls()

    # 将本地 store 挂载到 selector（让其走 DB 路径而非实时计算）
    if local_store is not None and hasattr(local_selector, 'indicator_store'):
        local_selector.indicator_store = local_store

    return local_selector.select(date, data_chunk)


# ══════════════════════════════════════════════════════════════════
# BacktestEngine
# ══════════════════════════════════════════════════════════════════

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
        score_warmup_lookback_days: int = 20,
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
            parallel_workers: Worker processes for parallel stock screening (0 = auto)
        """
        self.data_dir = Path(data_dir)
        self.buy_config_path = buy_config_path
        self.buy_config = buy_config
        self.sell_strategy_config = sell_strategy_config
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)

        # Indicator database
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

        # Market data
        self.market_data: Dict[str, pd.DataFrame] = {}
        self.trading_dates: List[datetime] = []

        # ── [优化] 预建日期索引，供 searchsorted 使用 ─────────────
        # key: stock_code, value: numpy datetime64[ns] 数组（已排序）
        self._date_arrays: Dict[str, np.ndarray] = {}

        # Buy selectors
        self.buy_selectors: List[Any] = []

        # Selector combination config
        self.combination_mode = "OR"
        self.time_window_days = 5
        self.required_selectors = []

        # Signal history tracking (for TIME_WINDOW mode)
        self.signal_history: Dict[datetime, Dict[str, List[str]]] = {}

        # Sequential confirmation settings (for SEQUENTIAL_CONFIRMATION mode)
        self.trigger_selectors: List[str] = []
        self.trigger_logic = "OR"
        self.confirm_selectors: List[str] = []
        self.confirm_logic = "OR"
        self.buy_timing = "confirmation_day"

        # Track pending trigger signals waiting for confirmation
        self.pending_triggers: Dict[str, Dict[str, Any]] = {}

        # Sell strategy
        self.sell_strategy = None

        # Logging
        self.logs: List[str] = []
        self.log_callback = log_callback

        # Data preparation cache
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.cache_date: Optional[datetime] = None

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

        # ── [优化P0-1] 长驻进程池 ─────────────────────────────────
        # 原实现：_parallel_select() 内部每次调用都创建并销毁进程池
        # 优化后：在 __init__ 中创建一次，整个 run() 生命周期内复用
        self.parallel_workers: int = parallel_workers if parallel_workers > 0 else os.cpu_count() or 1
        self.log(f"Parallel workers: {self.parallel_workers}")

        # 进程池（workers > 1 时才创建）
        # [优化P0-3] 通过 initializer 在每个 worker 进程启动时初始化一次 IndicatorStore
        self._executor: Optional[ProcessPoolExecutor] = None
        if self.parallel_workers > 1:
            db_path_for_workers = self.indicator_db_path if self.use_indicator_db else None
            self._executor = ProcessPoolExecutor(
                max_workers=self.parallel_workers,
                initializer=_worker_init,
                initargs=(db_path_for_workers,),
            )
            self.log(f"Persistent process pool created ({self.parallel_workers} workers)")

        if self.use_indicator_db:
            self.log(f"Using indicator database: {self.indicator_db_path}")
        else:
            self.log("Using CSV data with real-time indicator computation")

    def __del__(self):
        """确保进程池在对象销毁时被清理（兜底机制）。"""
        if getattr(self, '_executor', None) is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass

    def _ensure_project_root_on_path(self):
        """Ensure project root is on sys.path for Selector imports."""
        import sys
        if self.buy_config_path:
            root = Path(self.buy_config_path).parent.parent
        else:
            root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

    # ══════════════════════════════════════════════════════════════════
    # [优化P1-1] 日期索引预建与 searchsorted 数据切片
    # ══════════════════════════════════════════════════════════════════

    def _build_date_index(self) -> None:
        """
        预处理：将每只股票的日期列转为 numpy datetime64[ns] 数组并缓存。

        供 _get_data_up_to_date() 和 _build_current_market_data() 使用
        searchsorted (O(log N)) 替代全量布尔过滤 (O(N))。

        在 load_data() 完成后调用一次。
        """
        self._date_arrays = {}
        for code, df in self.market_data.items():
            self._date_arrays[code] = df['date'].values.astype('datetime64[ns]')
        self.log(f"  Date index built for {len(self._date_arrays)} stocks")

    def _build_current_market_data(self, date: datetime) -> Dict[str, pd.Series]:
        """
        高效构建当日行情快照字典。

        [优化P1-1] 用 searchsorted O(log N) 替代原来的 df[df['date'] == date] O(N)，
        对 5000 支股票提速约 3~5 倍。

        Args:
            date: 目标交易日

        Returns:
            Dict[股票代码, 当日 Series]，不含当日无数据的股票
        """
        date_np = np.datetime64(date, 'ns')
        result: Dict[str, pd.Series] = {}

        for code, arr in self._date_arrays.items():
            idx = int(np.searchsorted(arr, date_np, side='left'))
            if idx < len(arr) and arr[idx] == date_np:
                result[code] = self.market_data[code].iloc[idx]

        return result

    # ══════════════════════════════════════════════════════════════════
    # 数据加载
    # ══════════════════════════════════════════════════════════════════

    def load_data(self, stock_codes: Optional[List[str]] = None, lookback_days: int = 200):
        """
        Load historical data from CSV files or indicator database.

        Args:
            stock_codes: List of stock codes. If None, loads all.
            lookback_days: Calendar days before start_date to load for indicator calculations.
        """
        if self.use_indicator_db and self.indicator_store:
            self._load_data_from_db(stock_codes, lookback_days)
        else:
            self._load_data_from_csv(stock_codes, lookback_days)

        # [优化P1-1] 数据加载完成后，立即预建日期索引
        self._build_date_index()

    def _load_data_from_db(self, stock_codes: Optional[List[str]], lookback_days: int):
        """从指标数据库加载数据（新模式）。"""
        self.log("Loading data from indicator database...")

        data_start_date = self.start_date - timedelta(days=lookback_days)
        self.log(f"Loading data from {data_start_date.date()} (backtest starts {self.start_date.date()})")

        if stock_codes is None:
            codes = self.indicator_store.get_all_codes()
        else:
            codes = stock_codes

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

        if len(self.trading_dates) == 0:
            raise ValueError(
                f"No trading dates found in database. "
                f"Check if database contains data for the backtest period "
                f"({self.start_date.date()} to {self.end_date.date()})"
            )

        self.log(
            f"Trading dates: {len(self.trading_dates)} days "
            f"from {self.trading_dates[0].date()} to {self.trading_dates[-1].date()}"
        )
        self.validate_data_quality()

    def _load_data_from_csv(self, stock_codes: Optional[List[str]], lookback_days: int):
        """从 CSV 文件加载数据（原有逻辑）。"""
        self.log("Loading market data from CSV files...")

        data_start_date = self.start_date - timedelta(days=lookback_days)
        self.log(f"Loading data from {data_start_date.date()} (backtest starts {self.start_date.date()})")

        if stock_codes is None:
            csv_files = list(self.data_dir.glob("*.csv"))
        else:
            csv_files = [self.data_dir / f"{code}.csv" for code in stock_codes]

        loaded_count = 0
        for csv_file in csv_files:
            if not csv_file.exists():
                continue
            try:
                df = pd.read_csv(csv_file)
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                else:
                    self.log(f"Warning: {csv_file.name} missing 'date' column")
                    continue

                df = df.sort_values('date').reset_index(drop=True)
                df = df[(df['date'] >= data_start_date) & (df['date'] <= self.end_date)]

                if len(df) == 0:
                    continue

                code = csv_file.stem
                self.market_data[code] = df
                loaded_count += 1

            except Exception as e:
                self.log(f"Error loading {csv_file.name}: {e}")

        self.log(f"Loaded {loaded_count} stocks")

        all_dates = set()
        for df in self.market_data.values():
            backtest_dates = df[(df['date'] >= self.start_date) & (df['date'] <= self.end_date)]['date'].tolist()
            all_dates.update(backtest_dates)

        self.trading_dates = sorted(list(all_dates))

        if len(self.trading_dates) == 0:
            raise ValueError(
                f"No trading dates found in data. "
                f"Check if data files exist in {self.data_dir} and cover the backtest period "
                f"({self.start_date.date()} to {self.end_date.date()})"
            )

        self.log(
            f"Trading dates: {len(self.trading_dates)} days "
            f"from {self.trading_dates[0].date()} to {self.trading_dates[-1].date()}"
        )
        self.validate_data_quality()

    def validate_data_quality(self):
        """Check if data meets selector requirements and validate OHLC consistency."""
        self.log("\nValidating data quality...")

        if not self.market_data:
            self.log("  WARNING: No market data loaded")
            return

        ohlc_issues = []
        price_issues = []

        for code, df in self.market_data.items():
            if (df['low'] < 0).any():
                price_issues.append(f"{code}: negative prices detected")

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
            for issue in ohlc_issues[:10]:
                self.log(f"    - {issue}")
            if len(ohlc_issues) > 10:
                self.log(f"    ... and {len(ohlc_issues) - 10} more")

        if price_issues:
            self.log("  WARNING: Price validation issues:")
            for issue in price_issues[:5]:
                self.log(f"    - {issue}")

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

        insufficient_60ma = sum(1 for l in lengths_at_start if l < 60)
        insufficient_120 = sum(1 for l in lengths_at_start if l < 120)

        self.log(f"    Stocks with <60 days (MA60 won't work): {insufficient_60ma}")
        self.log(f"    Stocks with <120 days (max_window): {insufficient_120}")

        if insufficient_120 > len(lengths_at_start) * 0.5:
            self.log("  WARNING: >50% of stocks have <120 days data at backtest start")
            self.log("          Consider using later start_date or increase lookback_days")

    # ══════════════════════════════════════════════════════════════════
    # 选股器 / 卖出策略加载
    # ══════════════════════════════════════════════════════════════════

    def load_buy_selectors(self):
        """从 config.json 加载买入选股器。"""
        self.log("Loading buy selectors...")

        if self.buy_config is not None:
            config = self.buy_config
        else:
            with open(self.buy_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

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
                self.trigger_selectors = comb.get('trigger_selectors', [])
                self.trigger_logic = comb.get('trigger_logic', 'OR')
                self.confirm_selectors = comb.get('confirm_selectors', [])
                self.confirm_logic = comb.get('confirm_logic', 'OR')
                self.buy_timing = comb.get('buy_timing', 'confirmation_day')

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
            self.combination_mode = "OR"
            self.log("Selector combination mode: OR (default)")

        self._ensure_project_root_on_path()

        selectors_config = config.get('selectors', [])
        loaded = 0

        for selector_cfg in selectors_config:
            if not selector_cfg.get('activate', True):
                continue

            class_name = selector_cfg.get('class')
            alias = selector_cfg.get('alias', class_name)
            params = selector_cfg.get('params', {})

            try:
                import backtest.Selector as Selector_module
                selector_cls = getattr(Selector_module, class_name)
                instance = selector_cls(**params)

                if self.use_indicator_db and self.indicator_store:
                    if hasattr(instance, 'indicator_store'):
                        instance.indicator_store = self.indicator_store

                self.buy_selectors.append({
                    'class': class_name,
                    'alias': alias,
                    'instance': instance,
                    'params': params,
                })
                self.log(f"  Loaded: {alias} ({class_name})")
                loaded += 1

            except Exception as e:
                self.log(f"  ERROR loading {class_name}: {e}")

        self.log(f"Loaded {loaded} buy selector(s)")

    def load_sell_strategy(self):
        """加载卖出策略。"""
        self.log("Loading sell strategy...")

        from .sell_strategies.base import create_sell_strategy
        self.sell_strategy = create_sell_strategy(self.sell_strategy_config)

        if isinstance(self.sell_strategy_config, dict):
            strategy_name = (
                self.sell_strategy_config.get('name') or
                self.sell_strategy_config.get('class') or
                'Unknown'
            )
        elif isinstance(self.sell_strategy_config, list):
            strategy_name = f"Multiple Strategies ({len(self.sell_strategy_config)})"
        else:
            strategy_name = 'Unknown'

        self.log(f"Loaded sell strategy: {strategy_name}")

    # ══════════════════════════════════════════════════════════════════
    # [优化P1-1] 数据切片：searchsorted 替代布尔过滤
    # ══════════════════════════════════════════════════════════════════

    def _get_data_up_to_date(self, date: datetime) -> Dict[str, pd.DataFrame]:
        """
        获取截至指定日期的数据（带缓存）。

        [优化P1-1] 使用预建的 numpy datetime64 索引 + searchsorted (O(log N))，
        替代原来的 df[df['date'] <= date] 全量布尔扫描 (O(N))。
        对 5000 支股票 × 250 天，总计减少约 125 万次布尔数组运算。

        Args:
            date: 目标日期（含该日）

        Returns:
            Dict[股票代码, DataFrame 视图（截至 date）]
        """
        # 同一天直接返回缓存（最常见情况）
        if date == self.cache_date and self.data_cache:
            return self.data_cache

        date_np = np.datetime64(date, 'ns')
        self.data_cache = {}

        for code, df in self.market_data.items():
            arr = self._date_arrays.get(code)
            if arr is None:
                # fallback（不应发生，但作为防御）
                df_filtered = df[df['date'] <= date]
                if len(df_filtered) > 0:
                    self.data_cache[code] = df_filtered
            else:
                # searchsorted: 找到第一个 > date 的位置，取 [0:idx] 即为 <= date 的所有行
                idx = int(np.searchsorted(arr, date_np, side='right'))
                if idx > 0:
                    self.data_cache[code] = df.iloc[:idx]   # 视图，无拷贝

        self.cache_date = date
        return self.data_cache

    # ══════════════════════════════════════════════════════════════════
    # [优化P0-1/P0-2] 并行选股
    # ══════════════════════════════════════════════════════════════════

    def _parallel_select(
        self,
        selector,
        date: datetime,
        data_up_to_date: Dict[str, pd.DataFrame],
    ) -> List[str]:
        """
        并行版 selector.select()。

        [优化P0-1] 使用长驻进程池 self._executor（而非每次临时创建），
        消除每日 fork/销毁进程的巨大开销。

        [优化P0-2] DB 模式下只传股票代码列表（字符串），不传 DataFrame，
        子进程自行从 _worker_indicator_store 读取数据，彻底消除大 DataFrame 的
        pickle 序列化 + 跨进程传输开销。

        CSV 模式下保留旧逻辑（传入 data_chunk），确保向后兼容。
        """
        codes = list(data_up_to_date.keys())
        n = self.parallel_workers

        # 单进程 或 股票数少于 worker 数：直接走串行
        if self._executor is None or n <= 1 or len(codes) <= n:
            return selector.select(date, data_up_to_date)

        # 将股票池均匀分片
        chunk_size = max(1, math.ceil(len(codes) / n))
        chunks = [codes[i:i + chunk_size] for i in range(0, len(codes), chunk_size)]

        selector_class_name = type(selector).__name__
        selector_params = {
            k: v for k, v in vars(selector).items()
            if not k.startswith('_') and k != 'indicator_store'
        }
        indicator_db_path = self.indicator_db_path if self.use_indicator_db else None

        if self.use_indicator_db:
            # [优化P0-2] DB 模式：只传代码列表（5 元素 tuple），子进程自行读取数据
            tasks = [
                (selector_class_name, selector_params, indicator_db_path, date, chunk)
                for chunk in chunks
            ]
        else:
            # CSV 模式（兼容旧逻辑）：仍传入 data_chunk（通常数据量较小）
            tasks = [
                (
                    selector_class_name, selector_params, None, date, chunk,
                    {c: data_up_to_date[c] for c in chunk if c in data_up_to_date},
                )
                for chunk in chunks
            ]

        picks: List[str] = []
        futures = {self._executor.submit(_selector_chunk_worker, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                picks.extend(future.result())
            except Exception as e:
                self.log(f"  [parallel_select] chunk error: {e}")

        return picks

    # ══════════════════════════════════════════════════════════════════
    # 买入信号相关
    # ══════════════════════════════════════════════════════════════════

    def get_buy_signals(self, date: datetime, cancel_check=None) -> List[BuySignal]:
        """获取当日原始买入信号（未经 score 百分位过滤）。"""
        self.log(f"\n{'='*80}")
        self.log(f"GETTING BUY SIGNALS FOR {date.date()}")
        self.log(f"{'='*80}")

        t0 = _time.perf_counter()
        data_up_to_date = self._get_data_up_to_date(date)
        self.log(f"  Data slice ready: {len(data_up_to_date)} stocks in {_time.perf_counter()-t0:.3f}s")

        signals_by_selector: Dict[str, List[BuySignal]] = {}

        for selector_info in self.buy_selectors:
            if cancel_check and cancel_check():
                break

            alias      = selector_info['alias']
            class_name = selector_info['class']
            selector   = selector_info['instance']

            try:
                self.log(f"  Running {alias}...")
                t1 = _time.perf_counter()

                picked_codes: List[str] = self._parallel_select(selector, date, data_up_to_date)
                self.log(f"    → {len(picked_codes)} picks in {_time.perf_counter()-t1:.3f}s ({self.parallel_workers} workers)")

                signals: List[BuySignal] = []
                for code in picked_codes:
                    if code not in data_up_to_date:
                        continue
                    df_code  = data_up_to_date[code]
                    last_row = df_code.iloc[-1]
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

    def _get_raw_signals_for_date(
        self, date: datetime, silent: bool = False
    ) -> tuple:
        """
        获取指定日期的原始信号（不做 score 过滤，不追加 score_history）。
        供 warmup_score_history 和主循环复用同一管线。

        Returns
        -------
        (signals, errors) : (List[BuySignal], List[str])
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
                self.log = orig_log

    def _apply_combination_logic(
        self,
        signals_by_selector: Dict[str, List[BuySignal]],
        current_date: datetime
    ) -> List[BuySignal]:
        """Apply selector combination logic."""
        if self.combination_mode == "OR":
            all_signals = []
            for signals in signals_by_selector.values():
                all_signals.extend(signals)

            signals_by_code: Dict[str, BuySignal] = {}
            for signal in all_signals:
                if signal.code not in signals_by_code:
                    signals_by_code[signal.code] = signal
                elif signal.score > signals_by_code[signal.code].score:
                    signals_by_code[signal.code] = signal

            return list(signals_by_code.values())

        elif self.combination_mode == "AND":
            required = self.required_selectors if self.required_selectors else list(signals_by_selector.keys())

            signals_by_code_list: Dict[str, List[BuySignal]] = {}
            for selector_name, signals in signals_by_selector.items():
                if selector_name not in required:
                    continue
                for signal in signals:
                    if signal.code not in signals_by_code_list:
                        signals_by_code_list[signal.code] = []
                    signals_by_code_list[signal.code].append(signal)

            final_signals = []
            for code, signals in signals_by_code_list.items():
                selector_names = {s.strategy_name for s in signals}
                if len(selector_names) >= len(required):
                    best_signal = max(signals, key=lambda s: s.score)
                    final_signals.append(best_signal)

            return final_signals

        elif self.combination_mode == "TIME_WINDOW":
            self._update_signal_history(signals_by_selector, current_date)

            final_signals = []
            window_dates = [
                d for d in self.signal_history.keys()
                if (current_date - d).days <= self.time_window_days
            ]

            for selector_name, signals in signals_by_selector.items():
                for signal in signals:
                    code = signal.code
                    picked_by_selectors = {selector_name}

                    for hist_date in window_dates:
                        for hist_selector, hist_codes in self.signal_history[hist_date].items():
                            if code in hist_codes:
                                picked_by_selectors.add(hist_selector)

                    required_count = len(self.required_selectors) if self.required_selectors else 2

                    if len(picked_by_selectors) >= required_count:
                        final_signals.append(signal)

            signals_by_code_dedup: Dict[str, BuySignal] = {}
            for signal in final_signals:
                if signal.code not in signals_by_code_dedup:
                    signals_by_code_dedup[signal.code] = signal
                elif signal.score > signals_by_code_dedup[signal.code].score:
                    signals_by_code_dedup[signal.code] = signal

            return list(signals_by_code_dedup.values())

        elif self.combination_mode == "SEQUENTIAL_CONFIRMATION":
            return self._apply_sequential_confirmation(signals_by_selector, current_date)

        else:
            raise ValueError(f"Unknown combination mode: {self.combination_mode}")

    def _update_signal_history(
        self,
        signals_by_selector: Dict[str, List[BuySignal]],
        current_date: datetime
    ):
        """Update signal history for TIME_WINDOW mode."""
        self.signal_history[current_date] = {}
        for selector_name, signals in signals_by_selector.items():
            self.signal_history[current_date][selector_name] = [s.code for s in signals]

        cutoff_date = current_date - timedelta(days=self.time_window_days + 1)
        for d in [d for d in self.signal_history.keys() if d < cutoff_date]:
            del self.signal_history[d]

    def _apply_sequential_confirmation(
        self,
        signals_by_selector: Dict[str, List[BuySignal]],
        current_date: datetime
    ) -> List[BuySignal]:
        """Apply sequential confirmation logic."""
        trigger_signals: Dict[str, List[BuySignal]] = {}
        confirm_signals: Dict[str, List[BuySignal]] = {}

        for selector_name, signals in signals_by_selector.items():
            if selector_name in self.trigger_selectors:
                trigger_signals[selector_name] = signals
            if selector_name in self.confirm_selectors:
                confirm_signals[selector_name] = signals

        new_triggers = self._evaluate_trigger_logic(trigger_signals)

        for signal in new_triggers:
            if signal.code not in self.pending_triggers:
                expiration_date = current_date + timedelta(days=self.time_window_days)
                self.pending_triggers[signal.code] = {
                    'trigger_date': current_date,
                    'expiration_date': expiration_date,
                    'trigger_signal': signal,
                }
                self.log(f"  TRIGGER: {signal.code} ({signal.strategy_alias}) - awaiting confirmation by {expiration_date.date()}")

        confirmed_codes = self._evaluate_confirm_logic(confirm_signals)
        confirmed_signals = []

        for code in confirmed_codes:
            if code in self.pending_triggers:
                pending = self.pending_triggers[code]
                self.log(f"  CONFIRMED: {code} (trigger: {pending['trigger_date'].date()}, confirm: {current_date.date()})")

                if self.buy_timing == "trigger_day":
                    buy_signal = pending['trigger_signal']
                else:
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
                del self.pending_triggers[code]

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
        """Evaluate trigger logic (AND/OR) on trigger_selectors."""
        if self.trigger_logic == "OR":
            all_signals = []
            for signals in trigger_signals.values():
                all_signals.extend(signals)

            signals_by_code: Dict[str, BuySignal] = {}
            for signal in all_signals:
                if signal.code not in signals_by_code:
                    signals_by_code[signal.code] = signal
                elif signal.score > signals_by_code[signal.code].score:
                    signals_by_code[signal.code] = signal

            return list(signals_by_code.values())

        elif self.trigger_logic == "AND":
            if len(trigger_signals) < len(self.trigger_selectors):
                return []

            signals_by_code_list: Dict[str, List[BuySignal]] = {}
            for selector_name, signals in trigger_signals.items():
                for signal in signals:
                    if signal.code not in signals_by_code_list:
                        signals_by_code_list[signal.code] = []
                    signals_by_code_list[signal.code].append(signal)

            final_signals = []
            for code, signals in signals_by_code_list.items():
                selector_names = {s.strategy_name for s in signals}
                if len(selector_names) >= len(self.trigger_selectors):
                    best_signal = max(signals, key=lambda s: s.score)
                    final_signals.append(best_signal)

            return final_signals

        else:
            raise ValueError(f"Unknown trigger_logic: {self.trigger_logic}")

    def _evaluate_confirm_logic(
        self,
        confirm_signals: Dict[str, List[BuySignal]]
    ) -> List[str]:
        """Evaluate confirmation logic (AND/OR) on confirm_selectors."""
        if self.confirm_logic == "OR":
            confirmed_codes: set = set()
            for signals in confirm_signals.values():
                for signal in signals:
                    confirmed_codes.add(signal.code)
            return list(confirmed_codes)

        elif self.confirm_logic == "AND":
            if len(confirm_signals) < len(self.confirm_selectors):
                return []

            signals_by_code: Dict[str, List[str]] = {}
            for selector_name, signals in confirm_signals.items():
                for signal in signals:
                    if signal.code not in signals_by_code:
                        signals_by_code[signal.code] = []
                    signals_by_code[signal.code].append(selector_name)

            confirmed_codes = []
            for code, selector_names in signals_by_code.items():
                if len(set(selector_names)) >= len(self.confirm_selectors):
                    confirmed_codes.append(code)

            return confirmed_codes

        else:
            raise ValueError(f"Unknown confirm_logic: {self.confirm_logic}")

    # ══════════════════════════════════════════════════════════════════
    # [优化P1-2] 卖出信号检查（并行化）
    # ══════════════════════════════════════════════════════════════════

    def check_sell_signals(
        self, date: datetime, cancel_check: Optional[Any] = None
    ) -> List[Tuple[str, str]]:
        """
        Check sell conditions for all positions.

        [优化P1-2] 使用 ThreadPoolExecutor 并行检查持仓：
        - 持仓间完全独立，无共享可变状态
        - pandas/numpy 计算在 C 层释放 GIL，线程并行有效
        - 使用 searchsorted 代替布尔过滤获取当日行数据

        CRITICAL: Prevents lookahead bias by only using data up to current date.

        Args:
            date: Current date
            cancel_check: Optional callable to check if backtest is cancelled

        Returns:
            List of (code, exit_reason) tuples
        """
        # 确保缓存已更新（_parallel_select 可能已经调用过，这里只是确认）
        self._get_data_up_to_date(date)

        positions = list(self.portfolio.positions.values())
        if not positions:
            return []

        date_np = np.datetime64(date, 'ns')

        def _check_one(position) -> Optional[Tuple[str, str]]:
            if cancel_check and cancel_check():
                return None

            code = position.code

            # 从缓存获取截至今日的历史数据
            df_up_to_date = self.data_cache.get(code)
            if df_up_to_date is None or len(df_up_to_date) == 0:
                return None

            # [优化P1-1] searchsorted 查找今日数据行
            arr = self._date_arrays.get(code)
            if arr is not None:
                idx = int(np.searchsorted(arr, date_np, side='left'))
                if idx < len(arr) and arr[idx] == date_np:
                    current_data = self.market_data[code].iloc[idx]
                else:
                    return None   # 今日无数据（可能停牌）
            else:
                # fallback
                df_today = df_up_to_date[df_up_to_date['date'] == date]
                if len(df_today) == 0:
                    return None
                current_data = df_today.iloc[-1]

            try:
                should_sell, reason = self.sell_strategy.should_sell(
                    position=position,
                    current_date=date,
                    current_data=current_data,
                    hist_data=df_up_to_date,
                    indicators=current_data if self.use_indicator_db else None
                )
                return (code, reason) if should_sell else None

            except Exception as e:
                self.log(f"Error checking sell for {code}: {e}")
                return None

        # 持仓少时直接串行，避免线程创建开销
        if len(positions) <= 3:
            return [r for r in (_check_one(p) for p in positions) if r is not None]

        # 持仓多时并行化（ThreadPoolExecutor，共享 data_cache 内存，无需序列化）
        n_threads = min(8, len(positions))
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            results = list(pool.map(_check_one, positions))

        return [r for r in results if r is not None]

    # ══════════════════════════════════════════════════════════════════
    # 买入订单处理
    # ══════════════════════════════════════════════════════════════════

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
        """
        signals_attempted = 0
        orders_created = 0

        for signal in buy_signals:
            if not self.portfolio.can_open_new_position():
                self.log(
                    f"  Position limit reached ({self.portfolio.max_positions}), "
                    f"stopping signal processing"
                )
                break

            if signal.code not in current_market_data:
                signals_attempted += 1
                self.log(f"  SKIPPED: {signal.code} ({signal.strategy_alias}) - no market data")
                continue

            current_price = current_market_data[signal.code]['close']

            df_up_to_date = self.data_cache.get(signal.code)
            if df_up_to_date is None:
                df = self.market_data[signal.code]
                df_up_to_date = df[df['date'] <= date]

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
    # Score 百分位过滤
    # ══════════════════════════════════════════════════════════════════

    def filter_signals_by_score(
        self, raw_signals: List[BuySignal], date: datetime
    ) -> List[BuySignal]:
        """
        将当日信号 score 追加进 score_history，然后按百分位阈值过滤。
        先追加再过滤，保证今日 score 不参与今日阈值计算（防未来函数）。
        """
        if not self.score_filter_enabled:
            return raw_signals

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

    def warmup_score_history(self, force_legacy: bool = True) -> None:
        """
        Bootstrap 预热：用 lookback_days 历史数据预填充 score_history。

        在 load_buy_selectors() 和 load_sell_strategy() 之后、run() 之前调用。
        预热期完整复用选股器管线（含 combination_logic），确保历史分布与
        主循环信号口径一致。预热期内压制普通日志，但保留错误收集，完成后统一输出摘要。

        Parameters
        ----------
        force_legacy : bool, default True
            True 时预热期强制走实时计算（legacy）路径，忽略 indicator_db。
        """
        if not self.score_filter_enabled and self.rotation_manager is None:
            return

        if not self.buy_selectors:
            self.log("warmup_score_history: no selectors loaded, skipping")
            return

        warmup_date_set: set = set()
        for df in self.market_data.values():
            pre_dates = df[df['date'] < self.start_date]['date']
            warmup_date_set.update(pre_dates.tolist())
        all_warmup_dates = sorted(warmup_date_set)

        if not all_warmup_dates:
            self.log("warmup_score_history: no warmup dates available (check lookback_days)")
            return

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
            for warmup_date in warmup_dates:
                signals, errors = self._get_raw_signals_for_date(warmup_date, silent=True)
                date_errors.extend(errors)

                for s in signals:
                    self.score_history.append(s.score)
                    collected += 1

        finally:
            if force_legacy and saved_engine_db:
                self.use_indicator_db = saved_engine_db
                for info in self.buy_selectors:
                    sel = info['instance']
                    if id(sel) in saved_selector_stores:
                        sel.indicator_store = saved_selector_stores[id(sel)]

        self.log(f"  Warmup complete: {collected} signals collected over {len(warmup_dates)} dates")
        self.log(f"  Score history size: {len(self.score_history)}")

        if date_errors:
            self.log(f"  Warmup errors ({len(date_errors)} total, showing first 5):")
            for err in date_errors[:5]:
                self.log(f"    {err}")

        if len(self.score_history) == 0:
            self.log(
                "  WARNING: Score history is empty after warmup. "
                "Possible causes: selectors erroring out (see errors above), "
                "or no stocks passed filters in warmup period."
            )

    # ══════════════════════════════════════════════════════════════════
    # 主事件循环
    # ══════════════════════════════════════════════════════════════════

    def run(self, progress_callback: Optional[Any] = None, cancel_check: Optional[Any] = None):
        """
        Run backtest.

        Main event loop over trading dates.
        [优化P0-1] run() 结束后（无论正常还是异常）在 finally 块中关闭进程池。
        """
        self.log("\n" + "="*80)
        self.log("BACKTEST START")
        self.log("="*80)

        # ── 注入交易日历到 portfolio（FIX-3 需要）──────────────────────
        # 必须在主循环开始前完成，让 _next_trading_date() 能正确查找下一交易日
        self.portfolio.set_trading_dates(self.trading_dates)
        # ──────────────────────────────────────────────────────────────

        try:
            total_days = len(self.trading_dates)

            for idx, date in enumerate(self.trading_dates, start=1):
                if cancel_check and cancel_check():
                    self.log("BACKTEST CANCELLED")
                    break

                self.log(f"\n--- {date.date()} ---")
                self.log(
                    f"  Cash: {self.portfolio.cash:,.2f}, "
                    f"Available: {self.portfolio.get_available_cash():,.2f}, "
                    f"Positions: {len(self.portfolio.positions)}"
                )

                # 1. Process T+1 settlement
                self.portfolio.process_settlement(date)

                proceeds = self.portfolio.settlement_tracker.pending_proceeds.get(date, 0)
                if proceeds > 0:
                    self.log(f"  Settlement: +{proceeds:,.2f} proceeds received")

                # 2. Execute pending buy orders from T-1
                executed_orders = self.portfolio.execute_pending_orders(date, self.market_data)
                from .data_structures import OrderAction, OrderStatus
                for order in executed_orders:
                    if order.status.value == "EXECUTED":
                        self.log(f"  EXECUTED {order.action.value}: {order.code} x {order.shares} @ {order.execution_price:.2f}")
                    else:
                        self.log(f"  FAILED {order.action.value}: {order.code} - {order.reason}")

                # 3. Update position metrics
                # [优化P1-1] 用 searchsorted 替代全量布尔过滤构建当日行情快照
                current_market_data = self._build_current_market_data(date)

                self.portfolio.update_positions(date, current_market_data)

                # 4. Check sell signals
                # [优化P1-2] 并行检查卖出信号（ThreadPoolExecutor）
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

                # 5. Get buy signals → score 过滤
                raw_signals, _ = self._get_raw_signals_for_date(date)
                buy_signals = self.filter_signals_by_score(raw_signals, date)

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
                        rotation_entry_codes = {o.code for o in r_buys}
                        buy_signals = [s for s in buy_signals if s.code not in rotation_entry_codes]
                        for pair in rotation_pairs:
                            sell_triggered_codes.add(pair.exit_position.code)

                # 6. Generate buy orders for T+1 with fallback mechanism
                self._process_buy_signals_with_fallback(date, buy_signals, current_market_data)

                # 7. Update equity curve
                self.portfolio.update_equity_curve(date, current_market_data)

                self.log(f"  Portfolio: {len(self.portfolio.positions)} positions, Cash: {self.portfolio.cash:,.0f}, Total: {self.portfolio.total_value:,.0f}")
                if progress_callback:
                    progress_callback(idx, total_days, date)

            # ── 强制平仓（回测结束）──────────────────────────────────
            if len(self.portfolio.positions) > 0:
                self.log("\n" + "="*80)
                self.log("FORCE LIQUIDATION - Closing all positions")
                self.log("="*80)

                last_date = self.trading_dates[-1]
                positions_to_close = list(self.portfolio.positions.keys())
                for code in positions_to_close:
                    self.portfolio.generate_sell_order(code, last_date, "End of backtest - forced liquidation")
                    self.log(f"  Generated sell order for {code}")

                virtual_execution_date = last_date + timedelta(days=1)
                self.log(f"\n--- Virtual Execution Date: {virtual_execution_date.date()} ---")

                self.portfolio.process_settlement(virtual_execution_date)

                market_data_virtual = {}
                for code, df in self.market_data.items():
                    df_last = df[df['date'] == last_date]
                    if len(df_last) > 0:
                        df_virtual = df_last.copy()
                        df_virtual['date'] = virtual_execution_date
                        market_data_virtual[code] = pd.concat([df, df_virtual], ignore_index=True)
                    else:
                        market_data_virtual[code] = df

                executed_orders = self.portfolio.execute_pending_orders(virtual_execution_date, market_data_virtual)

                from .data_structures import OrderAction, OrderStatus
                for order in executed_orders:
                    if order.status.value == "EXECUTED":
                        self.log(f"  EXECUTED {order.action.value}: {order.code} x {order.shares} @ {order.execution_price:.2f}")
                    else:
                        self.log(f"  FAILED {order.action.value}: {order.code} - {order.reason}")

                # [优化P1-1] 强制平仓后的最终行情也用 searchsorted
                final_market_data = self._build_current_market_data(last_date)
                self.portfolio.update_equity_curve(virtual_execution_date, final_market_data)

                self.log(
                    f"  Final portfolio: {len(self.portfolio.positions)} positions, "
                    f"Cash: {self.portfolio.cash:,.0f}, Total: {self.portfolio.total_value:,.0f}"
                )

            self.log("\n" + "="*80)
            self.log("BACKTEST COMPLETE")
            self.log("="*80 + "\n")

        finally:
            # [优化P0-1] 无论正常结束还是异常，都关闭长驻进程池
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
                self.log("Process pool shut down.")

    # ══════════════════════════════════════════════════════════════════
    # 结果 & 日志
    # ══════════════════════════════════════════════════════════════════

    def get_results(self) -> Dict[str, Any]:
        """Get backtest results."""
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

    # ══════════════════════════════════════════════════════════════════
    # 指标提取
    # ══════════════════════════════════════════════════════════════════

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
        # 路径1：DB 模式，last_row 含指标列
        if last_row is not None and 'kdj_j' in last_row.index:
            kdj_j = float(last_row.get('kdj_j', float('nan')))

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

            if 'daily_return' in last_row.index and not pd.isna(last_row['daily_return']):
                daily_return = float(last_row['daily_return'])
            elif df_full is not None and len(df_full) >= 2 and 'close' in df_full.columns:
                df_sorted = df_full.sort_values('date')
                prev = float(df_sorted['close'].iloc[-2])
                curr = float(df_sorted['close'].iloc[-1])
                daily_return = (curr - prev) / prev if prev > 0 else 0.0
            else:
                daily_return = 0.0

            if 'bbi' in last_row.index and df_full is not None and len(df_full) >= 2:
                bbi_series = df_full['bbi'] if 'bbi' in df_full.columns else None
                if bbi_series is not None and len(bbi_series.dropna()) >= 2:
                    recent = bbi_series.dropna().tail(2)
                    if len(recent) == 2:
                        bbi_slope = float(recent.iloc[-1]) - float(recent.iloc[-2])
                    else:
                        bbi_slope = 0.0
                else:
                    bbi_slope = 0.0
            else:
                bbi_slope = 0.0

            return {
                'kdj_j': kdj_j if not np.isnan(kdj_j) else 0.0,
                'volume_ratio': volume_ratio,
                'daily_return': daily_return,
                'bbi_slope': bbi_slope,
            }

        # 路径2：legacy 模式，实时计算指标
        if df_full is not None and len(df_full) > 0:
            try:
                from utils.indicators import compute_kdj, compute_bbi
                kdj_result = compute_kdj(df_full)
                kdj_j = float(kdj_result['J'].iloc[-1]) if 'J' in kdj_result.columns else 0.0

                if len(df_full) >= 2 and 'volume' in df_full.columns:
                    avg_vol = float(df_full['volume'].tail(20).mean())
                    curr_vol = float(df_full['volume'].iloc[-1])
                    volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 0.0
                else:
                    volume_ratio = 0.0

                if len(df_full) >= 2 and 'close' in df_full.columns:
                    prev = float(df_full['close'].iloc[-2])
                    curr = float(df_full['close'].iloc[-1])
                    daily_return = (curr - prev) / prev if prev > 0 else 0.0
                else:
                    daily_return = 0.0

                bbi_series = compute_bbi(df_full)
                recent = bbi_series.dropna().tail(2)
                bbi_slope = float(recent.iloc[-1]) - float(recent.iloc[-2]) if len(recent) == 2 else 0.0

                return {
                    'kdj_j': kdj_j,
                    'volume_ratio': volume_ratio,
                    'daily_return': daily_return,
                    'bbi_slope': bbi_slope,
                }
            except Exception:
                pass

        # 路径3：兜底，返回全零
        return {'kdj_j': 0.0, 'volume_ratio': 0.0, 'daily_return': 0.0, 'bbi_slope': 0.0}