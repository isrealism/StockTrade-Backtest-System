#!/usr/bin/env python3
"""
Test script to verify selector combination logic frontend integration.

This script creates a test payload to verify that the frontend correctly
sends selector combination configuration to the backend.
"""

import json

# Test payload with different combination modes
test_payloads = {
    "or_mode": {
        "name": "Test OR Mode",
        "start_date": "2025-01-01",
        "end_date": "2025-06-30",
        "initial_capital": 1000000,
        "max_positions": 10,
        "position_sizing": "equal_weight",
        "lookback_days": 200,
        "commission_rate": 0.0003,
        "stamp_tax_rate": 0.001,
        "slippage_rate": 0.001,
        "buy_config": {
            "selectors": [
                {
                    "class": "BBIKDJSelector",
                    "alias": "少妇战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                },
                {
                    "class": "SuperB1Selector",
                    "alias": "SuperB1战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                }
            ],
            "selector_combination": {
                "mode": "OR"
            }
        },
        "sell_strategy_name": "conservative_trailing",
        "stock_pool": {"type": "all"}
    },

    "and_mode": {
        "name": "Test AND Mode",
        "start_date": "2025-01-01",
        "end_date": "2025-06-30",
        "initial_capital": 1000000,
        "max_positions": 10,
        "position_sizing": "equal_weight",
        "lookback_days": 200,
        "commission_rate": 0.0003,
        "stamp_tax_rate": 0.001,
        "slippage_rate": 0.001,
        "buy_config": {
            "selectors": [
                {
                    "class": "BBIKDJSelector",
                    "alias": "少妇战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                },
                {
                    "class": "SuperB1Selector",
                    "alias": "SuperB1战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                }
            ],
            "selector_combination": {
                "mode": "AND"
            }
        },
        "sell_strategy_name": "conservative_trailing",
        "stock_pool": {"type": "all"}
    },

    "time_window_mode": {
        "name": "Test Time Window Mode",
        "start_date": "2025-01-01",
        "end_date": "2025-06-30",
        "initial_capital": 1000000,
        "max_positions": 10,
        "position_sizing": "equal_weight",
        "lookback_days": 200,
        "commission_rate": 0.0003,
        "stamp_tax_rate": 0.001,
        "slippage_rate": 0.001,
        "buy_config": {
            "selectors": [
                {
                    "class": "BBIKDJSelector",
                    "alias": "少妇战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                },
                {
                    "class": "SuperB1Selector",
                    "alias": "SuperB1战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                }
            ],
            "selector_combination": {
                "mode": "TIME_WINDOW",
                "time_window_days": 5
            }
        },
        "sell_strategy_name": "conservative_trailing",
        "stock_pool": {"type": "all"}
    },

    "sequential_confirmation_mode": {
        "name": "Test Sequential Confirmation Mode",
        "start_date": "2025-01-01",
        "end_date": "2025-06-30",
        "initial_capital": 1000000,
        "max_positions": 10,
        "position_sizing": "equal_weight",
        "lookback_days": 200,
        "commission_rate": 0.0003,
        "stamp_tax_rate": 0.001,
        "slippage_rate": 0.001,
        "buy_config": {
            "selectors": [
                {
                    "class": "BBIKDJSelector",
                    "alias": "少妇战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                },
                {
                    "class": "SuperB1Selector",
                    "alias": "SuperB1战法",
                    "activate": True,
                    "params": {"j_threshold": 15}
                },
                {
                    "class": "MA60CrossVolumeWaveSelector",
                    "alias": "上穿60放量战法",
                    "activate": True,
                    "params": {"j_threshold": 20}
                }
            ],
            "selector_combination": {
                "mode": "SEQUENTIAL_CONFIRMATION",
                "time_window_days": 5,
                "trigger_selectors": ["BBIKDJSelector", "SuperB1Selector"],
                "trigger_logic": "OR",
                "confirm_selectors": ["MA60CrossVolumeWaveSelector"],
                "confirm_logic": "OR",
                "buy_timing": "confirmation_day"
            }
        },
        "sell_strategy_name": "conservative_trailing",
        "stock_pool": {"type": "all"}
    }
}

def main():
    print("Selector Combination UI Test Payloads")
    print("=" * 60)

    for mode_name, payload in test_payloads.items():
        print(f"\n{mode_name.upper()}:")
        print("-" * 60)

        comb_config = payload["buy_config"]["selector_combination"]
        print(f"Mode: {comb_config['mode']}")

        if "time_window_days" in comb_config:
            print(f"Time Window: {comb_config['time_window_days']} days")

        if comb_config['mode'] == "SEQUENTIAL_CONFIRMATION":
            print(f"Trigger Selectors ({comb_config['trigger_logic']}): {', '.join(comb_config['trigger_selectors'])}")
            print(f"Confirm Selectors ({comb_config['confirm_logic']}): {', '.join(comb_config['confirm_selectors'])}")
            print(f"Buy Timing: {comb_config['buy_timing']}")

        print(f"\nJSON Payload Preview:")
        print(json.dumps(comb_config, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("\nTo test in frontend:")
    print("1. Start the backend server: cd backend && uvicorn app:app --reload")
    print("2. Open frontend in browser: http://localhost:8000")
    print("3. Select combination mode from dropdown")
    print("4. Configure settings and verify payload is sent correctly")
    print("\nTo test backend directly:")
    print("You can POST these payloads to /api/backtests endpoint")

if __name__ == "__main__":
    main()
