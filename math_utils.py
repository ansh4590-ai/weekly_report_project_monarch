"""
Mathematical utilities for calculations with deterministic rounding
"""

import math
from typing import Optional


def round_half_up(value: float, decimals: int = 0) -> float:
    """
    Round using half-up strategy (0.5 rounds up, not banker's rounding).

    Python's built-in round() uses banker's rounding (round-half-to-even),
    but financial reports typically use half-up rounding for consistency.

    Args:
        value: Value to round
        decimals: Number of decimal places (default 0)

    Returns:
        Rounded value

    Examples:
        >>> round_half_up(2.5)
        3.0
        >>> round_half_up(2.45, 1)
        2.5
    """
    multiplier = 10 ** decimals
    if value != value:  # NaN check (math.isnan may fail on non-float)
        return float('nan')
    return math.floor(value * multiplier + 0.5) / multiplier


def round2(v: Optional[float]) -> Optional[float]:
    """
    Round to 2 decimal places (half-up), or return None if input is None or NaN.

    Args:
        v: Value to round (or None)

    Returns:
        Rounded value or None
    """
    if v is None:
        return None
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return round_half_up(fv, 2)
    except (TypeError, ValueError):
        return None


def round0(v: Optional[float]) -> Optional[int]:
    """
    Round to nearest integer (half-up), or return None if input is None or NaN.

    Args:
        v: Value to round (or None)

    Returns:
        Rounded integer or None
    """
    if v is None:
        return None
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return int(round_half_up(fv, 0))
    except (TypeError, ValueError):
        return None


def round_to_nearest(value: float, multiple: int) -> int:
    """
    Round value to nearest multiple using half-up strategy.

    Used for support/resistance levels (round to 100, 500, etc.).

    Args:
        value: Value to round
        multiple: Multiple to round to (e.g., 100, 500)

    Returns:
        Rounded integer

    Examples:
        >>> round_to_nearest(24150, 100)
        24200
        >>> round_to_nearest(57250, 500)
        57500
    """
    return int(math.floor(value / multiple + 0.5) * multiple)


def calculate_weekly_pct(prev_close: Optional[float],
                         curr_close: Optional[float]) -> Optional[float]:
    """
    Calculate weekly percentage change with half-up rounding.

    Formula: ((curr - prev) / prev) * 100

    Args:
        prev_close: Previous week's Friday close
        curr_close: Current week's Friday close

    Returns:
        Percentage change rounded to 2 decimals, or None if inputs invalid
    """
    if prev_close is None or curr_close is None:
        return None

    # Guard against NaN (e.g., missing stock data from Yahoo Finance)
    try:
        if math.isnan(prev_close) or math.isnan(curr_close):
            return None
    except (TypeError, ValueError):
        return None

    if prev_close == 0:
        return None

    raw_pct = (curr_close - prev_close) / prev_close * 100

    # Round to 2 decimals using half-up
    return round_half_up(raw_pct, 2)


def calculate_ema(series, span: int):
    """
    Calculate Exponential Moving Average using standard formula.

    Uses pandas ewm with adjust=False (recursive formula, industry standard).

    Args:
        series: pandas Series of closing prices
        span: EMA period (e.g., 9, 21, 50, 200)

    Returns:
        pandas Series of EMA values
    """
    return series.ewm(span=span, adjust=False).mean()


def determine_bias(close: Optional[float], ema200: Optional[float]) -> str:
    """
    Determine market bias based on close vs EMA-200.

    Args:
        close: Current close price
        ema200: 200-period EMA value

    Returns:
        "BULLISH" if close > ema200
        "BEARISH" if close < ema200
        "NEUTRAL" if close == ema200
        "VOLATILE" if insufficient data
    """
    if close is None or ema200 is None:
        return "VOLATILE"

    if close > ema200:
        return "BULLISH"
    elif close < ema200:
        return "BEARISH"
    else:
        return "NEUTRAL"


def calculate_support_resistance(close: float,
                                  rounding_multiple: int,
                                  s1_factor: float = 0.98,
                                  s2_factor: float = 0.967,
                                  r1_factor: float = 1.02,
                                  r2_factor: float = 1.033) -> dict:
    """
    Calculate support and resistance levels using percentage-based bands.

    Args:
        close: Current close price
        rounding_multiple: Multiple to round to (100, 500, etc.)
        s1_factor: Support 1 multiplier (default 0.98 = -2%)
        s2_factor: Support 2 multiplier (default 0.967 = -3.3%)
        r1_factor: Resistance 1 multiplier (default 1.02 = +2%)
        r2_factor: Resistance 2 multiplier (default 1.033 = +3.3%)

    Returns:
        Dict with keys: s1, s2, r1, r2 (all integers)
    """
    s1 = round_to_nearest(close * s1_factor, rounding_multiple)
    s2 = round_to_nearest(close * s2_factor, rounding_multiple)
    r1 = round_to_nearest(close * r1_factor, rounding_multiple)
    r2 = round_to_nearest(close * r2_factor, rounding_multiple)

    return {"s1": s1, "s2": s2, "r1": r1, "r2": r2}
