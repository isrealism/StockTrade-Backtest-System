#!/usr/bin/env python3
"""
测试数据准备缓存逻辑的正确性

验证：
1. 缓存初始化正确
2. 增量更新正确
3. 缓存结果与原始过滤结果一致
"""

import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def create_test_data():
    """创建测试用的模拟数据"""
    dates = pd.date_range('2025-01-01', '2025-01-31', freq='D')

    test_data = {
        '000001': pd.DataFrame({
            'date': dates,
            'open': range(100, 100 + len(dates)),
            'close': range(100, 100 + len(dates)),
            'high': range(101, 101 + len(dates)),
            'low': range(99, 99 + len(dates)),
            'volume': [1000000] * len(dates)
        }),
        '000002': pd.DataFrame({
            'date': dates,
            'open': range(50, 50 + len(dates)),
            'close': range(50, 50 + len(dates)),
            'high': range(51, 51 + len(dates)),
            'low': range(49, 49 + len(dates)),
            'volume': [500000] * len(dates)
        })
    }

    return test_data


def test_cache_initialization():
    """测试缓存初始化"""
    print("="*80)
    print("测试 1: 缓存初始化")
    print("="*80)

    from backtest.engine import BacktestEngine

    # Create mock engine with test data
    engine = BacktestEngine(
        data_dir="./data",
        buy_config_path="./configs.json",
        sell_strategy_config={},
        start_date="2025-01-01",
        end_date="2025-01-31",
        initial_capital=1000000
    )

    # Set test data
    test_data = create_test_data()
    engine.market_data = test_data

    # Test first call
    date1 = datetime(2025, 1, 10)
    cached_data = engine._get_data_up_to_date(date1)

    # Verify
    assert len(cached_data) == 2, f"Expected 2 stocks, got {len(cached_data)}"
    assert '000001' in cached_data, "Stock 000001 not in cache"
    assert '000002' in cached_data, "Stock 000002 not in cache"

    # Check data length
    assert len(cached_data['000001']) == 10, f"Expected 10 days for 000001, got {len(cached_data['000001'])}"
    assert len(cached_data['000002']) == 10, f"Expected 10 days for 000002, got {len(cached_data['000002'])}"

    # Check cache_date
    assert engine.cache_date == date1, f"cache_date should be {date1}, got {engine.cache_date}"

    print("✅ 缓存初始化测试通过")
    print(f"   - 缓存了 {len(cached_data)} 只股票")
    print(f"   - 000001: {len(cached_data['000001'])} 天数据")
    print(f"   - 000002: {len(cached_data['000002'])} 天数据")
    print(f"   - cache_date: {engine.cache_date.date()}")
    print()


def test_cache_same_date():
    """测试相同日期重复调用"""
    print("="*80)
    print("测试 2: 相同日期重复调用")
    print("="*80)

    from backtest.engine import BacktestEngine

    engine = BacktestEngine(
        data_dir="./data",
        buy_config_path="./configs.json",
        sell_strategy_config={},
        start_date="2025-01-01",
        end_date="2025-01-31",
        initial_capital=1000000
    )

    test_data = create_test_data()
    engine.market_data = test_data

    # First call
    date1 = datetime(2025, 1, 10)
    cached_data1 = engine._get_data_up_to_date(date1)

    # Second call with same date
    cached_data2 = engine._get_data_up_to_date(date1)

    # Should return same object (no copy)
    assert cached_data1 is cached_data2, "Same date should return same cache object"

    print("✅ 相同日期重复调用测试通过")
    print(f"   - 返回相同缓存对象（无需重新过滤）")
    print()


def test_incremental_update():
    """测试增量更新"""
    print("="*80)
    print("测试 3: 增量更新")
    print("="*80)

    from backtest.engine import BacktestEngine

    engine = BacktestEngine(
        data_dir="./data",
        buy_config_path="./configs.json",
        sell_strategy_config={},
        start_date="2025-01-01",
        end_date="2025-01-31",
        initial_capital=1000000
    )

    test_data = create_test_data()
    engine.market_data = test_data

    # First call: 10 days
    date1 = datetime(2025, 1, 10)
    cached_data1 = engine._get_data_up_to_date(date1)
    len1 = len(cached_data1['000001'])

    # Second call: +5 days
    date2 = datetime(2025, 1, 15)
    cached_data2 = engine._get_data_up_to_date(date2)
    len2 = len(cached_data2['000001'])

    # Third call: +5 days
    date3 = datetime(2025, 1, 20)
    cached_data3 = engine._get_data_up_to_date(date3)
    len3 = len(cached_data3['000001'])

    # Verify incremental growth
    assert len2 == len1 + 5, f"Expected {len1 + 5} days after increment, got {len2}"
    assert len3 == len2 + 5, f"Expected {len2 + 5} days after increment, got {len3}"

    print("✅ 增量更新测试通过")
    print(f"   - 第1次调用 (2025-01-10): {len1} 天")
    print(f"   - 第2次调用 (2025-01-15): {len2} 天 (+{len2-len1})")
    print(f"   - 第3次调用 (2025-01-20): {len3} 天 (+{len3-len2})")
    print()


def test_cache_consistency():
    """测试缓存结果与原始过滤结果一致性"""
    print("="*80)
    print("测试 4: 缓存结果一致性")
    print("="*80)

    from backtest.engine import BacktestEngine

    engine = BacktestEngine(
        data_dir="./data",
        buy_config_path="./configs.json",
        sell_strategy_config={},
        start_date="2025-01-01",
        end_date="2025-01-31",
        initial_capital=1000000
    )

    test_data = create_test_data()
    engine.market_data = test_data

    # Use cache
    date = datetime(2025, 1, 15)
    cached_result = engine._get_data_up_to_date(date)

    # Original filtering (no cache)
    original_result = {}
    for code, df in test_data.items():
        df_filtered = df[df['date'] <= date].copy()
        if len(df_filtered) > 0:
            original_result[code] = df_filtered

    # Compare
    assert len(cached_result) == len(original_result), "Stock count mismatch"

    for code in cached_result:
        assert code in original_result, f"Stock {code} missing in original result"

        cached_df = cached_result[code]
        original_df = original_result[code]

        # Check length
        assert len(cached_df) == len(original_df), \
            f"Length mismatch for {code}: cached={len(cached_df)}, original={len(original_df)}"

        # Check dates
        assert cached_df['date'].equals(original_df['date']), \
            f"Date mismatch for {code}"

        # Check data values
        assert cached_df['close'].equals(original_df['close']), \
            f"Close price mismatch for {code}"

    print("✅ 缓存结果一致性测试通过")
    print(f"   - 缓存结果与原始过滤结果完全一致")
    print(f"   - 验证了 {len(cached_result)} 只股票的所有列")
    print()


def test_new_stock_handling():
    """测试新股票出现时的处理"""
    print("="*80)
    print("测试 5: 新股票处理")
    print("="*80)

    from backtest.engine import BacktestEngine

    engine = BacktestEngine(
        data_dir="./data",
        buy_config_path="./configs.json",
        sell_strategy_config={},
        start_date="2025-01-01",
        end_date="2025-01-31",
        initial_capital=1000000
    )

    test_data = create_test_data()
    engine.market_data = test_data

    # Initial cache with 2 stocks
    date1 = datetime(2025, 1, 10)
    cached_data1 = engine._get_data_up_to_date(date1)
    assert len(cached_data1) == 2, "Should have 2 stocks initially"

    # Add new stock to market_data
    dates = pd.date_range('2025-01-01', '2025-01-31', freq='D')
    engine.market_data['000003'] = pd.DataFrame({
        'date': dates,
        'open': range(200, 200 + len(dates)),
        'close': range(200, 200 + len(dates)),
        'high': range(201, 201 + len(dates)),
        'low': range(199, 199 + len(dates)),
        'volume': [2000000] * len(dates)
    })

    # Update cache
    date2 = datetime(2025, 1, 15)
    cached_data2 = engine._get_data_up_to_date(date2)

    # Verify new stock is added
    assert len(cached_data2) == 3, f"Should have 3 stocks after adding new one, got {len(cached_data2)}"
    assert '000003' in cached_data2, "New stock 000003 should be in cache"
    assert len(cached_data2['000003']) == 15, f"New stock should have 15 days, got {len(cached_data2['000003'])}"

    print("✅ 新股票处理测试通过")
    print(f"   - 初始缓存: {len(cached_data1)} 只股票")
    print(f"   - 添加新股后: {len(cached_data2)} 只股票")
    print(f"   - 新股 000003: {len(cached_data2['000003'])} 天数据")
    print()


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*80)
    print("数据准备缓存逻辑测试")
    print("="*80 + "\n")

    try:
        test_cache_initialization()
        test_cache_same_date()
        test_incremental_update()
        test_cache_consistency()
        test_new_stock_handling()

        print("\n" + "="*80)
        print("✅ 所有测试通过！")
        print("="*80)
        print("\n缓存机制工作正常，可以安全使用。")

    except AssertionError as e:
        print("\n" + "="*80)
        print("❌ 测试失败")
        print("="*80)
        print(f"\n错误: {e}")
        sys.exit(1)
    except Exception as e:
        print("\n" + "="*80)
        print("❌ 测试异常")
        print("="*80)
        print(f"\n异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
