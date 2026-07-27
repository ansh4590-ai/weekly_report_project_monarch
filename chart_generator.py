"""
Chart Generator for Weekly Equity Report
=========================================

Generates TradingView-style weekly candlestick charts for NIFTY 50, 
BANK NIFTY, and FINNIFTY.

Visual fidelity targets:
- TradingView green (#26A69A) / red (#EF5350) candlesticks
- White background
- Right-side Y-axis with comma-formatted prices
- Horizontal dotted cyan line at current price with price label
- ~20 weekly candles
- Matching candle proportions, spacing, margins
"""

import os
import tempfile
from datetime import date, timedelta
from typing import Dict, Optional, Tuple, List

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch


# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

# TradingView color palette
TV_GREEN = '#26A69A'
TV_RED = '#EF5350'
TV_BG = '#FFFFFF'
TV_GRID = '#E0E3EB'
TV_AXIS_TEXT = '#787B86'
TV_PRICE_LINE = '#2196F3'       # Cyan/blue for current price line
TV_PRICE_LABEL_BG = '#2196F3'   # Price label background
TV_PRICE_LABEL_TEXT = '#FFFFFF'  # Price label text

# Chart dimensions matching corrected EMU config values
# CHART_IMG_CX = 4,200,000 EMU ≈ 4.59 inches; CHART_IMG_CY = 2,700,000 EMU ≈ 2.95 inches
# Render at ~1.4× for crisp quality (Word downscales to EMU)
CHART_WIDTH_INCHES = 6.5    # Render wider for crispness
CHART_HEIGHT_INCHES = 3.5   # Proportional to EMU target aspect ratio
CHART_DPI = 150  # High DPI for crisp rendering

# Candle proportions (relative to spacing)
CANDLE_BODY_WIDTH = 0.72   # Body width as fraction of spacing
CANDLE_WICK_WIDTH = 1.2    # Wick line width in points

# Number of weekly candles to display
NUM_WEEKS = 40


# ═══════════════════════════════════════════════════════════════════
# WEEKLY OHLC AGGREGATION
# ═══════════════════════════════════════════════════════════════════

def aggregate_weekly_ohlc(daily_df: pd.DataFrame,
                          end_date: date,
                          num_weeks: int = NUM_WEEKS) -> pd.DataFrame:
    """
    Aggregate daily OHLC data into weekly OHLC candles.
    
    Each week runs Monday–Friday. The weekly candle:
    - Open  = Monday's open (or first trading day of week)
    - High  = Max high of the week
    - Low   = Min low of the week
    - Close = Friday's close (or last trading day of week)
    
    Args:
        daily_df: DataFrame with DatetimeIndex and OHLC columns
        end_date: End date for the chart
        num_weeks: Number of weekly candles to generate
        
    Returns:
        DataFrame with weekly OHLC data, indexed by week-ending date
    """
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()
    
    df = daily_df.copy()
    
    # Ensure we have required columns
    for col in ['Open', 'High', 'Low', 'Close']:
        if col not in df.columns:
            return pd.DataFrame()
    
    # Filter up to end_date
    ts_end = pd.Timestamp(end_date)
    df = df[df.index <= ts_end]
    
    if df.empty:
        return pd.DataFrame()
    
    # Resample to weekly (W-FRI = week ending Friday)
    weekly = df.resample('W-FRI').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last'
    })

    # Drop weeks where ALL OHLC values are NaN (i.e., no trading data at all).
    # Do NOT use plain .dropna() — Yahoo Finance sometimes returns a valid
    # Open/High/Low but NaN for Close on the most recent day (a known YF quirk).
    # Dropping on all columns would silently remove the current week's candle.
    weekly = weekly.dropna(subset=['Open', 'High', 'Low'])

    # Heal any remaining NaN Close (YF quirk: Close not yet published for today).
    # Fill with the last valid daily Close from the raw data that falls on or
    # before the week-ending date, so the candle renders correctly.
    if not weekly.empty and weekly['Close'].isna().any():
        # Build a clean daily close series (drop NaN rows)
        daily_close = df['Close'].dropna()
        for week_end, row in weekly[weekly['Close'].isna()].iterrows():
            available = daily_close[daily_close.index <= week_end]
            if not available.empty:
                weekly.at[week_end, 'Close'] = float(available.iloc[-1])

    # Drop any week still missing Close after the heal attempt
    weekly = weekly.dropna(subset=['Close'])

    # Take only the last N weeks
    if len(weekly) > num_weeks:
        weekly = weekly.iloc[-num_weeks:]

    return weekly


# ═══════════════════════════════════════════════════════════════════
# CANDLESTICK CHART RENDERING
# ═══════════════════════════════════════════════════════════════════

def _format_price(price: float) -> str:
    """Format price with comma separators and 2 decimal places."""
    return f'{price:,.2f}'


def generate_candlestick_chart(weekly_df: pd.DataFrame,
                                output_path: str,
                                current_close: Optional[float] = None) -> str:
    """
    Generate a TradingView-style weekly candlestick chart.
    
    Args:
        weekly_df: DataFrame with weekly OHLC data
        output_path: Path to save the PNG file
        current_close: Current price for the horizontal line
        
    Returns:
        Path to the generated PNG file
    """
    if weekly_df.empty:
        # Generate a placeholder chart
        fig, ax = plt.subplots(figsize=(CHART_WIDTH_INCHES, CHART_HEIGHT_INCHES))
        ax.text(0.5, 0.5, 'No Data Available', transform=ax.transAxes,
                ha='center', va='center', fontsize=14, color='#787B86')
        ax.set_facecolor(TV_BG)
        fig.patch.set_facecolor(TV_BG)
        fig.savefig(output_path, dpi=CHART_DPI, bbox_inches='tight',
                    facecolor=TV_BG, pad_inches=0.05)
        plt.close(fig)
        return output_path
    
    n = len(weekly_df)
    
    # Create figure with exact dimensions
    fig, ax = plt.subplots(figsize=(CHART_WIDTH_INCHES, CHART_HEIGHT_INCHES))
    fig.patch.set_facecolor(TV_BG)
    ax.set_facecolor(TV_BG)
    
    # X positions (0 to n-1)
    x_positions = np.arange(n)
    
    # Calculate body width
    body_width = CANDLE_BODY_WIDTH
    
    # Draw candles
    for i, (idx, row) in enumerate(weekly_df.iterrows()):
        o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
        
        # Determine color
        is_bullish = c >= o
        color = TV_GREEN if is_bullish else TV_RED
        
        # Body
        body_bottom = min(o, c)
        body_height = abs(c - o)
        if body_height < (h - l) * 0.005:
            # Doji — draw thin line
            body_height = (h - l) * 0.005
        
        # Draw body as filled rectangle
        rect = plt.Rectangle(
            (i - body_width / 2, body_bottom),
            body_width, body_height,
            facecolor=color,
            edgecolor=color,
            linewidth=0.5,
            zorder=3
        )
        ax.add_patch(rect)
        
        # Draw upper wick
        ax.plot([i, i], [max(o, c), h],
                color=color, linewidth=CANDLE_WICK_WIDTH, zorder=2)
        
        # Draw lower wick
        ax.plot([i, i], [min(o, c), l],
                color=color, linewidth=CANDLE_WICK_WIDTH, zorder=2)
    
    # ─── Y-axis on right side ───
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position('right')
    
    # Force more ticks on Y-axis (denser values) to fill gaps
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=12, min_n_ticks=8))
    
    # Format Y-axis prices with commas
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, p: _format_price(x))
    )
    
    # Y-axis tick label styling — dark text so labels are clearly visible
    ax.tick_params(axis='y', labelsize=8, labelcolor='#333333',
                   length=0, pad=4)

    
    # ─── Grid ───
    # TradingView uses very light horizontal grid lines (barely visible)
    ax.grid(axis='y', color='#F0F0F0', linewidth=0.4, alpha=0.5,
            linestyle='-', zorder=0)
    ax.grid(axis='x', visible=False)
    
    # ─── Current price horizontal line ───
    if current_close is not None:
        # Determine color based on last candle
        last_row = weekly_df.iloc[-1]
        is_bullish = last_row['Close'] >= last_row['Open']
        label_bg_color = TV_GREEN if is_bullish else TV_RED

        # Light dotted cyan/gray line across the chart (like TradingView)
        ax.axhline(y=current_close, color='#B2B5BE',
                    linewidth=0.6, linestyle='--', alpha=0.6, zorder=4)
        
        # Price label on the right edge — colored badge based on trend
        price_text = _format_price(current_close)
        
        # Short connecting line from chart edge to label
        ax.plot([n - 0.3, n + 0.2], [current_close, current_close],
                color=label_bg_color, linewidth=0.8, zorder=5,
                clip_on=False)
        
        # Draw label as colored box at right edge
        ax.annotate(
            price_text,
            xy=(n + 0.3, current_close),
            xycoords='data',
            fontsize=6.5,
            color=TV_PRICE_LABEL_TEXT,
            fontweight='bold',
            fontfamily='sans-serif',
            ha='left',
            va='center',
            bbox=dict(
                boxstyle='square,pad=0.25',
                facecolor=label_bg_color,
                edgecolor=label_bg_color,
                alpha=0.95
            ),
            clip_on=False,
            zorder=6
        )
    
    # ─── Axis limits ───
    all_highs = weekly_df['High'].values
    all_lows = weekly_df['Low'].values
    price_range = all_highs.max() - all_lows.min()
    # Reduced padding to eliminate extra extreme values
    y_padding = price_range * 0.02
    
    ax.set_ylim(all_lows.min() - y_padding, all_highs.max() + y_padding)
    ax.set_xlim(-0.8, n + 0.5)
    
    # ─── Remove X-axis (no date labels like TradingView zoomed view) ───
    ax.set_xticks([])
    ax.tick_params(axis='x', length=0)
    
    # ─── Spine styling ───
    for spine in ['top', 'bottom', 'left']:
        ax.spines[spine].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # ─── Tight layout ───
    # Y-axis is on the RIGHT side — need enough right margin for tick labels + price badge
    # right=0.78 → 22% of figure width (1.32" at 6") reserved for right-side Y labels
    fig.subplots_adjust(left=0.01, right=0.78, top=0.97, bottom=0.04)
    
    # Save with tight bbox so nothing is clipped at figure edge
    fig.savefig(output_path, dpi=CHART_DPI, facecolor=TV_BG,
                edgecolor='none', bbox_inches='tight')
    plt.close(fig)
    
    return output_path


# ═══════════════════════════════════════════════════════════════════
# CANDLESTICK PATTERN DETECTION
# ═══════════════════════════════════════════════════════════════════

def detect_candlestick_pattern(weekly_df: pd.DataFrame) -> str:
    """
    Detect the candlestick pattern of the most recent weekly candle.
    
    Implements recognition for:
    - Doji (open ≈ close, small body)
    - Hammer (small body at top, long lower shadow)
    - Inverted Hammer (small body at bottom, long upper shadow)
    - Bullish Engulfing (current bullish candle engulfs previous bearish)
    - Bearish Engulfing (current bearish candle engulfs previous bullish)
    - Marubozu (large body, minimal shadows)
    - Spinning Top (small body, equal shadows)
    - Default: bullish/bearish candle
    
    Args:
        weekly_df: DataFrame with weekly OHLC data (minimum 2 rows)
        
    Returns:
        Pattern name string (e.g., "Doji", "Hammer", "Bullish Engulfing")
    """
    if weekly_df is None or len(weekly_df) < 1:
        return "indecisive"
    
    last = weekly_df.iloc[-1]
    o, h, l, c = last['Open'], last['High'], last['Low'], last['Close']
    
    body = abs(c - o)
    full_range = h - l
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    
    is_bullish = c >= o
    
    # Avoid division by zero
    if full_range == 0:
        return "Doji"
    
    body_ratio = body / full_range
    
    # ─── Doji: body is very small relative to range ───
    if body_ratio < 0.15:
        # Dragonfly Doji (long lower shadow)
        if lower_shadow > 2 * body and upper_shadow < body:
            return "Dragonfly Doji"
        # Gravestone Doji (long upper shadow)
        if upper_shadow > 2 * body and lower_shadow < body:
            return "Gravestone Doji"
        return "Doji"
    
    # ─── Hammer: small body at top, long lower shadow ───
    if body_ratio < 0.35 and lower_shadow >= 2 * body and upper_shadow < body * 0.5:
        if is_bullish:
            return "Hammer"
        else:
            return "Hanging Man"
    
    # ─── Inverted Hammer: small body at bottom, long upper shadow ───
    if body_ratio < 0.35 and upper_shadow >= 2 * body and lower_shadow < body * 0.5:
        if is_bullish:
            return "Inverted Hammer"
        else:
            return "Shooting Star"
    
    # ─── Engulfing patterns (need previous candle) ───
    if len(weekly_df) >= 2:
        prev = weekly_df.iloc[-2]
        prev_o, prev_c = prev['Open'], prev['Close']
        prev_bullish = prev_c >= prev_o
        
        if is_bullish and not prev_bullish:
            if o <= prev_c and c >= prev_o:
                return "Bullish Engulfing"
        
        if not is_bullish and prev_bullish:
            if o >= prev_c and c <= prev_o:
                return "Bearish Engulfing"
    
    # ─── Marubozu: large body, minimal shadows ───
    if body_ratio > 0.85:
        if is_bullish:
            return "Bullish Marubozu"
        else:
            return "Bearish Marubozu"
    
    # ─── Spinning Top: small body with roughly equal shadows ───
    if body_ratio < 0.30:
        if upper_shadow > 0 and lower_shadow > 0:
            shadow_ratio = min(upper_shadow, lower_shadow) / max(upper_shadow, lower_shadow)
            if shadow_ratio > 0.5:
                return "Spinning Top"
    
    # ─── Default ───
    if is_bullish:
        return "bullish"
    else:
        return "bearish"


def classify_pattern_type(pattern: str) -> str:
    """
    Classify a pattern as 'bullish', 'bearish', or 'indecisive'.
    
    Used to determine the trend sentence and outlook.
    """
    bullish_patterns = {
        'Hammer', 'Inverted Hammer', 'Bullish Engulfing',
        'Bullish Marubozu', 'Dragonfly Doji', 'bullish'
    }
    bearish_patterns = {
        'Hanging Man', 'Shooting Star', 'Bearish Engulfing',
        'Bearish Marubozu', 'Gravestone Doji', 'bearish'
    }
    
    if pattern in bullish_patterns:
        return 'bullish'
    elif pattern in bearish_patterns:
        return 'bearish'
    else:
        return 'indecisive'


# ═══════════════════════════════════════════════════════════════════
# TECHNICAL COMMENTARY GENERATION
# ═══════════════════════════════════════════════════════════════════

def generate_technical_commentary(index_name: str,
                                   pattern: str,
                                   weekly_pct: Optional[float],
                                   sr_data: dict,
                                   is_benchmark: bool = False,
                                   benchmark_pct: Optional[float] = None,
                                   banknifty_pct: Optional[float] = None) -> List[str]:
    """
    Auto-generate 3 technical commentary bullet points for an index.
    
    Bullet 1: Trend + candlestick pattern description
    Bullet 2: Expected outlook for the coming week
    Bullet 3: Support and resistance levels (bold)
    
    Args:
        index_name: Display name (e.g., "NIFTY", "BANKNIFTY", "FINNIFTY")
        pattern: Detected candlestick pattern string
        weekly_pct: Weekly percentage change
        sr_data: S/R dict with keys s1, s2, r1, r2, close
        is_benchmark: Whether this is the benchmark index (NIFTY)
        
    Returns:
        List of 3 strings (bullet points)
    """
    pattern_type = classify_pattern_type(pattern)
    
    # Calculate relative performance
    rel_perf = "performed in line with"
    if weekly_pct is not None and benchmark_pct is not None:
        diff = weekly_pct - benchmark_pct
        if diff > 0.15:
            rel_perf = "outperformed"
        elif diff < -0.15:
            rel_perf = "underperformed"
            
    fin_perf = "performed in line with"
    if index_name == "FINNIFTY" and weekly_pct is not None and banknifty_pct is not None:
        diff_bn = weekly_pct - banknifty_pct
        if diff_bn > 0.15:
            fin_perf = "outperformed"
        elif diff_bn < -0.15:
            fin_perf = "underperformed"
    
    # Determine bias word
    if weekly_pct is not None:
        bias = "positive" if weekly_pct >= 0 else "negative"
    else:
        bias = "mixed"
    
    # ─── Bullet 1: Trend + pattern ───
    # Map pattern to display name for the sentence
    pattern_display = pattern
    if pattern in ('bullish', 'bearish'):
        pattern_display = f"{pattern}"
        formation = f"a {pattern} candlestick"
    elif pattern == 'indecisive':
        formation = "an indecisive candlestick"
    else:
        formation = f"{pattern.lower()} candlestick" if 'Doji' not in pattern else f"indecisive ({pattern})"
    
    # Determine formation text  
    if 'Doji' in pattern:
        formation_text = f"indecisive ({pattern}) candlestick formation"
    elif 'Engulfing' in pattern:
        formation_text = f"{pattern.lower()} candlestick formation"
    elif pattern in ('Hammer', 'Hanging Man', 'Shooting Star', 'Inverted Hammer'):
        formation_text = f"{pattern.lower()} candlestick formation"
    elif 'Marubozu' in pattern:
        direction = "bullish" if "Bullish" in pattern else "bearish"
        formation_text = f"a strong {direction} ({pattern.lower()}) candlestick formation"
    elif pattern == 'Spinning Top':
        formation_text = f"indecisive (spinning top) candlestick formation"
    elif pattern == 'bullish':
        formation_text = "a bullish candlestick formation"
    elif pattern == 'bearish':
        formation_text = "a bearish candlestick formation"
    else:
        formation_text = "an indecisive candlestick formation"
    
    if is_benchmark:
        b1 = (f"Benchmark index traded with a {bias} bias in the previous week "
              f"before closing with {formation_text} on the weekly chart")
    elif index_name == "BANK NIFTY":
        b1 = (f"Banking index {rel_perf} the benchmark and "
              f"closed with {formation_text} on the weekly chart")
    else:
        # FINNIFTY
        b1 = (f"{index_name} index {fin_perf} the banking index and "
              f"closed with {formation_text} on the weekly chart")
    
    # ─── Bullet 2: Outlook ───
    if pattern_type == 'bullish':
        outlook = "positive"
    elif pattern_type == 'bearish':
        outlook = "negative"
    else:
        outlook = "volatile"
    
    if is_benchmark:
        b2 = f"Benchmark index is likely to trade {outlook} in the coming week"
    elif index_name == "BANK NIFTY":
        b2 = f"Banking index is likely to perform in line with the Benchmark index in the coming week"
    else:
        b2 = f"{index_name} is likely to trade in line with the banking index in the coming week"
    
    # ─── Bullet 3: S/R levels ───
    s1 = sr_data.get('s1')
    s2 = sr_data.get('s2')
    r1 = sr_data.get('r1')
    r2 = sr_data.get('r2')
    
    s1_str = f"{s1:,}" if s1 is not None else "N/A"
    s2_str = f"{s2:,}" if s2 is not None else "N/A"
    r1_str = f"{r1:,}" if r1 is not None else "N/A"
    r2_str = f"{r2:,}" if r2 is not None else "N/A"
    
    if is_benchmark:
        b3 = f"Benchmark Index has support at {s2_str} \u2013 {s1_str} level and resistance at {r1_str}\u2013 {r2_str} level"
    elif index_name == "BANK NIFTY":
        b3 = f"Banking index has support at {s2_str}-{s1_str} and resistance at {r1_str} -{r2_str} level"
    else:
        b3 = f"{index_name} has support at {s2_str}-{s1_str} level and resistance at {r1_str}-{r2_str} level."
    
    return [b1, b2, b3]


# ═══════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════

def generate_all_charts(yf_cache: Dict[str, pd.DataFrame],
                        end_date: date,
                        output_dir: Optional[str] = None) -> Dict[str, str]:
    """
    Generate candlestick charts for all three indices.
    
    Args:
        yf_cache: Dict mapping display names to DataFrames
        end_date: End date for charts
        output_dir: Directory to save charts (default: temp dir)
        
    Returns:
        Dict mapping index key to PNG file path:
        {"NIFTY": "path/nifty_chart.png", ...}
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix='equity_charts_')
    
    os.makedirs(output_dir, exist_ok=True)
    
    chart_map = {
        "NIFTY": "NIFTY 50",
        "BANK NIFTY": "BANK NIFTY",
        "FINNIFTY": "FINNIFTY"
    }
    
    results = {}
    
    for chart_name, data_name in chart_map.items():
        df = yf_cache.get(data_name)
        
        print(f"  [CHART] Generating {chart_name} weekly candlestick chart...")
        
        if df is None or df.empty:
            print(f"    [WARN] No data for {chart_name}")
            weekly = pd.DataFrame()
            current_close = None
        else:
            weekly = aggregate_weekly_ohlc(df, end_date)
            if not weekly.empty:
                current_close = float(weekly['Close'].iloc[-1])
                print(f"    [OK] {len(weekly)} weekly candles, close={current_close:,.2f}")
            else:
                current_close = None
                print(f"    [WARN] Weekly aggregation produced no data")
        
        fname = f"{chart_name.lower().replace(' ', '_')}_weekly.png"
        fpath = os.path.join(output_dir, fname)
        
        generate_candlestick_chart(weekly, fpath, current_close)
        results[chart_name] = fpath
    
    return results


def generate_all_technical_data(yf_cache: Dict[str, pd.DataFrame],
                                 sr_rows: list,
                                 indices_data: list,
                                 end_date: date) -> Dict[str, dict]:
    """
    Generate chart paths, patterns, and commentary for all three indices.
    
    Args:
        yf_cache: Dict mapping display names to DataFrames
        sr_rows: S/R data from market data
        indices_data: Indices data from market data
        end_date: Report end date
        
    Returns:
        Dict mapping chart name to {chart_path, pattern, commentary, weekly_df}
    """
    chart_map = {
        "NIFTY": {"data_name": "NIFTY 50", "sr_name": "NIFTY", "is_benchmark": True},
        "BANK NIFTY": {"data_name": "BANK NIFTY", "sr_name": "BANK NIFTY", "is_benchmark": False},
        "FINNIFTY": {"data_name": "FINNIFTY", "sr_name": "FINNIFTY", "is_benchmark": False},
    }
    
    # Build SR lookup
    sr_lookup = {row['name']: row for row in sr_rows}
    
    # Build indices lookup for weekly pct
    idx_lookup = {d['name']: d for d in indices_data}
    
    results = {}
    
    for chart_name, cfg in chart_map.items():
        df = yf_cache.get(cfg['data_name'])
        
        # Weekly OHLC
        weekly = aggregate_weekly_ohlc(df, end_date) if df is not None and not df.empty else pd.DataFrame()
        
        # Pattern detection
        pattern = detect_candlestick_pattern(weekly) if not weekly.empty else "indecisive"
        
        # Weekly pct
        idx_data = idx_lookup.get(cfg['data_name'], {})
        weekly_pct = idx_data.get('pct')
        
        # S/R data
        sr = sr_lookup.get(cfg['sr_name'], {})
        
        # Get benchmark and banknifty percentages for relative performance logic
        benchmark_pct = idx_lookup.get("NIFTY 50", {}).get('pct')
        banknifty_pct = idx_lookup.get("BANK NIFTY", {}).get('pct')
        
        # Commentary
        commentary = generate_technical_commentary(
            chart_name, pattern, weekly_pct, sr, cfg['is_benchmark'],
            benchmark_pct=benchmark_pct, banknifty_pct=banknifty_pct
        )
        
        results[chart_name] = {
            'weekly_df': weekly,
            'pattern': pattern,
            'commentary': commentary,
        }
        
        print(f"  [{chart_name}] Pattern: {pattern}")
        for i, bullet in enumerate(commentary):
            print(f"    Bullet {i+1}: {bullet[:70]}...")
    
    return results


# ═══════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Quick test with synthetic data
    print("Testing chart generator with synthetic data...")
    
    dates = pd.date_range(end='2026-06-19', periods=100, freq='B')
    np.random.seed(42)
    
    base_price = 24000
    prices = [base_price]
    for _ in range(99):
        prices.append(prices[-1] + np.random.normal(0, 100))
    
    test_df = pd.DataFrame({
        'Open': [p + np.random.normal(0, 30) for p in prices],
        'High': [p + abs(np.random.normal(50, 30)) for p in prices],
        'Low': [p - abs(np.random.normal(50, 30)) for p in prices],
        'Close': prices,
    }, index=dates)
    
    weekly = aggregate_weekly_ohlc(test_df, date(2026, 6, 19))
    print(f"Weekly candles: {len(weekly)}")
    
    pattern = detect_candlestick_pattern(weekly)
    print(f"Pattern: {pattern}")
    
    output = os.path.join(os.path.dirname(__file__), "test_chart.png")
    generate_candlestick_chart(weekly, output, float(weekly['Close'].iloc[-1]))
    print(f"Chart saved: {output}")
    
    commentary = generate_technical_commentary(
        "NIFTY", pattern, 1.5,
        {"s1": 23500, "s2": 23200, "r1": 24500, "r2": 24800},
        is_benchmark=True
    )
    for i, b in enumerate(commentary):
        print(f"  Bullet {i+1}: {b}")
