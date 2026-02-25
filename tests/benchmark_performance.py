#!/usr/bin/env python3
"""
性能基准测试

对比数据库模式和传统模式的性能差异。

Usage:
    python scripts/benchmark_performance.py
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Selector import (
    BBIKDJSelector,
    SuperB1Selector,
    BBIShortLongSelector,
    PeakKDJSelector,
    MA60CrossVolumeWaveSelector,
    BigBullishVolumeSelector,
)
from backtest.indicator_store import IndicatorStore


def load_selector_configs() -> List[Dict]:
    """加载选股器配置"""
    config_path = Path("./configs.json")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return [s for s in config.get('selectors', []) if s.get('activate', False)]


def benchmark_selector(
    selector_class,
    selector_name: str,
    params: Dict,
    test_code: str,
    test_date: pd.Timestamp,
    csv_data: pd.DataFrame,
    db_data: pd.DataFrame,
    indicator_store: IndicatorStore,
    iterations: int = 100
) -> Tuple[float, float, float]:
    """
    对单个选股器进行性能基准测试

    Returns:
        (legacy_time, db_time, speedup)
    """
    # 准备数据
    csv_hist = csv_data[csv_data['date'] <= test_date].tail(200)
    db_hist = db_data[db_data['date'] <= test_date].tail(200)

    # 测试传统模式
    selector_legacy = selector_class(**params)
    start_time = time.time()
    for _ in range(iterations):
        selector_legacy._passes_filters(csv_hist)
    legacy_time = time.time() - start_time

    # 测试数据库模式
    db_params = params.copy()
    db_params['indicator_store'] = indicator_store
    selector_db = selector_class(**db_params)
    start_time = time.time()
    for _ in range(iterations):
        selector_db._passes_filters(db_hist)
    db_time = time.time() - start_time

    # 计算加速比
    speedup = legacy_time / db_time if db_time > 0 else 0

    return (legacy_time, db_time, speedup)


def main():
    print("="*80)
    print("  Performance Benchmark")
    print("="*80)
    print()

    # 初始化 IndicatorStore
    db_path = "./data/indicators.db"
    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}")
        sys.exit(1)

    store = IndicatorStore(db_path)
    stats = store.get_database_stats()
    print(f"Database: {stats['total_stocks']} stocks, {stats['total_rows']} rows")
    print()

    # 获取测试股票
    codes = store.get_all_codes()
    if not codes:
        print("❌ No data in database.")
        sys.exit(1)

    test_code = codes[0]
    print(f"Test stock: {test_code}")

    # 设置测试日期
    start_date, end_date = store.get_date_range(test_code)
    test_date = pd.to_datetime(end_date)
    print(f"Test date: {test_date.strftime('%Y-%m-%d')}")
    print()

    # 读取数据
    csv_file = Path(f"./data/{test_code}.csv")
    csv_data = pd.read_csv(csv_file)
    csv_data['date'] = pd.to_datetime(csv_data['date'])
    db_data = store.get_indicators(test_code, end_date=test_date.strftime('%Y-%m-%d'))

    # 加载选股器配置
    selector_configs = load_selector_configs()
    print(f"Benchmarking {len(selector_configs)} selectors (100 iterations each)...")
    print("="*80)
    print()

    # 选股器类映射
    selector_classes = {
        'BBIKDJSelector': BBIKDJSelector,
        'SuperB1Selector': SuperB1Selector,
        'BBIShortLongSelector': BBIShortLongSelector,
        'PeakKDJSelector': PeakKDJSelector,
        'MA60CrossVolumeWaveSelector': MA60CrossVolumeWaveSelector,
        'BigBullishVolumeSelector': BigBullishVolumeSelector,
    }

    # 性能测试
    results = []
    print(f"{'Selector':<25} {'Legacy (s)':<12} {'DB (s)':<12} {'Speedup':<12}")
    print("-" * 80)

    for config in selector_configs:
        class_name = config['class']
        alias = config.get('alias', class_name)
        params = config.get('params', {})

        if class_name not in selector_classes:
            continue

        selector_class = selector_classes[class_name]

        try:
            legacy_time, db_time, speedup = benchmark_selector(
                selector_class=selector_class,
                selector_name=alias,
                params=params,
                test_code=test_code,
                test_date=test_date,
                csv_data=csv_data,
                db_data=db_data,
                indicator_store=store,
                iterations=100
            )

            results.append((alias, legacy_time, db_time, speedup))
            print(f"{alias:<25} {legacy_time:>10.3f}s  {db_time:>10.3f}s  {speedup:>10.1f}x")

        except Exception as e:
            print(f"{alias:<25} ERROR: {str(e)}")

    print()
    print("="*80)
    print("  Summary")
    print("="*80)

    if results:
        # 计算总体统计
        total_legacy = sum(r[1] for r in results)
        total_db = sum(r[2] for r in results)
        avg_speedup = np.mean([r[3] for r in results])
        max_speedup = max([r[3] for r in results])
        min_speedup = min([r[3] for r in results])

        print(f"Total Legacy Time:  {total_legacy:.3f}s")
        print(f"Total DB Time:      {total_db:.3f}s")
        print(f"Overall Speedup:    {total_legacy / total_db:.1f}x")
        print()
        print(f"Average Speedup:    {avg_speedup:.1f}x")
        print(f"Max Speedup:        {max_speedup:.1f}x")
        print(f"Min Speedup:        {min_speedup:.1f}x")
        print()

        # 性能提升估算
        print("="*80)
        print("  Performance Improvement Estimation")
        print("="*80)
        print()
        print(f"For a typical backtest scenario:")
        print(f"  - Stock universe: 5000 stocks")
        print(f"  - Backtest period: 6 months (~120 trading days)")
        print(f"  - Selectors: {len(results)}")
        print()
        print(f"Estimated legacy mode time: {total_legacy * 5000 * 120 / 100:.0f}s = {total_legacy * 5000 * 120 / 100 / 60:.1f} minutes")
        print(f"Estimated DB mode time:     {total_db * 5000 * 120 / 100:.0f}s = {total_db * 5000 * 120 / 100 / 60:.1f} minutes")
        print()
        print(f"🚀 Expected speedup: {total_legacy / total_db:.1f}x faster!")

    # 关闭数据库连接
    store.close()


if __name__ == "__main__":
    main()
