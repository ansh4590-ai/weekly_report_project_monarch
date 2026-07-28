"""
save_snapshot.py — Run this locally every Sunday after market close.

Usage:
    python save_snapshot.py 26-07-2026

This fetches the full market data (nselib for sectors, YF for indices) and saves
a pre-computed snapshot to data/market_snapshot.json.

It ALSO writes data/long_history/<NIFTY 50|BANK NIFTY|FINNIFTY>.csv — the full
nselib-sourced OHLC series behind the EMA table. This exists because nselib is
blocked on Streamlit Cloud, and FINNIFTY's Yahoo Finance fallback tickers
(NIFTY_FIN_SERVICE.NS / ^CNXFIN) don't reliably return the ~830-trading-day
depth an EMA-200 needs — yfinance just silently returns a shorter series
instead of erroring, so the deployed report's FINNIFTY EMAs quietly come out
wrong even though nothing visibly fails. Committing this cache each week gives
the cloud deployment the same accurate series nselib gives you locally.

After running, commit + push so the Streamlit Cloud deployment always has
accurate data, even though NSE APIs are blocked on the cloud:

    git add data/market_snapshot.json data/long_history/
    git commit -m "snapshot: week ending 26-Jul-2026"
    git push
"""

import json
import os
import sys
from datetime import datetime

# ── Parse date argument ───────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Usage: python save_snapshot.py DD-MM-YYYY")
    print("  e.g. python save_snapshot.py 26-07-2026")
    sys.exit(1)

try:
    end_date = datetime.strptime(sys.argv[1], "%d-%m-%Y").date()
except ValueError:
    print(f"[ERROR] Invalid date format: {sys.argv[1]}  (expected DD-MM-YYYY)")
    sys.exit(1)

# ── Fetch ─────────────────────────────────────────────────────────────────────
from weekly_equity_report import fetch_all_market_data
from datetime import timedelta

start_date = end_date - timedelta(days=7)

print(f"[INFO] Fetching data for {start_date} → {end_date} …")
mkt = fetch_all_market_data(start_date, end_date)

# ── Build snapshot dict ───────────────────────────────────────────────────────
from data_sources import fetch_global_markets

prev_fri_tgt, curr_fri_tgt = mkt["target_fridays"]
global_mkts = fetch_global_markets(prev_fri_tgt, curr_fri_tgt)

snapshot = {
    "week_start": start_date.isoformat(),
    "week_end":   end_date.isoformat(),
    "indices":    mkt["indices"],
    "sectors":    mkt["sectors"],
    "global_mkts": global_mkts,
}

# ── Save ──────────────────────────────────────────────────────────────────────
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market_snapshot.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with open(out_path, "w") as f:
    json.dump(snapshot, f, indent=2)

print(f"\n[OK] Snapshot saved → {out_path}")
print(f"     Week: {start_date} → {end_date}")

missing_sectors = [s["name"] for s in mkt["sectors"] if s["pct"] is None]
print(f"     Sectors complete: {mkt['data_quality']['sectors_ok']}/{mkt['data_quality']['sectors_total']}")
if missing_sectors:
    print(f"     Missing: {missing_sectors}")

# ── Persist long-history cache for LONG_WINDOW_INDICES (EMA input series) ──
# mkt["yf_cache"] holds whatever fetch_with_fallback actually returned for
# each index this run. Locally, nselib reaches NSE directly, so for FINNIFTY
# in particular this is the accurate, full-depth series — exactly what the
# cloud deployment can't get for itself. Save it so it can.
from config import LONG_WINDOW_INDICES

long_history_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "long_history")
os.makedirs(long_history_dir, exist_ok=True)

print(f"\n[INFO] Saving long-history cache for {sorted(LONG_WINDOW_INDICES)} …")
for _name in LONG_WINDOW_INDICES:
    _df = mkt.get("yf_cache", {}).get(_name)
    if _df is None or _df.empty:
        print(f"     [WARN] {_name}: no data fetched this run — cache NOT updated (old cache, if any, left as-is)")
        continue
    _out_csv = os.path.join(long_history_dir, f"{_name}.csv")
    _df_out = _df.reset_index()
    # nselib/yfinance both index by a "Date"-named DatetimeIndex, but be
    # defensive in case that ever changes.
    if _df_out.columns[0] != "Date":
        _df_out = _df_out.rename(columns={_df_out.columns[0]: "Date"})
    _df_out.to_csv(_out_csv, index=False)
    print(f"     [OK] {_name}: {len(_df_out)} rows -> {_out_csv}")

print(f"\n[NEXT] Commit and push:")
print(f"     git add data/market_snapshot.json data/long_history/")
print(f"     git commit -m \"snapshot: week ending {end_date.strftime('%d-%b-%Y')}\"")
print(f"     git push")
