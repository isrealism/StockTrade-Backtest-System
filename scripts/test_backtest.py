#!/usr/bin/env python
"""
Simple backtest runner for testing Phase 1 implementation.

Usage:
    python scripts/test_backtest.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.engine import BacktestEngine
import json

def load_sell_strategy_by_name(strategy_name: str, config_path: str = "./configs/sell_strategies.json"):
    """从配置文件中加载指定策略"""
    
    # 读取 JSON 文件
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)
    
    # 获取 strategies 字段
    strategies = config_data.get('strategies', {})
    
    # 检查策略是否存在
    if strategy_name not in strategies:
        available = list(strategies.keys())
        raise ValueError(f"策略 '{strategy_name}' 不存在。可用策略: {', '.join(available)}")
    
    # 获取策略配置
    strategy_config = strategies[strategy_name]
    
    # 返回策略配置
    if 'strategies' in strategy_config:
        # 组合策略（如 conservative_trailing）
        return strategy_config['strategies']
    else:
        # 单一策略（如 hold_forever）
        return {
            'class': strategy_config.get('class'),
            'params': strategy_config.get('params', {})
        }

def main():
    """Run simple backtest test."""
    print("="*80)
    print("SIMPLE BACKTEST TEST")
    print("="*80)

    # Configuration
    data_dir = "./data"
    buy_config_path = "./configs.json"
    start_date = "2025-01-01"
    end_date = "2025-01-10"
    initial_capital = 1000000

    # ============ 指定策略名称 ============
    strategy_name = "conservative_trailing"  # ← 修改这里选择不同策略

    # 加载策略配置
    sell_strategy_config = load_sell_strategy_by_name(
    strategy_name, 
    "./configs/sell_strategies.json"
    )
    
    # Initialize engine
    engine = BacktestEngine(
        data_dir=data_dir,
        buy_config_path=buy_config_path,
        sell_strategy_config=sell_strategy_config,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        max_positions=20,
        position_sizing="equal_weight"
    )

    # Load data (all stocks)
    engine.load_data()

    if len(engine.market_data) == 0:
        print("\nERROR: No data loaded. Please run fetch_kline.py first.")
        return

    # Load buy selectors
    engine.load_buy_selectors()

    if len(engine.buy_selectors) == 0:
        print("\nERROR: No buy selectors loaded. Please check configs.json.")
        return

    # Load sell strategy
    engine.load_sell_strategy()

    # Run backtest
    print("\nRunning backtest...")
    engine.run()

    # Get results
    results = engine.get_results()

    # Print summary
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)
    print(f"Initial Capital: {initial_capital:,.0f}")
    print(f"Final Value:     {results['final_value']:,.0f}")
    print(f"Total Return:    {results['total_return']*100:.2f}%")
    print(f"Total Trades:    {results['num_trades']}")
    print(f"Open Positions:  {results['num_positions']}")

    # Print trade summary if trades exist
    if results['num_trades'] > 0:
        print("\nTrade Summary:")
        trades = results['trades']
        winning_trades = [t for t in trades if t['net_pnl'] > 0]
        losing_trades = [t for t in trades if t['net_pnl'] < 0]

        print(f"  Winning trades: {len(winning_trades)}")
        print(f"  Losing trades:  {len(losing_trades)}")

        if len(trades) > 0:
            win_rate = len(winning_trades) / len(trades)
            print(f"  Win rate:       {win_rate*100:.2f}%")

            avg_win = sum(t['net_pnl'] for t in winning_trades) / len(winning_trades) if winning_trades else 0
            avg_loss = sum(t['net_pnl'] for t in losing_trades) / len(losing_trades) if losing_trades else 0
            print(f"  Avg win:        {avg_win:,.0f}")
            print(f"  Avg loss:       {avg_loss:,.0f}")

    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
