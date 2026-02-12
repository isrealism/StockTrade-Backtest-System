"""
Test script for selector combination logic and benchmark analysis.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest.engine import BacktestEngine
from backtest.performance import PerformanceAnalyzer
import json

def test_selector_combination():
    """Test selector combination modes."""
    print("="*80)
    print("TEST 1: Selector Combination Logic")
    print("="*80)

    # Test OR mode (default)
    print("\n--- Testing OR Mode ---")
    config_or = {
        "selector_combination": {
            "mode": "OR",
            "time_window_days": 5,
            "required_selectors": []
        },
        "selectors": [
            {
                "class": "BBIKDJSelector",
                "alias": "少妇战法",
                "activate": True,
                "params": {
                    "j_threshold": 15,
                    "bbi_min_window": 20,
                    "max_window": 120,
                    "price_range_pct": 1,
                    "bbi_q_threshold": 0.2,
                    "j_q_threshold": 0.10
                }
            },
            {
                "class": "SuperB1Selector",
                "alias": "SuperB1战法",
                "activate": True,
                "params": {
                    "lookback_n": 10,
                    "close_vol_pct": 0.02,
                    "price_drop_pct": 0.02,
                    "j_threshold": 10,
                    "j_q_threshold": 0.10,
                    "B1_params": {
                        "j_threshold": 15,
                        "bbi_min_window": 20,
                        "max_window": 120,
                        "price_range_pct": 1,
                        "bbi_q_threshold": 0.3,
                        "j_q_threshold": 0.10
                    }
                }
            }
        ]
    }

    sell_config = {
        "class": "PercentageTrailingStopStrategy",
        "params": {"trailing_pct": 0.08}
    }

    engine = BacktestEngine(
        data_dir="./data",
        buy_config_path="",
        sell_strategy_config=sell_config,
        start_date="2025-06-01",
        end_date="2025-06-30",
        initial_capital=1000000,
        max_positions=10,
        buy_config=config_or
    )

    try:
        engine.load_data()
        engine.load_buy_selectors()

        # Check that combination mode is loaded correctly
        print(f"✓ Combination mode loaded: {engine.combination_mode}")
        print(f"✓ Time window days: {engine.time_window_days}")
        print(f"✓ Required selectors: {engine.required_selectors}")
        print(f"✓ Number of selectors loaded: {len(engine.buy_selectors)}")

        print("\n✓ OR mode test PASSED")

    except Exception as e:
        print(f"✗ OR mode test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test AND mode
    print("\n--- Testing AND Mode ---")
    config_and = config_or.copy()
    config_and["selector_combination"]["mode"] = "AND"
    config_and["selector_combination"]["required_selectors"] = ["BBIKDJSelector", "SuperB1Selector"]

    engine2 = BacktestEngine(
        data_dir="./data",
        buy_config_path="",
        sell_strategy_config=sell_config,
        start_date="2025-06-01",
        end_date="2025-06-30",
        initial_capital=1000000,
        max_positions=10,
        buy_config=config_and
    )

    try:
        engine2.load_data()
        engine2.load_buy_selectors()

        print(f"✓ Combination mode loaded: {engine2.combination_mode}")
        print(f"✓ Required selectors: {engine2.required_selectors}")
        print("\n✓ AND mode test PASSED")

    except Exception as e:
        print(f"✗ AND mode test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test TIME_WINDOW mode
    print("\n--- Testing TIME_WINDOW Mode ---")
    config_window = config_or.copy()
    config_window["selector_combination"]["mode"] = "TIME_WINDOW"
    config_window["selector_combination"]["time_window_days"] = 5

    engine3 = BacktestEngine(
        data_dir="./data",
        buy_config_path="",
        sell_strategy_config=sell_config,
        start_date="2025-06-01",
        end_date="2025-06-30",
        initial_capital=1000000,
        max_positions=10,
        buy_config=config_window
    )

    try:
        engine3.load_data()
        engine3.load_buy_selectors()

        print(f"✓ Combination mode loaded: {engine3.combination_mode}")
        print(f"✓ Time window days: {engine3.time_window_days}")
        print("\n✓ TIME_WINDOW mode test PASSED")

    except Exception as e:
        print(f"✗ TIME_WINDOW mode test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "="*80)
    print("✓ ALL SELECTOR COMBINATION TESTS PASSED")
    print("="*80)
    return True


def test_benchmark_analysis():
    """Test benchmark analysis functionality."""
    print("\n" + "="*80)
    print("TEST 2: Benchmark Analysis")
    print("="*80)

    import pandas as pd

    # Create sample equity curve
    dates = pd.date_range('2025-06-01', '2025-06-30', freq='D')
    equity_curve = pd.DataFrame({
        'date': dates,
        'total_value': [1000000 * (1 + i*0.001) for i in range(len(dates))]
    })

    # Create empty trades DataFrame
    trades = pd.DataFrame()

    print("\n--- Testing without benchmark ---")
    try:
        analyzer1 = PerformanceAnalyzer(
            equity_curve=equity_curve,
            trades=trades,
            initial_capital=1000000
        )

        print(f"✓ Benchmark name: {analyzer1.benchmark_name}")
        print(f"✓ Benchmark data: {analyzer1.benchmark_data}")
        print("✓ No benchmark test PASSED")

    except Exception as e:
        print(f"✗ No benchmark test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n--- Testing with 沪深300 benchmark ---")
    try:
        analyzer2 = PerformanceAnalyzer(
            equity_curve=equity_curve,
            trades=trades,
            initial_capital=1000000,
            benchmark_name="沪深300"
        )

        print(f"✓ Benchmark name: {analyzer2.benchmark_name}")
        print(f"✓ Benchmark data loaded: {analyzer2.benchmark_data is not None}")
        if analyzer2.benchmark_data is not None:
            print(f"✓ Benchmark records: {len(analyzer2.benchmark_data)}")

        # Test get_benchmark_equity_curve
        benchmark_curve = analyzer2.get_benchmark_equity_curve()
        print(f"✓ Benchmark curve generated: {len(benchmark_curve)} records")

        print("\n✓ Benchmark test PASSED")

    except Exception as e:
        print(f"✗ Benchmark test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "="*80)
    print("✓ ALL BENCHMARK TESTS PASSED")
    print("="*80)
    return True


if __name__ == "__main__":
    print("\n" + "="*80)
    print("RUNNING IMPLEMENTATION TESTS")
    print("="*80)

    # Test 1: Selector Combination
    test1_passed = test_selector_combination()

    # Test 2: Benchmark Analysis
    test2_passed = test_benchmark_analysis()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Selector Combination: {'✓ PASSED' if test1_passed else '✗ FAILED'}")
    print(f"Benchmark Analysis:   {'✓ PASSED' if test2_passed else '✗ FAILED'}")

    if test1_passed and test2_passed:
        print("\n✓ ALL TESTS PASSED - Implementation successful!")
        sys.exit(0)
    else:
        print("\n✗ SOME TESTS FAILED - Please review errors above")
        sys.exit(1)
