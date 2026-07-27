"""
Date validation and trading day logic
"""

from datetime import datetime, timedelta, date
from typing import Tuple


def validate_end_sunday(end_str: str) -> Tuple[date, date]:
    """
    Validate the end Sunday and auto-derive the start Sunday (7 days prior).

    The weekly report always spans exactly one week, so only the end Sunday
    needs to be provided. Start is always end - 7 days.

    Args:
        end_str: End date (Sunday) in DD-MM-YYYY format

    Returns:
        Tuple of (start_date, end_date) as date objects

    Raises:
        ValueError: If date is invalid or not a Sunday
    """
    fmt = "%d-%m-%Y"

    try:
        end = datetime.strptime(end_str.strip(), fmt).date()
    except ValueError:
        raise ValueError(f"Invalid date '{end_str}'. Use DD-MM-YYYY format.")

    if end.weekday() != 6:
        raise ValueError(
            f"{end.strftime('%d-%b-%Y')} is a {end.strftime('%A')}. "
            f"Please enter a Sunday."
        )

    start = end - timedelta(days=7)
    return start, end


def validate_date_range(start_str: str, end_str: str) -> Tuple[date, date]:
    """
    Validate that date range is exactly Sunday-to-Sunday (7 days).

    Args:
        start_str: Start date in DD-MM-YYYY format
        end_str: End date in DD-MM-YYYY format

    Returns:
        Tuple of (start_date, end_date) as date objects

    Raises:
        ValueError: If dates are invalid, not Sundays, or not 7 days apart
    """
    fmt = "%d-%m-%Y"

    try:
        start = datetime.strptime(start_str.strip(), fmt).date()
    except ValueError:
        raise ValueError(f"Invalid start date '{start_str}'. Use DD-MM-YYYY format.")

    try:
        end = datetime.strptime(end_str.strip(), fmt).date()
    except ValueError:
        raise ValueError(f"Invalid end date '{end_str}'. Use DD-MM-YYYY format.")

    # Both must be Sundays (weekday 6)
    if start.weekday() != 6:
        raise ValueError(
            f"Start date {start.strftime('%d-%b-%Y')} is {start.strftime('%A')}. "
            f"Must be Sunday."
        )

    if end.weekday() != 6:
        raise ValueError(
            f"End date {end.strftime('%d-%b-%Y')} is {end.strftime('%A')}. "
            f"Must be Sunday."
        )

    # Must be exactly 7 days apart
    delta = (end - start).days
    if delta != 7:
        raise ValueError(
            f"Date range is {delta} days (from {start.strftime('%d-%b-%Y')} "
            f"to {end.strftime('%d-%b-%Y')}). Must be exactly 7 days."
        )

    return start, end


def find_last_trading_day(target_date: date, df, max_lookback: int = 3) -> date:
    """
    Find the last trading day on or before target_date by checking dataframe.

    This handles market holidays - if target_date (e.g., Friday) is a holiday,
    returns the previous trading day (e.g., Thursday).

    Args:
        target_date: Target date (typically Friday)
        df: DataFrame with DatetimeIndex containing trading days
        max_lookback: Maximum days to look back (default 3 for long weekends)

    Returns:
        Last trading day on or before target_date

    Raises:
        ValueError: If no trading day found within max_lookback
    """
    import pandas as pd

    if df is None or df.empty:
        # No data available - return target date as best guess
        return target_date

    # Check each day from target_date backwards
    for i in range(max_lookback + 1):
        check_date = target_date - timedelta(days=i)
        ts = pd.Timestamp(check_date)

        # Check if this date exists in dataframe
        if ts in df.index:
            return check_date

    # Fallback: return target_date if nothing found
    # (Caller should detect missing data and handle appropriately)
    return target_date


def get_friday_dates(start_sunday: date, end_sunday: date) -> Tuple[date, date]:
    """
    Calculate the Friday dates for prev week and current week.

    For a Sunday-to-Sunday week:
    - prev_friday: Friday before start_sunday (start_sunday - 2 days)
    - curr_friday: Friday before end_sunday (end_sunday - 2 days)

    Args:
        start_sunday: Start of week (Sunday)
        end_sunday: End of week (Sunday)

    Returns:
        Tuple of (prev_friday, curr_friday)
    """
    prev_friday = start_sunday - timedelta(days=2)
    curr_friday = end_sunday - timedelta(days=2)

    return prev_friday, curr_friday


def validate_trading_day(target_date: date, df, symbol_name: str) -> bool:
    """
    Check if target_date has trading data in dataframe.

    Args:
        target_date: Date to check
        df: DataFrame with DatetimeIndex
        symbol_name: Name of symbol (for logging)

    Returns:
        True if trading day, False otherwise
    """
    import pandas as pd

    if df is None or df.empty:
        return False

    ts = pd.Timestamp(target_date)
    return ts in df.index
