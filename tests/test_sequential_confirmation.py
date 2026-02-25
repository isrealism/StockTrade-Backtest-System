"""
Test script for SEQUENTIAL_CONFIRMATION mode.

This script validates that the sequential confirmation logic
is correctly implemented and can parse configurations.
"""

import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_configuration_parsing():
    """Test that SEQUENTIAL_CONFIRMATION config can be parsed."""
    print("=" * 80)
    print("TEST 1: Configuration Parsing")
    print("=" * 80)

    test_config = {
        "selector_combination": {
            "mode": "SEQUENTIAL_CONFIRMATION",
            "time_window_days": 5,
            "trigger_selectors": ["BBIKDJSelector"],
            "trigger_logic": "OR",
            "confirm_selectors": ["MA60CrossVolumeWaveSelector"],
            "confirm_logic": "OR",
            "buy_timing": "confirmation_day"
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
                "class": "MA60CrossVolumeWaveSelector",
                "alias": "上穿60放量战法",
                "activate": True,
                "params": {
                    "lookback_n": 25,
                    "vol_multiple": 1.8,
                    "j_threshold": 15,
                    "j_q_threshold": 0.10,
                    "ma60_slope_days": 5,
                    "max_window": 120
                }
            }
        ]
    }

    from backtest.engine import BacktestEngine

    try:
        # Initialize engine with test config
        engine = BacktestEngine(
            data_dir="./data",
            buy_config_path="./configs.json",
            sell_strategy_config={"class": "PercentageTrailingStopStrategy", "params": {"trailing_pct": 0.08}},
            start_date="2025-01-01",
            end_date="2025-01-31",
            buy_config=test_config
        )

        # Load selectors (this will parse the configuration)
        engine.load_buy_selectors()

        print("\n✓ Configuration parsed successfully!")
        print(f"  Combination mode: {engine.combination_mode}")
        print(f"  Time window: {engine.time_window_days} days")
        print(f"  Trigger selectors ({engine.trigger_logic}): {', '.join(engine.trigger_selectors)}")
        print(f"  Confirm selectors ({engine.confirm_logic}): {', '.join(engine.confirm_selectors)}")
        print(f"  Buy timing: {engine.buy_timing}")
        print(f"  Loaded selectors: {len(engine.buy_selectors)}")

        # Verify attributes
        assert engine.combination_mode == "SEQUENTIAL_CONFIRMATION"
        assert engine.time_window_days == 5
        assert engine.trigger_selectors == ["BBIKDJSelector"]
        assert engine.trigger_logic == "OR"
        assert engine.confirm_selectors == ["MA60CrossVolumeWaveSelector"]
        assert engine.confirm_logic == "OR"
        assert engine.buy_timing == "confirmation_day"
        assert len(engine.buy_selectors) == 2

        print("\n✓ All assertions passed!")
        return True

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_validation_errors():
    """Test that validation errors are raised for invalid configs."""
    print("\n" + "=" * 80)
    print("TEST 2: Validation Error Handling")
    print("=" * 80)

    from backtest.engine import BacktestEngine

    # Test 1: Missing trigger_selectors
    print("\nTest 2.1: Missing trigger_selectors")
    test_config_1 = {
        "selector_combination": {
            "mode": "SEQUENTIAL_CONFIRMATION",
            "confirm_selectors": ["MA60CrossVolumeWaveSelector"]
        },
        "selectors": []
    }

    try:
        engine = BacktestEngine(
            data_dir="./data",
            buy_config_path="./configs.json",
            sell_strategy_config={"class": "PercentageTrailingStopStrategy", "params": {"trailing_pct": 0.08}},
            start_date="2025-01-01",
            end_date="2025-01-31",
            buy_config=test_config_1
        )
        engine.load_buy_selectors()
        print("✗ Should have raised ValueError for missing trigger_selectors")
        return False
    except ValueError as e:
        if "trigger_selectors" in str(e):
            print(f"✓ Correctly raised error: {e}")
        else:
            print(f"✗ Wrong error: {e}")
            return False

    # Test 2: Missing confirm_selectors
    print("\nTest 2.2: Missing confirm_selectors")
    test_config_2 = {
        "selector_combination": {
            "mode": "SEQUENTIAL_CONFIRMATION",
            "trigger_selectors": ["BBIKDJSelector"]
        },
        "selectors": []
    }

    try:
        engine = BacktestEngine(
            data_dir="./data",
            buy_config_path="./configs.json",
            sell_strategy_config={"class": "PercentageTrailingStopStrategy", "params": {"trailing_pct": 0.08}},
            start_date="2025-01-01",
            end_date="2025-01-31",
            buy_config=test_config_2
        )
        engine.load_buy_selectors()
        print("✗ Should have raised ValueError for missing confirm_selectors")
        return False
    except ValueError as e:
        if "confirm_selectors" in str(e):
            print(f"✓ Correctly raised error: {e}")
        else:
            print(f"✗ Wrong error: {e}")
            return False

    print("\n✓ All validation tests passed!")
    return True


def test_example_configs():
    """Test all example configurations from configs.json."""
    print("\n" + "=" * 80)
    print("TEST 3: Example Configuration Validation")
    print("=" * 80)

    # Load configs.json
    config_path = project_root / "configs.json"
    with open(config_path, 'r', encoding='utf-8') as f:
        configs = json.load(f)

    # Extract example configurations
    examples = [
        ("Example 1", configs.get("_example_1")),
        ("Example 2", configs.get("_example_2")),
        ("Example 3", configs.get("_example_3")),
        ("Example 4", configs.get("_example_4"))
    ]

    from backtest.engine import BacktestEngine

    all_passed = True
    for name, example_config in examples:
        if not example_config:
            continue

        print(f"\n{name}: {example_config.get('_description', 'No description')}")

        test_config = {
            "selector_combination": example_config,
            "selectors": configs["selectors"]  # Use actual selectors from configs.json
        }

        try:
            engine = BacktestEngine(
                data_dir="./data",
                buy_config_path="./configs.json",
                sell_strategy_config={"class": "PercentageTrailingStopStrategy", "params": {"trailing_pct": 0.08}},
                start_date="2025-01-01",
                end_date="2025-01-31",
                buy_config=test_config
            )
            engine.load_buy_selectors()

            print(f"  ✓ Config valid")
            print(f"    Triggers ({engine.trigger_logic}): {', '.join(engine.trigger_selectors)}")
            print(f"    Confirms ({engine.confirm_logic}): {', '.join(engine.confirm_selectors)}")

        except Exception as e:
            print(f"  ✗ Failed: {e}")
            all_passed = False

    if all_passed:
        print("\n✓ All example configurations are valid!")
    else:
        print("\n✗ Some example configurations failed!")

    return all_passed


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("SEQUENTIAL CONFIRMATION MODE - TEST SUITE")
    print("=" * 80)

    results = []

    # Run tests
    results.append(("Configuration Parsing", test_configuration_parsing()))
    results.append(("Validation Errors", test_validation_errors()))
    results.append(("Example Configs", test_example_configs()))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(passed for _, passed in results)

    print("\n" + "=" * 80)
    if all_passed:
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
