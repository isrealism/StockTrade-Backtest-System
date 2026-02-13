"""
Date and time utilities for trading system.

Provides helper functions for working with trading dates, date ranges, etc.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional


def get_trading_dates(
    df: pd.DataFrame,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> List[datetime]:
    """
    Extract list of trading dates from DataFrame.

    Args:
        df: DataFrame with 'date' column
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        Sorted list of unique trading dates
    """
    dates = pd.to_datetime(df['date'])

    # Apply filters
    if start_date is not None:
        dates = dates[dates >= start_date]
    if end_date is not None:
        dates = dates[dates <= end_date]

    return sorted(dates.unique().tolist())


def count_trading_days(
    dates: List[datetime],
    start: datetime,
    end: datetime
) -> int:
    """
    Count trading days between start and end dates.

    Args:
        dates: List of all trading dates
        start: Start date
        end: End date

    Returns:
        Number of trading days in range
    """
    return sum(1 for d in dates if start <= d <= end)


def get_previous_trading_date(
    dates: List[datetime],
    current_date: datetime
) -> Optional[datetime]:
    """
    Get the previous trading date before current_date.

    Args:
        dates: List of all trading dates (sorted)
        current_date: Current date

    Returns:
        Previous trading date or None if not found
    """
    prev_dates = [d for d in dates if d < current_date]
    return prev_dates[-1] if prev_dates else None


def get_next_trading_date(
    dates: List[datetime],
    current_date: datetime
) -> Optional[datetime]:
    """
    Get the next trading date after current_date.

    Args:
        dates: List of all trading dates (sorted)
        current_date: Current date

    Returns:
        Next trading date or None if not found
    """
    next_dates = [d for d in dates if d > current_date]
    return next_dates[0] if next_dates else None


def get_date_range_with_lookback(
    end_date: datetime,
    lookback_trading_days: int,
    all_trading_dates: List[datetime]
) -> datetime:
    """
    Get start date by going back N trading days from end_date.

    Args:
        end_date: End date
        lookback_trading_days: Number of trading days to look back
        all_trading_dates: List of all trading dates

    Returns:
        Start date (N trading days before end_date)
    """
    # Find end_date position
    try:
        end_idx = all_trading_dates.index(end_date)
    except ValueError:
        # If end_date not in list, find closest date before it
        earlier_dates = [d for d in all_trading_dates if d <= end_date]
        if not earlier_dates:
            raise ValueError(f"No trading dates found before {end_date}")
        end_date = earlier_dates[-1]
        end_idx = all_trading_dates.index(end_date)

    # Go back N trading days
    start_idx = max(0, end_idx - lookback_trading_days)
    return all_trading_dates[start_idx]


def is_trading_day(date: datetime, trading_dates: List[datetime]) -> bool:
    """
    Check if date is a trading day.

    Args:
        date: Date to check
        trading_dates: List of all trading dates

    Returns:
        True if date is a trading day
    """
    return date in trading_dates


def format_date_range(start: datetime, end: datetime) -> str:
    """
    Format date range as string.

    Args:
        start: Start date
        end: End date

    Returns:
        Formatted string like "2024-01-01 to 2024-12-31"
    """
    return f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"


def parse_date(date_str: str) -> datetime:
    """
    Parse date string to datetime.

    Supports formats:
    - YYYY-MM-DD
    - YYYYMMDD
    - "today"

    Args:
        date_str: Date string

    Returns:
        Parsed datetime

    Raises:
        ValueError if format is invalid
    """
    if date_str.lower() == 'today':
        return datetime.now()

    # Try YYYY-MM-DD
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        pass

    # Try YYYYMMDD
    try:
        return datetime.strptime(date_str, '%Y%m%d')
    except ValueError:
        pass

    raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD, YYYYMMDD, or 'today'")
