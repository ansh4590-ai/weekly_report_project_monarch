"""
Data source integrations: Yahoo Finance, NSE, FII/DII
"""

import csv
import io
import contextlib
import math
import os
import time
import warnings
from datetime import date, timedelta
from typing import Optional, Tuple, Dict, Any

import pandas as pd

from config import (
    YF_SYMBOLS, NSE_NAME_MAP, NSELIB_MAP,
    YF_RETRY_COUNT, YF_RETRY_DELAY, NSE_TIMEOUT
)
from math_utils import round2

warnings.filterwarnings("ignore")

# ── Committed long-history cache dir (see load_long_history_cache below) ──
LONG_HISTORY_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "long_history"
)


# ══════════════════════════════════════════════════════════════════════════════
# YAHOO FINANCE
# ══════════════════════════════════════════════════════════════════════════════

def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize yfinance DataFrame:
    - Flatten MultiIndex columns
    - Remove duplicate columns
    - Strip timezone from DatetimeIndex

    Args:
        df: Raw yfinance DataFrame

    Returns:
        Normalized DataFrame
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # Flatten MultiIndex columns (yfinance >= 0.2.38)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    # Remove duplicate columns
    df = df.loc[:, ~df.columns.duplicated()]

    # Strip timezone from DatetimeIndex
    # Use tz_convert(None) for tz-aware index (not tz_localize)
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_convert(None)

    return df


def fetch_yahoo_finance(symbol: str,
                        start_date: date,
                        end_date: date,
                        retries: int = YF_RETRY_COUNT) -> pd.DataFrame:
    """
    Download OHLCV data from Yahoo Finance with retry logic.

    Tries two methods:
    1. yf.download() - avoids timezone metadata bug
    2. yf.Ticker().history() - fallback

    Args:
        symbol: Yahoo Finance ticker (e.g., "^NSEI")
        start_date: Start date (inclusive)
        end_date: End date (exclusive for yfinance)
        retries: Number of retry attempts

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume
        Empty DataFrame if all methods fail
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  [ERROR] yfinance not installed. Run: pip install yfinance")
        return pd.DataFrame()

    for attempt in range(1, retries + 1):
        # Method 1: yf.download()
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                raw = yf.download(
                    symbol, start=start_date, end=end_date,
                    progress=False, auto_adjust=False, actions=False
                )
            df = normalize_dataframe(raw)
            if not df.empty and "Close" in df.columns:
                return df
        except Exception as e:
            print(f"  [WARN] yf.download({symbol}) attempt {attempt}/{retries}: {e}")

        # Method 2: yf.Ticker().history() as fallback
        try:
            raw = yf.Ticker(symbol).history(start=start_date, end=end_date, auto_adjust=False)
            df = normalize_dataframe(raw)
            if not df.empty and "Close" in df.columns:
                return df
        except Exception as e:
            print(f"  [WARN] yf.Ticker({symbol}).history() attempt {attempt}/{retries}: {e}")

        if attempt < retries:
            time.sleep(YF_RETRY_DELAY)

    return pd.DataFrame()


def load_long_history_cache(display_name: str) -> pd.DataFrame:
    """
    Load a pre-fetched, git-committed long-history OHLC series for `display_name`.

    Why this exists
    ----------------
    nselib (the accurate primary source used for LONG_WINDOW_INDICES like
    FINNIFTY — see fetch_with_fallback) is blocked on Streamlit Cloud, so it
    times out there and the code falls through to Yahoo Finance. The problem:
    the YF fallback tickers for some indices (e.g. FINNIFTY's
    "NIFTY_FIN_SERVICE.NS" / "^CNXFIN") don't reliably return the full
    ~830-trading-day depth an EMA-200 needs — yfinance just silently hands
    back a shorter series instead of raising an error, so nothing "fails"
    and no warning fires, but every EMA computed from that series
    (9/21/50/100/200) comes out different — the longer windows worst of all,
    since they never converge. That's exactly why a report generated on the
    website can come out with correct NIFTY/BANK NIFTY EMAs (their YF
    tickers ^NSEI/^NSEBANK have full depth) but wrong FINNIFTY EMAs, while
    the same code run locally (where nselib reaches NSE directly) is correct
    for all three.

    This cache is the fix: a copy of the same accurate nselib series,
    refreshed weekly by save_snapshot.py (run locally, where nselib works)
    and committed to git, so the cloud deployment can use it instead of
    ever touching the incomplete YF series.

    Returns an empty DataFrame if no cache file exists yet for this name.
    """
    path = os.path.join(LONG_HISTORY_CACHE_DIR, f"{display_name}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
        df.set_index("Date", inplace=True)
        df.sort_index(inplace=True)
        for col in ["Close", "Open", "High", "Low"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        print(f"  [WARN] {display_name}: could not read long-history cache: {e}")
        return pd.DataFrame()


def fetch_with_fallback(display_name: str,
                        start_date: date,
                        end_date: date) -> Tuple[Optional[str], pd.DataFrame]:
    """
    Fetch data for a display name, trying all symbol candidates.

    Args:
        display_name: Display name (e.g., "NIFTY 50")
        start_date: Start date
        end_date: End date (will be extended by 1 day for yfinance)

    Returns:
        Tuple of (symbol_used, dataframe)
        Returns (None, empty_df) if all symbols fail
    """
    # 1. Try nselib first (most accurate for NSE official close)
    #    Wrapped in a 5-second timeout so it fails fast on Streamlit Cloud
    #    where outbound NSE requests are blocked.
    if display_name in NSELIB_MAP:
        import concurrent.futures

        nse_index_name = NSELIB_MAP[display_name]
        from_str = start_date.strftime("%d-%m-%Y")
        to_str = end_date.strftime("%d-%m-%Y")

        def _nselib_fetch():
            from nselib import capital_market
            return capital_market.index_data(
                index=nse_index_name,
                from_date=from_str,
                to_date=to_str,
            )

        try:
            print(f"  [INFO] {display_name}: Trying nselib (Primary) [{nse_index_name}]")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_nselib_fetch)
                df_nse = future.result(timeout=5)  # fail fast if NSE is unreachable

            if df_nse is not None and not df_nse.empty:
                df_nse["Date"] = pd.to_datetime(df_nse["TIMESTAMP"], format="%d-%b-%Y")
                df_nse.set_index("Date", inplace=True)

                # De-duplicate: nselib's bulk index-history call has been
                # observed to return overlapping rows for the same date when
                # queried across a wide range (like the ~1200-day EMA lookback
                # here). A duplicated day inflates its weight in the EMA
                # recursion — this shows up almost entirely in short-span
                # EMAs (9/21-day), since long-span EMAs are dominated by
                # years of other data and barely notice it.
                dup_count = int(df_nse.index.duplicated().sum())
                if dup_count:
                    print(f"  [WARN] {display_name}: nselib returned {dup_count} duplicate date(s) — "
                          f"dropping duplicates (keeping last).")
                    df_nse = df_nse[~df_nse.index.duplicated(keep="last")]

                df_nse.sort_index(inplace=True)
                df_nse = df_nse.rename(columns={
                    "CLOSE_INDEX_VAL": "Close",
                    "OPEN_INDEX_VAL": "Open",
                    "HIGH_INDEX_VAL": "High",
                    "LOW_INDEX_VAL": "Low",
                })
                for col in ["Close", "Open", "High", "Low"]:
                    df_nse[col] = pd.to_numeric(df_nse[col], errors="coerce")

                # Gap check: flag if the most recent stretch has an unusually
                # large jump between consecutive trading rows (a real market
                # holiday run is at most ~4 calendar days; anything bigger in
                # the last ~30 rows suggests missing data, which would
                # silently distort the short EMAs the same way duplicates do).
                if len(df_nse) >= 2:
                    recent = df_nse.tail(30)
                    gaps = recent.index.to_series().diff().dt.days.dropna()
                    if not gaps.empty and gaps.max() > 5:
                        bad_idx = gaps.idxmax()
                        print(f"  [WARN] {display_name}: unusually large gap ({int(gaps.max())} days) "
                              f"in nselib data ending {bad_idx.date()} — recent EMAs (9/21-day) may be "
                              f"affected. Check nselib's raw output for missing trading days.")

                return f"nselib:{nse_index_name}", df_nse

        except concurrent.futures.TimeoutError:
            print(f"  [WARN] {display_name}: nselib timed out — NSE likely unreachable (cloud). "
                  f"Trying committed long-history cache before YF.")
        except Exception as e:
            print(f"  [WARN] {display_name}: nselib failed: {e}. "
                  f"Trying committed long-history cache before YF.")

        # 1b. Committed long-history cache (accurate nselib data, snapshotted
        #     locally and checked into git — see load_long_history_cache).
        #     Only reached when live nselib above didn't already return.
        #     Keep the full cached series (not trimmed to start/end) since
        #     the EMA calculation needs the long lookback, not just the
        #     report week.
        cached = load_long_history_cache(display_name)
        if not cached.empty:
            print(f"  [OK] {display_name}: using committed long-history cache ({len(cached)} rows)")
            return f"cache:{nse_index_name}", cached
        else:
            print(f"  [INFO] {display_name}: no long-history cache file found. Falling back to YF.")

    # 2. Try Yahoo Finance fallback
    candidates = YF_SYMBOLS.get(display_name, [])

    # De-duplicate while preserving order
    unique_candidates = list(dict.fromkeys(candidates))

    # Try each Yahoo Finance symbol
    for symbol in unique_candidates:
        df = fetch_yahoo_finance(symbol, start_date, end_date)
        if not df.empty:
            # Verify the data actually covers the report period.
            # YF sometimes returns only pre-week rows (e.g. July 17) + today's
            # live NaN — in that case last_dt appears recent but the actual report
            # week is completely missing. get_close_on_date would then silently
            # fall back to the previous week's close, producing wrong percentages.
            try:
                report_mask = (
                    (df.index.date >= start_date) &
                    (df.index.date <= end_date)
                )
                close_in_window = df.loc[report_mask, "Close"].dropna()
                if close_in_window.empty:
                    print(
                        f"  [WARN] {display_name}: YF {symbol} has NO data in "
                        f"report window [{start_date} → {end_date}] — rejecting."
                    )
                    continue
            except Exception:
                pass  # if the coverage check itself errors, accept the data
            return symbol, df
    # All methods failed
    if not unique_candidates and display_name not in NSELIB_MAP:
        print(f"  [WARN] {display_name}: No symbol defined")
    else:
        print(f"  [FAIL] {display_name}: All symbols failed")

    return None, pd.DataFrame()


def get_close_on_date(df: pd.DataFrame, target_date: date) -> Optional[float]:
    """
    Get last non-NaN Close value on or before target_date.

    Args:
        df: DataFrame with DatetimeIndex and Close column
        target_date: Target date

    Returns:
        Close value (float) or None if no data
    """
    if df is None or df.empty or "Close" not in df.columns:
        return None

    ts = pd.Timestamp(target_date)
    subset = df[df.index <= ts].copy()

    # Drop rows where Close is NaN — yfinance occasionally inserts NaN rows
    subset = subset.dropna(subset=["Close"])

    if subset.empty:
        return None

    val = float(subset["Close"].iloc[-1])
    if math.isnan(val) or math.isinf(val):
        return None
    return val


def get_close_from_bhavcopy(target_friday: date, disp_name: str) -> Optional[float]:
    """
    Read the spot index close for `disp_name` from the locally cached
    derivatives Bhavcopy CSV for `target_friday`.

    This is the most reliable fallback for cloud deployments (Streamlit Cloud)
    where NSE API calls are blocked by NSE's IP geo-restrictions. The bhavcopy
    files are committed to git and always available alongside the codebase.

    Args:
        target_friday: The Friday date whose close we need.
        disp_name:     Our display name, e.g. "FINNIFTY", "NIFTY 50".

    Returns:
        float close, or None if bhavcopy not found / symbol not in file.
    """
    from config import DATA_DIR, BHAVCOPY_INDEX_MAP
    bhav_sym = BHAVCOPY_INDEX_MAP.get(disp_name)
    if not bhav_sym:
        return None  # index not tracked in derivatives bhavcopy

    # Walk back up to 5 weekdays looking for the nearest available bhavcopy
    day = target_friday
    for _ in range(5):
        if day.weekday() >= 5:          # skip weekends
            day -= timedelta(days=1)
            continue
        bhav_path = os.path.join(
            DATA_DIR, str(day.year), day.strftime("%Y%m%d"), "bhavcopy.csv"
        )
        if os.path.exists(bhav_path):
            try:
                df_b = pd.read_csv(bhav_path, low_memory=False)
                sub = df_b[df_b["TckrSymb"] == bhav_sym]
                if not sub.empty:
                    val = float(sub["UndrlygPric"].iloc[0])
                    print(f"  [BHAVCOPY] {disp_name}: {val} (from {day})")
                    return val
            except Exception as exc:
                print(f"  [WARN] Bhavcopy read error for {disp_name} on {day}: {exc}")
        day -= timedelta(days=1)

    return None


def get_ohlc_week(df: pd.DataFrame,
                  after_date: date,
                  on_or_before_date: date) -> list:
    """
    Extract OHLC data for trading days in the window.

    Args:
        df: DataFrame with OHLC columns
        after_date: Start date (exclusive)
        on_or_before_date: End date (inclusive)

    Returns:
        List of dicts: [{"date": date, "open": float, "high": float,
                         "low": float, "close": float}, ...]
    """
    if df is None or df.empty:
        return []

    ts_after = pd.Timestamp(after_date)
    ts_before = pd.Timestamp(on_or_before_date)

    subset = df[(df.index > ts_after) & (df.index <= ts_before)]

    rows = []
    has_high = "High" in df.columns
    has_low = "Low" in df.columns
    has_open = "Open" in df.columns

    for ts, row in subset.iterrows():
        close_val = float(row["Close"])
        rows.append({
            "date": ts.date(),
            "open": float(row["Open"]) if has_open else close_val,
            "high": float(row["High"]) if has_high else close_val,
            "low": float(row["Low"]) if has_low else close_val,
            "close": close_val,
        })

    return rows


# ══════════════════════════════════════════════════════════════════════════════
# NSE LIVE SNAPSHOT
# ══════════════════════════════════════════════════════════════════════════════

def create_nse_session():
    """
    Create requests session with NSE-compatible headers.

    Returns:
        requests.Session object with cookies warmed up
    """
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    })

    # Warm up session (get cookies)
    try:
        session.get("https://www.nseindia.com", timeout=NSE_TIMEOUT)
    except Exception as e:
        print(f"  [WARN] NSE session warm-up failed: {e}")

    return session


def fetch_nse_snapshot(session) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Fetch NSE allIndices live snapshot.

    Returns dict: display_name → {"close": float, "pct": float}

    Note: The "pct" field is DAILY percentage change, not weekly.
    Do not use for weekly calculations.

    Args:
        session: requests.Session object

    Returns:
        Dict mapping display names to {"close": float, "pct": float}
        Empty dict if fetch fails
    """
    result = {}

    urls = [
        "https://www.nseindia.com/api/allIndices",
        "https://www.nseindia.com/api/v2/allIndices"
    ]

    for url in urls:
        try:
            resp = session.get(url, timeout=NSE_TIMEOUT)
            print(f"  [INFO] NSE allIndices -> HTTP {resp.status_code}")

            if resp.status_code != 200:
                print(f"  [WARN] Response body: {resp.text[:300]}")
                continue

            data = resp.json().get("data", [])

            for item in data:
                nse_name = item.get("index", "").strip()
                display_name = NSE_NAME_MAP.get(nse_name)

                if not display_name:
                    continue

                last_val = item.get("last") or item.get("previousClose")
                pct_val = item.get("percentChange")

                try:
                    result[display_name] = {
                        "close": round2(float(last_val)) if last_val is not None else None,
                        "pct": round2(float(pct_val)) if pct_val is not None else None,
                    }
                except (TypeError, ValueError):
                    pass

            if result:
                print(f"  [OK] NSE snapshot: {len(result)} indices fetched")
                return result

        except Exception as e:
            print(f"  [WARN] NSE allIndices error: {e}")

    print("  [WARN] NSE snapshot unavailable — relying entirely on Yahoo Finance")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# FII / DII
# ══════════════════════════════════════════════════════════════════════════════

def _parse_nse_fiidii_date(raw) -> Optional[date]:
    if raw is None:
        return None
    from datetime import datetime
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None

def _scrape_nse_fiidii_direct(session=None) -> Optional[Dict[str, Any]]:
    """Scrape the latest FII/DII figures from NSE's trade-react endpoint."""
    own_session = session is None
    if own_session:
        session = create_nse_session()

    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    try:
        resp = session.get(url, timeout=NSE_TIMEOUT)
        if resp.status_code != 200:
            return None

        data = resp.json()
        if not data:
            return None

        fii_net, dii_net, data_date = None, None, None

        for row in data:
            category = str(row.get("category", "")).upper()
            raw_val = row.get("netValue")
            if raw_val is None:
                continue
            try:
                net_val = float(raw_val)
            except (TypeError, ValueError):
                continue

            net_int = int(round(net_val))
            if "FII" in category or "FPI" in category:
                fii_net = net_int if fii_net is None else fii_net + net_int
                data_date = data_date or row.get("date")
            elif "DII" in category:
                dii_net = net_int if dii_net is None else dii_net + net_int
                data_date = data_date or row.get("date")

        if fii_net is None or dii_net is None:
            return None

        return {
            "fii": fii_net,
            "dii": dii_net,
            "data_date": _parse_nse_fiidii_date(data_date),
            "data_date_raw": data_date,
        }

    except Exception:
        return None

    finally:
        if own_session:
            try:
                session.close()
            except Exception:
                pass

def fetch_fii_dii(start_date: date, end_date: date) -> Dict[str, Any]:
    print("\n[INFO] Fetching FII/DII Data...")
    print("  [+] Scraping NSE directly (Latest Trading Day snapshot)...")
    scraped = _scrape_nse_fiidii_direct()
    if scraped is not None:
        print(f"  [OK] Live (direct scrape): FII={scraped['fii']:,} Cr, DII={scraped['dii']:,} Cr  [as of {scraped['data_date_raw']}]")
        return {"fii": scraped["fii"], "dii": scraped["dii"], "is_weekly": False, "data_date": scraped["data_date"]}
    
    print("  [+] Direct scrape failed — falling back to nsepython...")
    try:
        import nsepython
        df = nsepython.nse_fiidii()
        if df is not None and not df.empty:
            fii_rows = df[df["category"].str.contains("FII|FPI", na=False, regex=True)]
            dii_rows = df[df["category"].str.contains("DII", na=False)]
            fii_net = int(round(pd.to_numeric(fii_rows["netValue"], errors="coerce").sum()))
            dii_net = int(round(pd.to_numeric(dii_rows["netValue"], errors="coerce").sum()))
            data_date_raw = df["date"].iloc[0] if "date" in df.columns else None
            data_date = _parse_nse_fiidii_date(data_date_raw)
            print(f"  [OK] Live (nsepython): FII={fii_net:,} Cr, DII={dii_net:,} Cr  [as of {data_date_raw}]")
            return {"fii": fii_net, "dii": dii_net, "is_weekly": False, "data_date": data_date}
    except Exception as e:
        print(f"  [FAIL] nsepython fallback also failed: {e}")
    print("  [WARN] FII/DII data unavailable from either source.")
    return {"fii": None, "dii": None, "is_weekly": False, "data_date": None}

FII_DII_LOG_FILENAME = "fii_dii_history.csv"


def _fii_dii_log_path() -> str:
    """Return the absolute path to the FII/DII history CSV file."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), FII_DII_LOG_FILENAME)


def log_daily_fii_dii(snapshot: Dict[str, Any]) -> None:
    """Append or update a single day's FII/DII values in the history CSV."""
    data_date = snapshot.get("data_date")
    fii = snapshot.get("fii")
    dii = snapshot.get("dii")

    if data_date is None or fii is None or dii is None:
        print("  [WARN] Skipping FII/DII log write — incomplete snapshot.")
        return

    path = _fii_dii_log_path()
    rows = []

    # Read existing rows, skipping the date we are about to write
    if os.path.exists(path):
        with open(path, "r", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("date") != data_date.isoformat():
                    rows.append(row)

    rows.append({"date": data_date.isoformat(), "fii": fii, "dii": dii})
    rows.sort(key=lambda r: r["date"])

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "fii", "dii"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  [OK] Logged FII/DII for {data_date.isoformat()} to {FII_DII_LOG_FILENAME}")

def get_fii_dii_for_date(target_date: date) -> Dict[str, Any]:
    """
    Return FII/DII for a single date.
    - If target_date is today: scrapes live from NSE and saves to cache.
    - Otherwise: reads from the history CSV cache.
    """
    today = date.today()

    # Live scrape for today
    if target_date == today:
        snapshot = fetch_fii_dii(today, today)
        if snapshot.get("fii") is not None:
            log_daily_fii_dii(snapshot)
            return {
                "fii": snapshot["fii"],
                "dii": snapshot["dii"],
                "source": "live",
                "data_date": snapshot.get("data_date", today),
            }

    # Read from cache
    path = _fii_dii_log_path()
    if os.path.exists(path):
        with open(path, "r", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("date") == target_date.isoformat():
                    return {
                        "fii": int(float(row["fii"])),
                        "dii": int(float(row["dii"])),
                        "source": "log",
                        "data_date": target_date,
                    }

    print(f"  [WARN] No FII/DII value available for {target_date.isoformat()}")
    return {"fii": None, "dii": None, "source": "unavailable", "data_date": target_date}


def get_weekly_fii_dii(prev_friday: date, curr_friday: date, expected_days: int = 5) -> Dict[str, Any]:
    """
    Sum all logged FII/DII values for the week (prev_friday < date <= curr_friday).
    Returns a dict with totals, days_covered, and whether the week is complete.
    """
    from datetime import datetime

    path = _fii_dii_log_path()
    if not os.path.exists(path):
        print("  [WARN] No FII/DII history log found yet — nothing to sum.")
        return {"fii": None, "dii": None, "is_weekly": False, "days_covered": 0, "is_complete": False}

    fii_total, dii_total, days_covered = 0, 0, 0

    with open(path, "r", newline="") as f:
        for row in csv.DictReader(f):
            try:
                row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if prev_friday < row_date <= curr_friday:
                fii_total += int(float(row["fii"]))
                dii_total += int(float(row["dii"]))
                days_covered += 1

    if days_covered == 0:
        return {"fii": None, "dii": None, "is_weekly": False, "days_covered": 0, "is_complete": False}

    is_complete = days_covered >= expected_days
    print(
        f"  [OK] Weekly FII/DII from log: FII={fii_total:,} Cr, DII={dii_total:,} Cr "
        f"({days_covered}/{expected_days} trading days logged)"
    )
    return {
        "fii": fii_total,
        "dii": dii_total,
        "is_weekly": True,
        "days_covered": days_covered,
        "expected_days": expected_days,
        "is_complete": is_complete,
    }


def get_fii_dii_data(start_date: date, end_date: date) -> pd.DataFrame:
    """
    Return a per-day FII/DII DataFrame for the window (start_date, end_date].

    Each row has columns: date, fii, dii, status.
    Status values:
        "weekend"  — Saturday/Sunday, no market data expected.
        "cached"   — value read from fii_dii_history.csv.
        "live"     — scraped from NSE just now (date == today) and saved to cache.
        "missing"  — not in cache and not today, so we can't fetch it.

    Uses file locking when reading/writing the CSV to support concurrent
    Streamlit sessions without data corruption.

    Args:
        start_date: Window start (exclusive — rows start from start_date + 1 day)
        end_date:   Window end (inclusive)

    Returns:
        pd.DataFrame with columns [date, fii, dii, status]
    """
    import csv
    import os

    path = _fii_dii_log_path()
    today = date.today()

    # ── Read the CSV cache (with file lock) ──────────────────────────────
    cache = {}  # date_iso -> {"fii": int, "dii": int}

    if os.path.exists(path):
        try:
            with open(path, "r", newline="") as f:
                for row in csv.DictReader(f):
                    d = row.get("date", "").strip()
                    if d:
                        try:
                            cache[d] = {
                                "fii": int(float(row["fii"])),
                                "dii": int(float(row["dii"])),
                            }
                        except (ValueError, KeyError):
                            pass
        except Exception:
            pass

    # ── Walk the window day by day ───────────────────────────────────────
    rows = []
    day = start_date + timedelta(days=1)

    while day <= end_date:
        iso = day.isoformat()

        if day.weekday() >= 5:
            rows.append({"date": day, "fii": float("nan"), "dii": float("nan"),
                         "status": "weekend"})
        elif iso in cache:
            rows.append({"date": day, "fii": cache[iso]["fii"],
                         "dii": cache[iso]["dii"], "status": "cached"})
        elif day == today:
            # Attempt live scrape
            scraped = _scrape_nse_fiidii_direct()
            if scraped is not None and scraped.get("fii") is not None:
                # Write to cache with file lock
                _write_to_cache(path, iso, scraped["fii"], scraped["dii"])
                rows.append({"date": day, "fii": scraped["fii"],
                             "dii": scraped["dii"], "status": "live"})
            else:
                rows.append({"date": day, "fii": float("nan"),
                             "dii": float("nan"), "status": "missing"})
        else:
            rows.append({"date": day, "fii": float("nan"),
                         "dii": float("nan"), "status": "missing"})

        day += timedelta(days=1)

    return pd.DataFrame(rows, columns=["date", "fii", "dii", "status"])


def _write_to_cache(path: str, date_iso: str, fii: int, dii: int) -> None:
    """
    Append or update a single row in fii_dii_history.csv.
    Uses an exclusive file lock during the write to prevent corruption
    when multiple Streamlit sessions run at the same time.
    """
    # Read existing rows, excluding the date we are about to write
    rows = []
    if os.path.exists(path):
        with open(path, "r", newline="") as f:
            _lock_file_exclusive(f)
            for row in csv.DictReader(f):
                if row.get("date") != date_iso:
                    rows.append(row)

    rows.append({"date": date_iso, "fii": fii, "dii": dii})
    rows.sort(key=lambda r: r["date"])

    with open(path, "w", newline="") as f:
        _lock_file_exclusive(f)
        writer = csv.DictWriter(f, fieldnames=["date", "fii", "dii"])
        writer.writeheader()
        writer.writerows(rows)


def _lock_file_exclusive(f) -> None:
    """
    Acquire an exclusive lock on an open file handle.
    Falls back silently if the filesystem does not support locking.
    """
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
    except Exception:
        pass  # Proceed without lock — better than failing outright


# ══════════════════════════════════════════════════════════════════════════════
# CONSTITUENT STOCKS
# ══════════════════════════════════════════════════════════════════════════════

# NOTE: Full Nifty 50 and Bank Nifty list for accurate top gainers calculation
NIFTY50_SAMPLE = {
    "ADANIENT": "ADANIENT.NS", "ADANIPORTS": "ADANIPORTS.NS", "APOLLOHOSP": "APOLLOHOSP.NS",
    "ASIANPAINT": "ASIANPAINT.NS", "AXISBANK": "AXISBANK.NS", "BAJAJ_AUTO": "BAJAJ-AUTO.NS",
    "BAJFINANCE": "BAJFINANCE.NS", "BAJAJFINSV": "BAJAJFINSV.NS", "BEL": "BEL.NS",
    "BHARTIARTL": "BHARTIARTL.NS", "CIPLA": "CIPLA.NS", "COALINDIA": "COALINDIA.NS",
    "DRREDDY": "DRREDDY.NS", "EICHERMOT": "EICHERMOT.NS", "ETERNAL": "ETERNAL.NS",
    "GRASIM": "GRASIM.NS", "HCLTECH": "HCLTECH.NS", "HDFCBANK": "HDFCBANK.NS",
    "HDFCLIFE": "HDFCLIFE.NS", "HINDALCO": "HINDALCO.NS", "HINDUNILVR": "HINDUNILVR.NS",
    "ICICIBANK": "ICICIBANK.NS", "ITC": "ITC.NS", "INFY": "INFY.NS", "INDIGO": "INDIGO.NS",
    "JSWSTEEL": "JSWSTEEL.NS", "JIOFIN": "JIOFIN.NS", "KOTAKBANK": "KOTAKBANK.NS",
    "LT": "LT.NS", "M&M": "M&M.NS", "MARUTI": "MARUTI.NS", "MAXHEALTH": "MAXHEALTH.NS",
    "NTPC": "NTPC.NS", "NESTLEIND": "NESTLEIND.NS", "ONGC": "ONGC.NS", "POWERGRID": "POWERGRID.NS",
    "RELIANCE": "RELIANCE.NS", "SBILIFE": "SBILIFE.NS", "SHRIRAMFIN": "SHRIRAMFIN.NS",
    "SBIN": "SBIN.NS", "SUNPHARMA": "SUNPHARMA.NS", "TCS": "TCS.NS", "TATACONSUM": "TATACONSUM.NS",
    "TMPV": "TMPV.NS", "TATASTEEL": "TATASTEEL.NS", "TECHM": "TECHM.NS", "TITAN": "TITAN.NS",
    "TRENT": "TRENT.NS", "ULTRACEMCO": "ULTRACEMCO.NS", "WIPRO": "WIPRO.NS"
}

BANKNIFTY_SAMPLE = {
    "AUBANK": "AUBANK.NS", "AXISBANK": "AXISBANK.NS", "BANKBARODA": "BANKBARODA.NS",
    "FEDERALBNK": "FEDERALBNK.NS", "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS", "IDFCFIRSTB": "IDFCFIRSTB.NS", "INDUSINDBK": "INDUSINDBK.NS",
    "KOTAKBANK": "KOTAKBANK.NS", "PNB": "PNB.NS", "SBIN": "SBIN.NS"
}


def fetch_constituents(prev_friday: date,
                       curr_friday: date) -> Dict[str, Any]:
    """
    Fetch top 2 gainers and losers for Nifty 50 and Bank Nifty constituents.

    NOTE: Uses representative sample, not full constituent list.
    For production, fetch live constituent list from NSE.

    Args:
        prev_friday: Previous week Friday
        curr_friday: Current week Friday

    Returns:
        Dict with keys: nifty_gainers, nifty_losers,
                       banknifty_gainers, banknifty_losers
        Each value is list of {"name": str, "pct": float}
    """
    from math_utils import calculate_weekly_pct

    fetch_from = prev_friday - timedelta(days=7)
    fetch_to = curr_friday + timedelta(days=1)

    def _stock_weekly_pct(symbol: str) -> Optional[float]:
        """Calculate weekly % for a single stock."""
        df = fetch_yahoo_finance(symbol, fetch_from, fetch_to)
        if df.empty:
            return None

        prev_close = get_close_on_date(df, prev_friday)
        curr_close = get_close_on_date(df, curr_friday)

        return calculate_weekly_pct(prev_close, curr_close)

    result = {}

    for group_name, tickers in [("nifty", NIFTY50_SAMPLE),
                                 ("banknifty", BANKNIFTY_SAMPLE)]:
        data = []

        for name, symbol in tickers.items():
            pct = _stock_weekly_pct(symbol)
            if pct is not None:
                data.append({"name": name, "pct": pct})

        # Sort by performance
        gainers = sorted(data, key=lambda x: x["pct"], reverse=True)[:2]
        losers = sorted(data, key=lambda x: x["pct"])[:2]

        result[f"{group_name}_gainers"] = gainers
        result[f"{group_name}_losers"] = losers

        print(f"  [INFO] {group_name.upper()}: {len(data)}/{len(tickers)} stocks fetched")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL MARKETS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_global_markets(prev_friday: date,
                         curr_friday: date) -> Dict[str, Optional[float]]:
    """
    Fetch weekly percentage change for DJIA and STOXX 600.

    Args:
        prev_friday: Previous week Friday
        curr_friday: Current week Friday

    Returns:
        Dict with keys "djia" and "stoxx" (percentage changes)
    """
    from math_utils import calculate_weekly_pct

    fetch_from = prev_friday - timedelta(days=7)
    fetch_to = curr_friday + timedelta(days=1)

    result = {}

    # Try STOXX with fallback symbols
    stoxx_symbols = ["^STOXX", "^STOXX50E", "STOXX.L"]

    for key, symbols in [("djia", ["^DJI"]), ("stoxx", stoxx_symbols)]:
        df = None

        # Try each symbol until one works
        for symbol in symbols:
            df = fetch_yahoo_finance(symbol, fetch_from, fetch_to)
            if not df.empty:
                print(f"  [OK] {key.upper()}: using {symbol}")
                break

        if df is None or df.empty:
            result[key] = None
            print(f"  [FAIL] {key.upper()}: No data available")
            continue

        prev_close = get_close_on_date(df, prev_friday)
        curr_close = get_close_on_date(df, curr_friday)

        result[key] = calculate_weekly_pct(prev_close, curr_close)

    return result

# ══════════════════════════════════════════════════════════════════════════════
# DERIVATIVES (OPTION CHAIN & BHAVCOPY PARSER)
# ══════════════════════════════════════════════════════════════════════════════

def _get_ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n:02d}{suffix}"

def fetch_option_chain_live(report_date: date, target_friday: date = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Fetches the live option chain from the NSE API for NIFTY and BANKNIFTY.
    Requires to be run on Friday evening/weekend to capture End-of-Week exact stats.
    """
    from datetime import datetime
    session = create_nse_session()
    if not session:
        print("  [WARN] Could not establish NSE session for Option Chain API.")
        return None
        
    pcr_date = target_friday if target_friday else report_date
    pcr_date_str = pcr_date.strftime("%b %d")
    derivatives_data = {}
    
    print("  [INFO] Attempting to fetch Live Option Chain from NSE API...")
    
    for idx_key, ticker in [("NIFTY", "NIFTY"), ("BANK NIFTY", "BANKNIFTY")]:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={ticker}"
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                print(f"    [WARN] Failed to fetch {ticker} options live (Status: {resp.status_code})")
                continue
                
            data = resp.json()
            records = data.get("records", {}).get("data", [])
            if not records:
                print(f"    [WARN] No records found in {ticker} live JSON.")
                continue
                
            # Filter CE and PE records
            ce_records = [r["CE"] for r in records if "CE" in r]
            pe_records = [r["PE"] for r in records if "PE" in r]
            
            # Find unique expiry dates
            expiries = sorted(list(set([r.get("expiryDate") for r in ce_records + pe_records if "expiryDate" in r])))
            if not expiries:
                print(f"    [WARN] No expiry dates found for {ticker}.")
                continue
                
            valid_expiries = []
            for d_str in expiries:
                try:
                    dt = datetime.strptime(d_str, "%d-%m-%Y")
                    valid_expiries.append((dt, d_str))
                except ValueError:
                    try:
                        dt = datetime.strptime(d_str, "%d-%b-%Y")
                        valid_expiries.append((dt, d_str))
                    except ValueError:
                        pass
            
            if not valid_expiries:
                print(f"    [WARN] Could not parse expiry dates for {ticker}.")
                continue
                
            valid_expiries.sort(key=lambda x: x[0])
            near_dt, near_expiry_str = valid_expiries[0]
            
            # Filter near expiry
            near_ce = [r for r in ce_records if r.get("expiryDate") == near_expiry_str]
            near_pe = [r for r in pe_records if r.get("expiryDate") == near_expiry_str]
            
            if not near_ce or not near_pe:
                print(f"    [WARN] Incomplete near expiry records for {ticker}.")
                continue
                
            # Max OI and Max OI Add (from near expiry)
            max_call = max(near_ce, key=lambda x: x.get("openInterest", 0))
            max_put = max(near_pe, key=lambda x: x.get("openInterest", 0))
            
            max_call_add = max(near_ce, key=lambda x: x.get("changeinOpenInterest", 0))
            max_put_add = max(near_pe, key=lambda x: x.get("changeinOpenInterest", 0))
            
            # PCR: CUMULATIVE across ALL expiries — matches firm's "Nifty Option all expiry"
            # formula: Put OI / Call OI.  Near-expiry-only PCR gives a different (lower)
            # figure and contradicts the bhavcopy image's computed value.
            total_ce_oi_all = sum(r.get("openInterest", 0) for r in ce_records)
            total_pe_oi_all = sum(r.get("openInterest", 0) for r in pe_records)
            pcr = float(total_pe_oi_all / total_ce_oi_all) if total_ce_oi_all > 0 else 0.0
            
            # Expiry string format e.g., 14th Jul
            expiry_str = f"{_get_ordinal(near_dt.day)} {near_dt.strftime('%b')}"
            
            derivatives_data[idx_key] = {
                "oi_add_c": str(int(max_call_add.get("strikePrice", 0))),
                "oi_add_p": str(int(max_put_add.get("strikePrice", 0))),
                "call_oi": str(int(max_call.get("strikePrice", 0))),
                "put_oi": str(int(max_put.get("strikePrice", 0))),
                "pcr": round(pcr, 2),
                "expiry": expiry_str,
                "pcr_date": pcr_date_str
            }
            
            print(f"    [OK] Live {idx_key}: PCR={pcr:.2f}, Exp={expiry_str}")
        except Exception as e:
            print(f"    [WARN] Exception parsing {idx_key} live options: {e}")
            
    if not derivatives_data:
        return None
        
    return derivatives_data

def parse_bhavcopy_derivatives(report_date: date, target_friday: date = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Locate, load and parse the NSE FO BhavCopy CSV for the report week.

    File discovery order
    --------------------
    1. Structured local cache  data/YYYY/YYYYMMDD/bhavcopy.csv
    2. Loose BhavCopy CSVs in the script's root directory  (legacy / manual drop)
    3. Auto-download from NSE archives via HistoricalDerivativeFetcher
    """
    import os
    import re
    import glob
    import pandas as pd
    from datetime import datetime
    from config import DATA_DIR
    from nse_downloader import HistoricalDerivativeFetcher

    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Report week window: Mon → Fri (report_date is the end Sunday)
    week_end   = report_date - timedelta(days=1)   # Saturday → use Friday
    week_start = report_date - timedelta(days=6)   # Previous Monday

    matched_file: Optional[str] = None

    # ── Tier 1: structured cache ───────────────────────────────────────────────
    # Walk back from Friday, checking data/YYYY/YYYYMMDD/bhavcopy.csv
    day = report_date - timedelta(days=2)           # Friday
    for _ in range(5):
        if day.weekday() < 5:                       # weekday only
            candidate = os.path.join(
                DATA_DIR,
                str(day.year),
                day.strftime("%Y%m%d"),
                "bhavcopy.csv"
            )
            if os.path.exists(candidate):
                print(f"  [CACHE HIT] Structured cache: {candidate} (dated {day})")
                matched_file = candidate
                break
        day -= timedelta(days=1)

    # ── Tier 2: loose CSVs in root dir (legacy manual drop) ───────────────────
    if not matched_file:
        date_pattern = re.compile(
            r'BhavCopy_NSE_FO_\d+_\d+_\d+_(\d{8})_F_\d+\.csv', re.IGNORECASE
        )
        loose_files = glob.glob(os.path.join(base_dir, "BhavCopy_NSE_FO_*.csv"))
        for f in sorted(loose_files, reverse=True):
            m = date_pattern.search(os.path.basename(f))
            if not m:
                continue
            try:
                file_date = datetime.strptime(m.group(1), "%Y%m%d").date()
            except ValueError:
                continue
            if week_start <= file_date <= week_end:
                print(f"  [INFO] Using loose BhavCopy: {os.path.basename(f)} (dated {file_date})")
                matched_file = f
                break

    # ── Tier 3: auto-download from NSE archives ────────────────────────────────
    if not matched_file:
        print("  [INFO] No local BhavCopy found. Attempting NSE archive download...")
        fetcher = HistoricalDerivativeFetcher(base_dir)
        matched_file = fetcher.get(report_date)

    if not matched_file:
        print("  [WARN] BhavCopy unavailable for this week. Falling back to manual input.")
        return None

    print(f"  [INFO] Using BhavCopy: {os.path.basename(matched_file)}")
    
    try:
        df = pd.read_csv(matched_file, low_memory=False)
    except Exception as e:
        print(f"  [ERROR] Failed to read Bhavcopy: {e}")
        return None
        
    pcr_date = target_friday if target_friday else report_date
    pcr_date_str = pcr_date.strftime("%b %d")
    derivatives_data = {}
    
    # Parse NIFTY and BANK NIFTY
    for idx_key, ticker in [("NIFTY", "NIFTY"), ("BANK NIFTY", "BANKNIFTY")]:
        try:
            # Filter options for the specific index
            df_opt = df[(df['TckrSymb'] == ticker) & (df['OptnTp'].isin(['CE', 'PE']))].copy()
            if df_opt.empty:
                print(f"    [WARN] No {ticker} options found in Bhavcopy.")
                continue
                
            if 'XpryDt' not in df_opt.columns:
                print(f"    [WARN] XpryDt column missing in Bhavcopy.")
                continue
                
            expiries = sorted(df_opt['XpryDt'].dropna().unique())
            if not expiries:
                continue
                
            near_expiry = expiries[0]
            df_near = df_opt[df_opt['XpryDt'] == near_expiry]
            
            # Format expiry date (e.g., 2026-07-14 -> 14th Jul)
            dt_exp = datetime.strptime(near_expiry, "%Y-%m-%d")
            expiry_str = f"{_get_ordinal(dt_exp.day)} {dt_exp.strftime('%b')}"
            
            ce = df_near[df_near['OptnTp'] == 'CE']
            pe = df_near[df_near['OptnTp'] == 'PE']
            
            if ce.empty or pe.empty:
                continue
                
            # Max OI and Max OI Addition from NEAR EXPIRY only
            # Use nlargest(1) to safely get the row with the highest positive change
            # (idxmax picks the global max which could be the least-negative value
            #  if all changes are negative on a falling day)
            max_call = ce.loc[ce['OpnIntrst'].idxmax()]
            max_put  = pe.loc[pe['OpnIntrst'].idxmax()]
            
            ce_add_top = ce.nlargest(1, 'ChngInOpnIntrst')
            pe_add_top = pe.nlargest(1, 'ChngInOpnIntrst')
            max_call_add = ce_add_top.iloc[0]
            max_put_add  = pe_add_top.iloc[0]
            
            # PCR: CUMULATIVE across ALL expiries for this ticker (not just
            # near expiry) — matches the firm's "cumulative PCR" wording and
            # is verified correct: total_pe_oi / total_ce_oi across all strikes/expiries.
            all_ce_oi = df_opt[df_opt['OptnTp'] == 'CE']['OpnIntrst'].sum()
            all_pe_oi = df_opt[df_opt['OptnTp'] == 'PE']['OpnIntrst'].sum()
            pcr = float(all_pe_oi / all_ce_oi) if all_ce_oi > 0 else 0.0
            
            # Populate dictionary matching manual input structure
            derivatives_data[idx_key] = {
                "oi_add_c": str(int(max_call_add['StrkPric'])),
                "oi_add_p": str(int(max_put_add['StrkPric'])),
                "call_oi": str(int(max_call['StrkPric'])),
                "put_oi": str(int(max_put['StrkPric'])),
                "pcr": round(pcr, 2),
                "expiry": expiry_str,
                "pcr_date": pcr_date_str
            }
            
            print(f"    [OK] {idx_key}: PCR={pcr:.2f}, Exp={expiry_str}")
        except Exception as e:
            print(f"    [WARN] Error parsing {idx_key} from Bhavcopy: {e}")
            
    if not derivatives_data:
        return None
        
    return derivatives_data
