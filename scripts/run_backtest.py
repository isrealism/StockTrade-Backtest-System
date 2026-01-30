#!/usr/bin/env python
"""
Comprehensive backtest runner for Z's Trading Strategies.

Usage:
    # Run with default settings
    python scripts/run_backtest.py

    # Specify sell strategy
    python scripts/run_backtest.py --sell-strategy conservative_trailing

    # Custom date range
    python scripts/run_backtest.py --start 2023-01-01 --end 2024-12-31

    # Save results to file
    python scripts/run_backtest.py --save-results ./backtest_results/my_test.json

Example:
    python scripts/run_backtest.py \\
        --start 2024-01-01 \\
        --end 2024-12-31 \\
        --sell-strategy conservative_trailing \\
        --initial-capital 1000000 \\
        --max-positions 10 \\
        --save-results ./backtest_results/conservative_2024.json
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


def load_sell_strategy_config(strategy_name: str) -> dict:
    """
    Load sell strategy configuration from configs/sell_strategies.json.

    Args:
        strategy_name: Name of strategy (e.g., "conservative_trailing")

    Returns:
        Strategy configuration dict
    """
    config_path = Path("./configs/sell_strategies.json")

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

    # Convert any non-serializable objects
    def json_serializer(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=json_serializer, ensure_ascii=False)

    print(f"\nResults saved to: {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run backtest for Z's Trading Strategies",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Data and date range
    parser.add_argument(
        '--data-dir',
        default='./data',
        help='Directory with historical K-line data (default: ./data)'
    )
    parser.add_argument(
        '--start',
        default='2024-01-01',
        help='Start date (YYYY-MM-DD, default: 2024-01-01)'
    )
    parser.add_argument(
        '--end',
        default='2024-12-31',
        help='End date (YYYY-MM-DD, default: 2024-12-31)'
    )

    # Strategy configuration
    parser.add_argument(
        '--buy-config',
        default='./configs.json',
        help='Buy strategies configuration file (default: ./configs.json)'
    )
    parser.add_argument(
        '--sell-strategy',
        default='conservative_trailing',
        help='Sell strategy name from sell_strategies.json (default: conservative_trailing)'
    )

    # Portfolio parameters
    parser.add_argument(
        '--initial-capital',
        type=float,
        default=1000000,
        help='Initial capital (default: 1000000)'
    )
    parser.add_argument(
        '--max-positions',
        type=int,
        default=10,
        help='Maximum number of positions (default: 10)'
    )
    parser.add_argument(
        '--position-sizing',
        choices=['equal_weight', 'risk_based'],
        default='equal_weight',
        help='Position sizing method (default: equal_weight)'
    )

    # Transaction costs
    parser.add_argument(
        '--commission',
        type=float,
        default=0.0003,
        help='Commission rate (default: 0.0003 = 0.03%%)'
    )
    parser.add_argument(
        '--stamp-tax',
        type=float,
        default=0.001,
        help='Stamp tax rate (default: 0.001 = 0.1%%)'
    )
    parser.add_argument(
        '--slippage',
        type=float,
        default=0.001,
        help='Slippage rate (default: 0.001 = 0.1%%)'
    )

    # Output
    parser.add_argument(
        '--save-results',
        help='Save results to JSON file (e.g., ./backtest_results/my_test.json)'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress detailed output (only show summary)'
    )

    args = parser.parse_args()

    # Print configuration
    print("="*80)
    print("BACKTEST CONFIGURATION")
    print("="*80)
    print(f"Date Range:        {args.start} to {args.end}")
    print(f"Initial Capital:   {args.initial_capital:,.0f}")
    print(f"Max Positions:     {args.max_positions}")
    print(f"Position Sizing:   {args.position_sizing}")
    print(f"Sell Strategy:     {args.sell_strategy}")
    print(f"Commission:        {args.commission*100:.3f}%")
    print(f"Stamp Tax:         {args.stamp_tax*100:.3f}%")
    print(f"Slippage:          {args.slippage*100:.3f}%")
    print("="*80 + "\n")

    # Load sell strategy configuration
    sell_strategy_config = load_sell_strategy_config(args.sell_strategy)

    # Initialize engine
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
        slippage_rate=args.slippage
    )

    # Load data
    print("Loading data...")
    engine.load_data()

    if len(engine.market_data) == 0:
        print("\nERROR: No data loaded. Please run fetch_kline.py first.")
        sys.exit(1)

    print(f"Loaded {len(engine.market_data)} stocks")

    # Load buy selectors
    print("Loading buy selectors...")
    engine.load_buy_selectors()

    if len(engine.buy_selectors) == 0:
        print("\nERROR: No buy selectors loaded. Please check configs.json.")
        sys.exit(1)

    print(f"Loaded {len(engine.buy_selectors)} buy selectors")

    # Load sell strategy
    print("Loading sell strategy...")
    engine.load_sell_strategy()
    print(f"Loaded: {sell_strategy_config.get('name', 'Unknown')}")

    # Run backtest
    print("\n" + "="*80)
    print("RUNNING BACKTEST")
    print("="*80 + "\n")

    if args.quiet:
        # Redirect output to suppress detailed logs
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    try:
        engine.run()
    finally:
        if args.quiet:
            sys.stdout = old_stdout

    # Get results
    results = engine.get_results()

    # Analyze performance
    equity_df = engine.portfolio.get_equity_curve_df()
    trades_df = engine.portfolio.get_trades_df()

    if len(equity_df) > 0:
        analyzer = PerformanceAnalyzer(
            equity_curve=equity_df,
            trades=trades_df,
            initial_capital=args.initial_capital
        )

        # Print report
        analyzer.print_report()

        # Add full analysis to results
        results['performance'] = analyzer.analyze()

    else:
        print("\nNo equity curve data generated.")

    # Add metadata
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
        'num_stocks': len(engine.market_data),
        'num_buy_selectors': len(engine.buy_selectors),
        'run_timestamp': datetime.now().isoformat()
    }

    # Save results if requested
    if args.save_results:
        save_results(results, args.save_results)

        # Save logs to .log file (same name as json result)
        log_path = Path(args.save_results).with_suffix('.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(engine.logs))
        print(f"Logs saved to: {log_path}")

    print("\nBacktest complete!")


if __name__ == "__main__":
    main()
