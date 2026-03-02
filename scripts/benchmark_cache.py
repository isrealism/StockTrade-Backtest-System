#!/usr/bin/env python3
"""
数据准备缓存性能基准测试

对比：
1. 原始模式（每天重复过滤）
2. 缓存模式（增量更新）

测量：
- 总耗时
- 每次调用耗时
- 内存占用
- 加速比
"""

import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
import time
import tracemalloc

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def create_realistic_test_data(num_stocks=1000, num_days=120):
    """
    创建接近真实场景的测试数据

    Args:
        num_stocks: 股票数量（默认 1000）
        num_days: 天数（默认 120，约半年回测）

    Returns:
        Dict[股票代码, DataFrame]
    """
    print(f"生成测试数据: {num_stocks} 只股票 × {num_days} 天...")

    dates = pd.date_range('2025-01-01', periods=num_days, freq='D')

    test_data = {}
    for i in range(num_stocks):
        code = f"{i:06d}"
        test_data[code] = pd.DataFrame({
            'date': dates,
            'open': 100 + i * 0.01,
            'close': 100 + i * 0.01,
            'high': 101 + i * 0.01,
            'low': 99 + i * 0.01,
            'volume': [1000000] * len(dates),
            # Simulate indicator columns (as if from database)
            'kdj_k': 50.0,
            'kdj_d': 50.0,
            'kdj_j': 50.0,
            'ma60': 100.0,
            'bbi': 100.0,
            'dif': 0.0
        })

    print(f"✅ 测试数据生成完成")
    return test_data


def benchmark_original_mode(market_data, trading_dates):
    """
    基准测试：原始模式（每天重复过滤）

    模拟原始代码：
    for date in trading_dates:
        for code, df in market_data.items():
            df_up_to_date = df[df['date'] <= date].copy()
    """
    print("\n" + "="*80)
    print("基准测试 1: 原始模式（每天重复过滤 + copy）")
    print("="*80)

    tracemalloc.start()
    start_time = time.time()

    total_operations = 0
    for date in trading_dates:
        data_for_selectors = {}
        for code, df in market_data.items():
            df_up_to_date = df[df['date'] <= date].copy()
            if len(df_up_to_date) > 0:
                data_for_selectors[code] = df_up_to_date
            total_operations += 1

    end_time = time.time()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    elapsed = end_time - start_time
    ops_per_second = total_operations / elapsed if elapsed > 0 else 0

    print(f"  总耗时: {elapsed:.2f} 秒")
    print(f"  总操作数: {total_operations:,} (股票 × 交易日)")
    print(f"  操作速度: {ops_per_second:,.0f} ops/s")
    print(f"  平均每天: {elapsed / len(trading_dates) * 1000:.2f} ms")
    print(f"  内存峰值: {peak / 1024 / 1024:.2f} MB")

    return {
        'mode': 'original',
        'elapsed': elapsed,
        'total_operations': total_operations,
        'ops_per_second': ops_per_second,
        'avg_per_day_ms': elapsed / len(trading_dates) * 1000,
        'peak_memory_mb': peak / 1024 / 1024
    }


def benchmark_cache_mode(market_data, trading_dates):
    """
    基准测试：缓存模式（增量更新）

    使用新实现的 _get_data_up_to_date() 方法
    """
    print("\n" + "="*80)
    print("基准测试 2: 缓存模式（增量更新）")
    print("="*80)

    from backtest.engine import BacktestEngine

    # Create engine
    engine = BacktestEngine(
        data_dir="./data",
        buy_config_path="./configs.json",
        sell_strategy_config={},
        start_date=trading_dates[0].strftime('%Y-%m-%d'),
        end_date=trading_dates[-1].strftime('%Y-%m-%d'),
        initial_capital=1000000
    )

    engine.market_data = market_data

    tracemalloc.start()
    start_time = time.time()

    total_operations = 0
    for date in trading_dates:
        data_for_selectors = engine._get_data_up_to_date(date)
        total_operations += len(market_data)

    end_time = time.time()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    elapsed = end_time - start_time
    ops_per_second = total_operations / elapsed if elapsed > 0 else 0

    print(f"  总耗时: {elapsed:.2f} 秒")
    print(f"  总操作数: {total_operations:,} (股票 × 交易日)")
    print(f"  操作速度: {ops_per_second:,.0f} ops/s")
    print(f"  平均每天: {elapsed / len(trading_dates) * 1000:.2f} ms")
    print(f"  内存峰值: {peak / 1024 / 1024:.2f} MB")

    return {
        'mode': 'cache',
        'elapsed': elapsed,
        'total_operations': total_operations,
        'ops_per_second': ops_per_second,
        'avg_per_day_ms': elapsed / len(trading_dates) * 1000,
        'peak_memory_mb': peak / 1024 / 1024
    }


def print_comparison(original_result, cache_result):
    """打印对比结果"""
    print("\n" + "="*80)
    print("性能对比总结")
    print("="*80)

    speedup = original_result['elapsed'] / cache_result['elapsed']
    time_saved = original_result['elapsed'] - cache_result['elapsed']
    time_saved_pct = (time_saved / original_result['elapsed']) * 100

    print(f"\n📊 耗时对比:")
    print(f"  原始模式: {original_result['elapsed']:.2f} 秒")
    print(f"  缓存模式: {cache_result['elapsed']:.2f} 秒")
    print(f"  节省时间: {time_saved:.2f} 秒 ({time_saved_pct:.1f}%)")
    print(f"  加速比: {speedup:.2f}x")

    print(f"\n📈 操作速度对比:")
    print(f"  原始模式: {original_result['ops_per_second']:,.0f} ops/s")
    print(f"  缓存模式: {cache_result['ops_per_second']:,.0f} ops/s")

    print(f"\n⏱️  平均每天耗时:")
    print(f"  原始模式: {original_result['avg_per_day_ms']:.2f} ms")
    print(f"  缓存模式: {cache_result['avg_per_day_ms']:.2f} ms")
    print(f"  节省: {original_result['avg_per_day_ms'] - cache_result['avg_per_day_ms']:.2f} ms/天")

    print(f"\n💾 内存占用:")
    print(f"  原始模式: {original_result['peak_memory_mb']:.2f} MB")
    print(f"  缓存模式: {cache_result['peak_memory_mb']:.2f} MB")
    memory_diff = cache_result['peak_memory_mb'] - original_result['peak_memory_mb']
    print(f"  差异: {memory_diff:+.2f} MB")


def extrapolate_to_production(speedup, time_saved, num_stocks_test, num_days_test):
    """推算生产环境性能提升"""
    print("\n" + "="*80)
    print("生产环境性能预估")
    print("="*80)

    # 生产环境配置
    prod_stocks = 5000
    prod_days = 120

    # 原始模式预估耗时（线性增长）
    scale_factor = (prod_stocks / num_stocks_test) * (prod_days / num_days_test)
    original_prod_time = time_saved / (speedup - 1) * scale_factor  # 反推原始耗时

    # 缓存模式预估耗时
    cache_prod_time = original_prod_time / speedup

    # 节省时间
    time_saved_prod = original_prod_time - cache_prod_time

    print(f"\n场景: {prod_stocks} 只股票 × {prod_days} 天回测")
    print(f"\n预估耗时:")
    print(f"  原始模式: {original_prod_time / 60:.1f} 分钟 ({original_prod_time:.0f} 秒)")
    print(f"  缓存模式: {cache_prod_time / 60:.1f} 分钟 ({cache_prod_time:.0f} 秒)")
    print(f"  节省时间: {time_saved_prod / 60:.1f} 分钟 ({time_saved_prod:.0f} 秒)")
    print(f"  加速比: {speedup:.2f}x")

    print(f"\n✨ 预期性能提升:")
    if time_saved_prod > 3600:
        print(f"  每次回测节省约 {time_saved_prod / 3600:.1f} 小时")
    elif time_saved_prod > 60:
        print(f"  每次回测节省约 {time_saved_prod / 60:.0f} 分钟")
    else:
        print(f"  每次回测节省约 {time_saved_prod:.0f} 秒")


def run_benchmark(num_stocks=1000, num_days=120):
    """
    运行完整基准测试

    Args:
        num_stocks: 测试股票数量
        num_days: 测试天数
    """
    print("\n" + "="*80)
    print("数据准备缓存性能基准测试")
    print("="*80)
    print(f"\n配置:")
    print(f"  股票数量: {num_stocks:,}")
    print(f"  交易天数: {num_days}")
    print(f"  总操作数: {num_stocks * num_days:,}")

    # 生成测试数据
    market_data = create_realistic_test_data(num_stocks, num_days)
    trading_dates = [
        datetime(2025, 1, 1) + timedelta(days=i)
        for i in range(num_days)
    ]

    # 运行基准测试
    original_result = benchmark_original_mode(market_data, trading_dates)
    cache_result = benchmark_cache_mode(market_data, trading_dates)

    # 打印对比
    print_comparison(original_result, cache_result)

    # 推算生产环境
    extrapolate_to_production(
        speedup=original_result['elapsed'] / cache_result['elapsed'],
        time_saved=original_result['elapsed'] - cache_result['elapsed'],
        num_stocks_test=num_stocks,
        num_days_test=num_days
    )

    print("\n" + "="*80)
    print("✅ 基准测试完成")
    print("="*80)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Data cache performance benchmark')
    parser.add_argument('--stocks', type=int, default=1000, help='Number of stocks (default: 1000)')
    parser.add_argument('--days', type=int, default=120, help='Number of trading days (default: 120)')

    args = parser.parse_args()

    run_benchmark(num_stocks=args.stocks, num_days=args.days)
