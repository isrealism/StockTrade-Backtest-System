"""
Data validation utilities for stock trading system.

Provides functions to validate data quality, OHLC consistency, and more.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


def validate_ohlc_consistency(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Validate OHLC data consistency.

    Checks:
    - low <= open <= high
    - low <= close <= high
    - No negative prices
    - No NaN values in critical columns

    Args:
        df: DataFrame with OHLC columns

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    # Check for required columns
    required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        issues.append(f"Missing columns: {missing_cols}")
        return False, issues

    # Check for NaN values
    nan_cols = [col for col in required_cols if df[col].isna().any()]
    if nan_cols:
        nan_counts = {col: df[col].isna().sum() for col in nan_cols}
        issues.append(f"NaN values found: {nan_counts}")

    # Check for negative prices
    if (df['low'] < 0).any():
        count = (df['low'] < 0).sum()
        issues.append(f"Negative prices: {count} rows")

    # Check OHLC constraints
    ohlc_violations = df[
        (df['low'] > df['open']) |
        (df['low'] > df['close']) |
        (df['high'] < df['open']) |
        (df['high'] < df['close'])
    ]
    if len(ohlc_violations) > 0:
        issues.append(f"OHLC violations: {len(ohlc_violations)} rows (low > open/close or high < open/close)")

    # Check for zero volume
    if (df['volume'] == 0).any():
        count = (df['volume'] == 0).sum()
        issues.append(f"Zero volume: {count} rows (possible suspension)")

    # Check for duplicate dates
    if df['date'].duplicated().any():
        count = df['date'].duplicated().sum()
        issues.append(f"Duplicate dates: {count} rows")

    is_valid = len(issues) == 0
    return is_valid, issues


def validate_data_range(
    df: pd.DataFrame,
    min_length: int = 120,
    check_date_continuity: bool = False
) -> Tuple[bool, List[str]]:
    """
    Validate data has sufficient length and continuity.

    Args:
        df: DataFrame with date column
        min_length: Minimum required number of rows
        check_date_continuity: Check for missing dates (gaps)

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    # Check length
    if len(df) < min_length:
        issues.append(f"Insufficient data: {len(df)} rows < {min_length} required")

    # Check date continuity (optional)
    if check_date_continuity and len(df) > 1:
        df_sorted = df.sort_values('date')
        dates = pd.to_datetime(df_sorted['date'])

        # Find gaps > 7 days (weekends + holidays acceptable)
        gaps = dates.diff()
        large_gaps = gaps[gaps > pd.Timedelta(days=7)]
        if len(large_gaps) > 0:
            issues.append(f"Date gaps found: {len(large_gaps)} gaps > 7 days")

    is_valid = len(issues) == 0
    return is_valid, issues


def generate_data_quality_report(
    market_data: Dict[str, pd.DataFrame],
    backtest_start: pd.Timestamp
) -> Dict[str, any]:
    """
    Generate comprehensive data quality report.

    Args:
        market_data: Dictionary of {stock_code: DataFrame}
        backtest_start: Backtest start date

    Returns:
        Dictionary with quality metrics and issues
    """
    report = {
        "total_stocks": len(market_data),
        "stocks_with_issues": [],
        "summary": {
            "ohlc_violations": 0,
            "negative_prices": 0,
            "nan_values": 0,
            "insufficient_length": 0,
        }
    }

    for code, df in market_data.items():
        # Check OHLC consistency
        is_valid_ohlc, ohlc_issues = validate_ohlc_consistency(df)

        # Check data length at backtest start
        df_at_start = df[df['date'] <= backtest_start]
        is_valid_range, range_issues = validate_data_range(df_at_start, min_length=120)

        # Collect issues
        all_issues = ohlc_issues + range_issues
        if all_issues:
            report["stocks_with_issues"].append({
                "code": code,
                "issues": all_issues,
                "data_length_at_start": len(df_at_start)
            })

            # Update summary counts
            for issue in all_issues:
                if "OHLC violations" in issue:
                    report["summary"]["ohlc_violations"] += 1
                if "Negative prices" in issue:
                    report["summary"]["negative_prices"] += 1
                if "NaN values" in issue:
                    report["summary"]["nan_values"] += 1
                if "Insufficient data" in issue:
                    report["summary"]["insufficient_length"] += 1

    return report


def clean_dataframe(df: pd.DataFrame, drop_nan: bool = True, drop_ohlc_violations: bool = True) -> pd.DataFrame:
    """
    Clean DataFrame by removing invalid rows.

    Args:
        df: Input DataFrame
        drop_nan: Drop rows with NaN values in critical columns
        drop_ohlc_violations: Drop rows violating OHLC constraints

    Returns:
        Cleaned DataFrame
    """
    df_clean = df.copy()

    # Drop NaN values
    if drop_nan:
        critical_cols = ['date', 'open', 'high', 'low', 'close']
        df_clean = df_clean.dropna(subset=critical_cols)

    # Drop OHLC violations
    if drop_ohlc_violations:
        df_clean = df_clean[
            (df_clean['low'] <= df_clean['open']) &
            (df_clean['low'] <= df_clean['close']) &
            (df_clean['high'] >= df_clean['open']) &
            (df_clean['high'] >= df_clean['close']) &
            (df_clean['low'] >= 0)
        ]

    return df_clean
