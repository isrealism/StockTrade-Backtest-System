#!/usr/bin/env python3
"""
测试选股器数据库适配

验证 BBIKDJSelector 在数据库模式和传统模式下的一致性。
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Selector import BBIKDJSelector
from backtest.indicator_store import IndicatorStore


def test_selector_consistency():
    """测试数据库模式和传统模式的一致性"""

    print("="*60)
    print("  Testing BBIKDJSelector Database Adaptation")
    print("="*60)
    print()

    # 初始化 IndicatorStore
    store = IndicatorStore("./data/indicators.db")
    stats = store.get_database_stats()
    print(f"Database: {stats['total_stocks']} stocks, {stats['total_rows']} rows")
    print()

    # 获取测试股票
    codes = store.get_all_codes()
    if not codes:
        print("❌ No data in database. Please run precompute_indicators.py first.")
        return

    test_code = codes[0]
    print(f"Testing with stock: {test_code}")
    print()

    # 设置测试日期（使用最后一个日期）
    start_date, end_date = store.get_date_range(test_code)
    test_date = pd.to_datetime(end_date)
    print(f"Test date: {test_date.strftime('%Y-%m-%d')}")
    print()

    # ========== 测试 1: 传统模式（从 CSV 读取） ==========
    print("Test 1: Legacy Mode (CSV + Real-time Computation)")
    print("-" * 60)

    # 读取 CSV 数据
    csv_file = Path(f"./data/{test_code}.csv")
    if not csv_file.exists():
        print(f"❌ CSV file not found: {csv_file}")
        return

    df_csv = pd.read_csv(csv_file)
    df_csv['date'] = pd.to_datetime(df_csv['date'])
    df_csv = df_csv[df_csv['date'] <= test_date].tail(150)

    # 创建传统模式选股器
    selector_legacy = BBIKDJSelector(
        j_threshold=-5,
        bbi_min_window=90,
        max_window=90,
        indicator_store=None  # 不使用数据库
    )

    # 测试过滤
    result_legacy = selector_legacy._passes_filters(df_csv)
    print(f"Result (legacy): {result_legacy}")
    print()

    # ========== 测试 2: 数据库模式 ==========
    print("Test 2: Database Mode (Pre-computed Indicators)")
    print("-" * 60)

    # 从数据库读取数据
    df_db = store.get_indicators(test_code, end_date=test_date.strftime('%Y-%m-%d'))
    df_db = df_db.tail(150)

    # 创建数据库模式选股器
    selector_db = BBIKDJSelector(
        j_threshold=-5,
        bbi_min_window=90,
        max_window=90,
        indicator_store=store
    )

    # 测试过滤
    result_db = selector_db._passes_filters(df_db)
    print(f"Result (database): {result_db}")
    print()

    # ========== 比较结果 ==========
    print("="*60)
    print("  Comparison")
    print("="*60)
    if result_legacy == result_db:
        print("✅ PASS: Both modes return the same result!")
        print(f"   Result: {result_legacy}")
    else:
        print("❌ FAIL: Results differ!")
        print(f"   Legacy: {result_legacy}")
        print(f"   Database: {result_db}")
    print()

    # ========== 性能比较 ==========
    print("="*60)
    print("  Performance Comparison")
    print("="*60)

    import time

    # 测试传统模式性能
    start_time = time.time()
    for _ in range(100):
        selector_legacy._passes_filters(df_csv)
    legacy_time = time.time() - start_time

    # 测试数据库模式性能
    start_time = time.time()
    for _ in range(100):
        selector_db._passes_filters(df_db)
    db_time = time.time() - start_time

    print(f"Legacy mode (100 iterations): {legacy_time:.3f}s")
    print(f"Database mode (100 iterations): {db_time:.3f}s")
    print(f"Speedup: {legacy_time / db_time:.1f}x faster")
    print()

    # 关闭数据库连接
    store.close()

    print("="*60)
    print("✅ Test completed!")
    print("="*60)


if __name__ == "__main__":
    test_selector_consistency()
