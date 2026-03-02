#!/usr/bin/env python3
"""
全面的数据一致性测试

验证所有选股器在数据库模式和传统模式下返回相同的结果。

Usage:
    python scripts/test_all_selectors_consistency.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd

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
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    return [s for s in config.get('selectors', []) if s.get('activate', False)]


def test_selector_consistency(
    selector_class,
    selector_name: str,
    params: Dict,
    test_code: str,
    test_date: pd.Timestamp,
    csv_data: pd.DataFrame,
    db_data: pd.DataFrame,
    indicator_store: IndicatorStore
) -> Tuple[bool, str]:
    """
    测试单个选股器的一致性

    Returns:
        (success, message)
    """
    try:
        # 创建传统模式选股器
        selector_legacy = selector_class(**params)

        # 创建数据库模式选股器
        db_params = params.copy()
        db_params['indicator_store'] = indicator_store
        selector_db = selector_class(**db_params)

        # 过滤数据到测试日期
        csv_hist = csv_data[csv_data['date'] <= test_date].tail(200)
        db_hist = db_data[db_data['date'] <= test_date].tail(200)

        # 测试过滤逻辑
        result_legacy = selector_legacy._passes_filters(csv_hist)
        result_db = selector_db._passes_filters(db_hist)

        if result_legacy == result_db:
            return (True, f"✅ {selector_name}: Consistent (result={result_legacy})")
        else:
            return (False, f"❌ {selector_name}: INCONSISTENT! Legacy={result_legacy}, DB={result_db}")

    except Exception as e:
        return (False, f"❌ {selector_name}: ERROR - {str(e)}")


def main():
    print("="*80)
    print("  All Selectors Consistency Test")
    print("="*80)
    print()

    # 初始化 IndicatorStore
    db_path = "./data/indicators.db"
    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}")
        print("   Please run: python scripts/precompute_indicators.py --mode full --force")
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

    # 读取 CSV 数据（传统模式）
    csv_file = Path(f"./data/{test_code}.csv")
    if not csv_file.exists():
        print(f"❌ CSV file not found: {csv_file}")
        sys.exit(1)

    csv_data = pd.read_csv(csv_file)
    csv_data['date'] = pd.to_datetime(csv_data['date'])

    # 读取数据库数据
    db_data = store.get_indicators(test_code, end_date=test_date.strftime('%Y-%m-%d'))

    print(f"CSV data: {len(csv_data)} rows")
    print(f"DB data: {len(db_data)} rows")
    print()

    # 加载选股器配置
    selector_configs = load_selector_configs()
    print(f"Testing {len(selector_configs)} selectors...")
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

    # 测试所有选股器
    results = []
    for config in selector_configs:
        class_name = config['class']
        alias = config.get('alias', class_name)
        params = config.get('params', {})

        # 跳过不支持的选股器
        if class_name not in selector_classes:
            print(f"⚠️  {alias}: Class not found, skipping")
            continue

        selector_class = selector_classes[class_name]

        # 测试一致性
        success, message = test_selector_consistency(
            selector_class=selector_class,
            selector_name=alias,
            params=params,
            test_code=test_code,
            test_date=test_date,
            csv_data=csv_data,
            db_data=db_data,
            indicator_store=store
        )

        results.append((success, message))
        print(message)

    print()
    print("="*80)
    print("  Test Summary")
    print("="*80)

    passed = sum(1 for s, _ in results if s)
    failed = len(results) - passed

    print(f"✅ Passed: {passed}/{len(results)}")
    print(f"❌ Failed: {failed}/{len(results)}")
    print()

    if failed == 0:
        print("🎉 All selectors are consistent!")
        print()
        print("Database mode is production-ready!")
    else:
        print("⚠️  Some selectors have inconsistencies.")
        print("   Please review the failed selectors above.")
        sys.exit(1)

    # 关闭数据库连接
    store.close()


if __name__ == "__main__":
    main()
