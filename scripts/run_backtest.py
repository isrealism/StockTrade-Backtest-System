#!/usr/bin/env python
"""
Comprehensive backtest runner for Z's Trading Strategies.

Usage:
    # Run with default settings
    python scripts/run_backtest.py

    # Specify sell strategy
    python scripts/run_backtest.py --sell-strategy conservative_trailing

    # Custom date range
    python scripts/run_backtest.py --start 2025-01-01 --end 2025-12-31

    # Use pre-computed indicator database
    python scripts/run_backtest.py --use-indicator-db

    # Enable score filter
    python scripts/run_backtest.py --score-filter --score-percentile 60

    # Enable rotation
    python scripts/run_backtest.py --rotation --rotation-min-loss 0.05

    # Save results to file
    python scripts/run_backtest.py --save-results ./backtest_results/my_test.json

Example:
    python scripts/run_backtest.py \\
        --start 2025-01-01 \\
        --end 2025-12-31 \\
        --sell-strategy conservative_trailing \\
        --initial-capital 1000000 \\
        --max-positions 20 \\
        --use-indicator-db \\
        --score-filter \\
        --rotation \\
        --save-results ./backtest_results/conservative_2025.json
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.engine import BacktestEngine
from backtest.performance import PerformanceAnalyzer

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_sell_strategy_config(strategy_name: str) -> dict:
    """Load sell strategy configuration from configs/sell_strategies.json."""
    config_path = PROJECT_ROOT / "configs/sell_strategies.json"

    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    strategies = config.get('strategies', {})

    if strategy_name not in strategies:
        print(f"ERROR: Strategy '{strategy_name}' not found in {config_path}")
        print(f"Available strategies: {', '.join(strategies.keys())}")
        sys.exit(1)

    return strategies[strategy_name]


def save_results(results: dict, output_path: str):
    """Save results to JSON file."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    def json_serializer(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=json_serializer, ensure_ascii=False)

    print(f"\nResults saved to: {output_file}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run backtest for Z's Trading Strategies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # ── 数据与日期 ────────────────────────────────────────────────
    data = parser.add_argument_group("Data & Date Range")
    data.add_argument(
        '--data-dir',
        default=str(PROJECT_ROOT / 'data'),
        help=f'Directory with historical K-line data (default: {PROJECT_ROOT}/data)'
    )
    data.add_argument(
        '--start',
        default='2025-01-01',
        help='Start date YYYY-MM-DD (default: 2025-01-01)'
    )
    data.add_argument(
        '--end',
        default='2025-12-31',
        help='End date YYYY-MM-DD (default: 2025-12-31)'
    )
    data.add_argument(
        '--lookback-days',
        type=int,
        default=200,
        help='Trading days before start_date to load for indicator warm-up (default: 200)'
    )

    # ── 策略配置 ──────────────────────────────────────────────────
    strat = parser.add_argument_group("Strategy")
    strat.add_argument(
        '--buy-config',
        default=str(PROJECT_ROOT / 'configs/buy_selectors.json'),
        help='Buy strategies configuration file'
    )
    strat.add_argument(
        '--sell-strategy',
        default='conservative_trailing',
        help='Sell strategy name from sell_strategies.json (default: conservative_trailing)'
    )

    # ── 仓位与资金 ────────────────────────────────────────────────
    port = parser.add_argument_group("Portfolio")
    port.add_argument('--initial-capital', type=float, default=1_000_000,
                      help='Initial capital (default: 1000000)')
    port.add_argument('--max-positions', type=int, default=20,
                      help='Maximum number of positions (default: 20)')
    port.add_argument('--position-sizing', choices=['equal_weight', 'risk_based'],
                      default='equal_weight', help='Position sizing method (default: equal_weight)')

    # ── 交易成本 ──────────────────────────────────────────────────
    cost = parser.add_argument_group("Transaction Costs")
    cost.add_argument('--commission', type=float, default=0.0003,
                      help='Commission rate (default: 0.0003 = 0.03%%)')
    cost.add_argument('--stamp-tax', type=float, default=0.001,
                      help='Stamp tax rate (default: 0.001 = 0.1%%)')
    cost.add_argument('--slippage', type=float, default=0.001,
                      help='Slippage rate (default: 0.001 = 0.1%%)')

    # ── 指标数据库 ────────────────────────────────────────────────
    db = parser.add_argument_group("Indicator Database")
    db.add_argument(
        '--use-indicator-db',
        action='store_true',
        default=True,
        help='Use pre-computed indicator database for faster backtesting (default: True)'
    )
    db.add_argument(
        '--no-indicator-db',
        dest='use_indicator_db',
        action='store_false',
        help='Force CSV/real-time mode instead of indicator database'
    )
    db.add_argument(
        '--indicator-db-path',
        default=str(PROJECT_ROOT / 'data/indicators.duckdb'),
        help='Path to indicator database'
    )

    # ── Score 百分位过滤 ──────────────────────────────────────────
    sf = parser.add_argument_group("Score Filter")
    sf.add_argument(
        '--score-filter',
        action='store_true',
        default=True,
        help='Enable historical score percentile filter (only trade top signals)'
    )
    sf.add_argument(
        '--no-score-filter',
        dest='score_filter',
        action='store_false',
        help='Disable score filter'
    )
    sf.add_argument(
        '--score-percentile',
        type=float,
        default=60.0,
        metavar='PCT',
        help='Percentile threshold: only keep signals above this historical percentile '
             '(default: 60.0, i.e. top 40%%)'
    )
    sf.add_argument(
        '--score-min-history',
        type=int,
        default=20,
        metavar='N',
        help='Minimum score history samples before filter activates (default: 20)'
    )
    sf.add_argument(
        '--score-warmup-days',
        type=int,
        default=20,
        metavar='DAYS',
        help='Number of pre-start trading days used to warm up score history (default: 20)'
    )
    sf.add_argument(
        '--warmup-force-legacy',
        action='store_true',
        default=False,
        help='Force legacy (real-time) indicator calculation during warmup, '
             'ignoring indicator DB (default: True, safe when DB is incomplete)'
    )
    sf.add_argument(
        '--no-warmup-force-legacy',
        dest='warmup_force_legacy',
        action='store_false',
        help='Use indicator DB during warmup (only set when DB is complete)'
    )

    # ── 换仓 (Rotation) ───────────────────────────────────────────
    rot = parser.add_argument_group("Rotation")
    rot.add_argument(
        '--rotation',
        action='store_true',
        default=True,
        help='Enable rotation: replace losing positions with higher-scoring new signals'
    )
    rot.add_argument(
        '--no-rotation',
        dest='rotation',
        action='store_false',
        help='Disable rotation'
    )
    rot.add_argument(
        '--rotation-min-loss',
        type=float,
        default=0.05,
        metavar='PCT',
        help='Min unrealized loss to trigger rotation consideration (default: 0.05 = 5%%)'
    )
    rot.add_argument(
        '--rotation-max-per-day',
        type=int,
        default=2,
        metavar='N',
        help='Max rotation pairs per day (default: 2)'
    )
    rot.add_argument(
        '--rotation-score-ratio',
        type=float,
        default=1.2,
        metavar='X',
        help='New signal score must be >= old entry score × X (default: 1.2)'
    )
    rot.add_argument(
        '--rotation-score-improvement',
        type=float,
        default=10.0,
        metavar='PTS',
        help='New signal score must exceed old entry score by at least PTS (default: 10.0)'
    )
    rot.add_argument(
        '--rotation-no-score-policy',
        choices=['skip', 'allow', 'mean'],
        default='skip',
        help='How to handle positions with no entry score (default: skip)'
    )

    # ── 性能 ──────────────────────────────────────────────────────
    perf = parser.add_argument_group("Performance")
    perf.add_argument(
        '--workers',
        type=int,
        default=0,
        metavar='N',
        help='Parallel worker processes for stock screening (0 = auto-detect CPU count, default: 0)'
    )

    # ── 输出 ──────────────────────────────────────────────────────
    out = parser.add_argument_group("Output")
    out.add_argument('--save-results', metavar='PATH',
                     help='Save results to JSON file')
    out.add_argument('--quiet', action='store_true',
                     help='Suppress detailed engine logs (only show summary)')

    return parser


def print_config(args):
    print("=" * 80)
    print("BACKTEST CONFIGURATION")
    print("=" * 80)
    print(f"  Date Range       : {args.start} → {args.end}")
    print(f"  Initial Capital  : {args.initial_capital:,.0f}")
    print(f"  Max Positions    : {args.max_positions}")
    print(f"  Position Sizing  : {args.position_sizing}")
    print(f"  Sell Strategy    : {args.sell_strategy}")
    print(f"  Commission       : {args.commission*100:.3f}%")
    print(f"  Stamp Tax        : {args.stamp_tax*100:.3f}%")
    print(f"  Slippage         : {args.slippage*100:.3f}%")
    print(f"  Lookback Days    : {args.lookback_days}")
    print(f"  Indicator DB     : {'ON  → ' + args.indicator_db_path if args.use_indicator_db else 'OFF (real-time)'}")
    # Score filter
    if args.score_filter:
        print(f"  Score Filter     : ON  | percentile={args.score_percentile:.0f}, "
              f"min_history={args.score_min_history}, warmup={args.score_warmup_days}d, "
              f"force_legacy={'yes' if args.warmup_force_legacy else 'no'}")
    else:
        print(f"  Score Filter     : OFF")
    # Rotation
    if args.rotation:
        print(f"  Rotation         : ON  | min_loss={args.rotation_min_loss*100:.1f}%, "
              f"max/day={args.rotation_max_per_day}, "
              f"score_ratio={args.rotation_score_ratio}x, "
              f"score_improvement>={args.rotation_score_improvement}pts, "
              f"no_score={args.rotation_no_score_policy}")
    else:
        print(f"  Rotation         : OFF")
    print("=" * 80 + "\n")


def main():
    parser = build_parser()
    args = parser.parse_args()

    print_config(args)

    # ── 加载卖出策略配置 ──────────────────────────────────────────
    sell_strategy_config = load_sell_strategy_config(args.sell_strategy)

    # ── 指标数据库可用性检查 ──────────────────────────────────────
    if args.use_indicator_db:
        db_path = Path(args.indicator_db_path)
        if not db_path.exists():
            print(f"WARNING: Indicator DB not found at {db_path}")
            print(f"         Falling back to real-time indicator calculation.")
            print(f"         Run 'python scripts/init_indicator_db.py' or 'python scripts/migrate_to_duckdb.py' to create the DB.\n")
            args.use_indicator_db = False

    # ── 初始化引擎 ────────────────────────────────────────────────
    engine = BacktestEngine(
        data_dir=args.data_dir,
        buy_config_path=args.buy_config,
        sell_strategy_config=sell_strategy_config,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.initial_capital,
        max_positions=args.max_positions,
        position_sizing=args.position_sizing,
        commission_rate=args.commission,
        stamp_tax_rate=args.stamp_tax,
        slippage_rate=args.slippage,
        # 指标数据库
        use_indicator_db=args.use_indicator_db,
        indicator_db_path=args.indicator_db_path,
        # Score 过滤
        score_filter_enabled=args.score_filter,
        score_percentile_threshold=args.score_percentile,
        score_min_history=args.score_min_history,
        score_warmup_lookback_days=args.score_warmup_days,
        # 换仓
        rotation_enabled=args.rotation,
        rotation_min_stop_threshold=args.rotation_min_loss,
        rotation_max_per_day=args.rotation_max_per_day,
        rotation_score_ratio=args.rotation_score_ratio,
        rotation_min_score_improvement=args.rotation_score_improvement,
        rotation_no_score_policy=args.rotation_no_score_policy,
        # 并行
        parallel_workers=args.workers,
    )

    # ── 加载数据 ──────────────────────────────────────────────────
    print("Loading data...")
    engine.load_data(lookback_days=args.lookback_days)

    if not engine.market_data:
        print("\nERROR: No data loaded. Please run fetch_kline.py first.")
        sys.exit(1)
    print(f"Loaded {len(engine.market_data)} stocks\n")

    # ── 加载选股器 ────────────────────────────────────────────────
    print("Loading buy selectors...")
    engine.load_buy_selectors()

    if not engine.buy_selectors:
        print("\nERROR: No buy selectors loaded. Please check configs.json.")
        sys.exit(1)
    print(f"Loaded {len(engine.buy_selectors)} buy selector(s)\n")

    # ── 加载卖出策略 ──────────────────────────────────────────────
    print("Loading sell strategy...")
    engine.load_sell_strategy()
    print(f"Loaded: {sell_strategy_config.get('name', args.sell_strategy)}\n")

    # ── Score 预热 ────────────────────────────────────────────────
    if args.score_filter or args.rotation:
        engine.warmup_score_history(force_legacy=args.warmup_force_legacy)

    # ── 运行回测 ──────────────────────────────────────────────────
    print("=" * 80)
    print("RUNNING BACKTEST")
    print("=" * 80 + "\n")

    if args.quiet:
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    try:
        engine.run()
    finally:
        if args.quiet:
            sys.stdout = old_stdout

    # ── 结果分析 ──────────────────────────────────────────────────
    results = engine.get_results()

    equity_df = engine.portfolio.get_equity_curve_df()
    trades_df = engine.portfolio.get_trades_df()

    if not equity_df.empty:
        analyzer = PerformanceAnalyzer(
            equity_curve=equity_df,
            trades=trades_df,
            initial_capital=args.initial_capital
        )
        analyzer.print_report()
        results['performance'] = analyzer.analyze()
    else:
        print("\nNo equity curve data generated.")

    # 换仓摘要
    rotation_summary = results.get('rotation_summary')
    if rotation_summary:
        print("\n" + "=" * 80)
        print("ROTATION SUMMARY")
        print("=" * 80)
        print(f"  Total rotations    : {rotation_summary['total_rotations']}")
        print(f"  Avg exit P&L       : {rotation_summary['avg_exit_pnl_pct']:+.2f}%")
        print(f"  Avg score gain     : +{rotation_summary['avg_score_improvement']:.1f} pts")

    # ── 元数据 ────────────────────────────────────────────────────
    results['metadata'] = {
        'start_date': args.start,
        'end_date': args.end,
        'initial_capital': args.initial_capital,
        'max_positions': args.max_positions,
        'position_sizing': args.position_sizing,
        'sell_strategy': args.sell_strategy,
        'commission_rate': args.commission,
        'stamp_tax_rate': args.stamp_tax,
        'slippage_rate': args.slippage,
        'use_indicator_db': args.use_indicator_db,
        'score_filter_enabled': args.score_filter,
        'score_percentile_threshold': args.score_percentile if args.score_filter else None,
        'rotation_enabled': args.rotation,
        'num_stocks': len(engine.market_data),
        'num_buy_selectors': len(engine.buy_selectors),
        'run_timestamp': datetime.now().isoformat(),
    }

    # ── 保存结果 ──────────────────────────────────────────────────
    if args.save_results:
        save_results(results, args.save_results)

        log_path = Path(args.save_results).with_suffix('.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(engine.logs))
        print(f"Logs saved to: {log_path}")

    print("\nBacktest complete!")


if __name__ == "__main__":
    main()