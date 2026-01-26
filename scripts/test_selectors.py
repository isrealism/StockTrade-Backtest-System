#!/usr/bin/env python
"""
Test individual selectors to diagnose signal generation issues.

Usage:
    python scripts/test_selectors.py

This script:
1. Loads all activated selectors from configs.json
2. Tests each selector individually with sample data
3. Reports which selectors are working and which are failing
"""

import sys
import json
from pathlib import Path
import pandas as pd

# Add parent directory to path to import Selector module
sys.path.insert(0, str(Path(__file__).parent.parent))
import Selector


def test_selector(selector_class, selector_name, params, data_dir, test_date, num_stocks=100):
    """
    Test a single selector.

    Args:
        selector_class: Selector class to test
        selector_name: Display name
        params: Selector parameters
        data_dir: Directory with stock data
        test_date: Date to test on (YYYY-MM-DD)
        num_stocks: Number of stocks to test with
    """
    print(f"\n{'='*80}")
    print(f"Testing: {selector_name}")
    print(f"{'='*80}")

    # Load sample data (first N stocks)
    data = {}
    csv_files = sorted(list(Path(data_dir).glob("*.csv")))[:num_stocks]

    print(f"Loading {num_stocks} stocks...")

    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            df['date'] = pd.to_datetime(df['date'])
            df = df[df['date'] <= pd.to_datetime(test_date)]

            if len(df) > 0:
                code = csv_file.stem
                data[code] = df
        except Exception as e:
            print(f"  Error loading {csv_file.name}: {e}")
            pass

    print(f"Loaded {len(data)} stocks with data on or before {test_date}")

    if len(data) == 0:
        print("ERROR: No data loaded. Cannot test selector.")
        return

    # Show data length statistics
    lengths = [len(df) for df in data.values()]
    print(f"Data lengths: min={min(lengths)}, max={max(lengths)}, median={sorted(lengths)[len(lengths)//2]}")

    # Create selector instance
    print(f"\nCreating selector instance...")
    try:
        selector = selector_class(**params)
        print(f"✓ Selector created successfully")
    except Exception as e:
        print(f"✗ ERROR creating selector: {e}")
        import traceback
        traceback.print_exc()
        return

    # Run selector
    print(f"\nRunning selector.select()...")
    try:
        selected = selector.select(pd.Timestamp(test_date), data)
        print(f"✓ Selector ran successfully")
        print(f"✓ Signals generated: {len(selected)}")

        if len(selected) > 0:
            print(f"  Sample signals (first 10): {selected[:10]}")
        else:
            print(f"  No signals generated (this may be normal if criteria are very specific)")

    except Exception as e:
        print(f"✗ ERROR running selector: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Test all selectors from configs.json."""
    config_path = Path(__file__).parent.parent / "configs.json"

    print("="*80)
    print("SELECTOR VALIDATION TEST")
    print("="*80)
    print(f"Config: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Use 2025 data for sufficient historical depth
    test_date = "2025-02-01"
    data_dir = Path(__file__).parent.parent / "data"

    print(f"Test date: {test_date}")
    print(f"Data directory: {data_dir}")

    # Test each activated selector
    activated_selectors = [s for s in config['selectors'] if s.get('activate', False)]
    print(f"\nFound {len(activated_selectors)} activated selectors")

    for selector_config in activated_selectors:
        class_name = selector_config['class']
        params = selector_config.get('params', {})
        alias = selector_config.get('alias', class_name)

        if hasattr(Selector, class_name):
            selector_class = getattr(Selector, class_name)
            test_selector(selector_class, alias, params, data_dir, test_date)
        else:
            print(f"\n{'='*80}")
            print(f"Testing: {alias}")
            print(f"{'='*80}")
            print(f"✗ WARNING: {class_name} not found in Selector.py")

    print(f"\n{'='*80}")
    print("TEST COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
