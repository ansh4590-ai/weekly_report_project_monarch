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
# nselib caps a single index_data() call at ~280 rows regardless of the
# requested date range. To get the 800+ rows an EMA-200 needs to converge,
# we stitch together annual segments starting from 2020, dedup, sort,
# and save the combined series. The cloud deployment then uses this cache
# instead of ever touching the truncated live nselib series.
from config import LONG_WINDOW_INDICES, NSELIB_MAP
import pandas as pd
from nselib import capital_market as _cm
from datetime import date as _date, timedelta as _td

long_history_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "long_history")
os.makedirs(long_history_dir, exist_ok=True)

# Name mapping: display name -> nselib index name
_LONG_NSELIB = {k: NSELIB_MAP[k] for k in LONG_WINDOW_INDICES if k in NSELIB_MAP}
# For indices not in NSELIB_MAP (e.g. NIFTY 50, BANK NIFTY), use YF cache as fallback
_LONG_YF_ONLY = {k for k in LONG_WINDOW_INDICES if k not in NSELIB_MAP}

print(f"\n[INFO] Building full long-history cache for {sorted(LONG_WINDOW_INDICES)} ...")
print(f"       (stitching annual nselib segments to overcome ~280-row API cap)")

today = _date.today()

for _name in sorted(LONG_WINDOW_INDICES):
    _out_csv = os.path.join(long_history_dir, f"{_name}.csv")

    if _name in _LONG_YF_ONLY:
        # NIFTY 50 and BANK NIFTY: YF (^NSEI / ^NSEBANK) returns full history
        _df = mkt.get("yf_cache", {}).get(_name)
        if _df is None or _df.empty:
            print(f"     [WARN] {_name}: no YF data this run — cache NOT updated")
            continue
        _df_out = _df.reset_index()
        if _df_out.columns[0] != "Date":
            _df_out = _df_out.rename(columns={_df_out.columns[0]: "Date"})
        _df_out.to_csv(_out_csv, index=False)
        print(f"     [OK]   {_name}: {len(_df_out)} rows (YF) -> {_out_csv}")
        continue

    # nselib path: stitch quarterly segments from 2019-01-01 to today.
    # nselib caps each call at ~70 rows per calendar year regardless of date range,
    # so we break into 3-month windows to stay under the cap and capture every day.
    _nse_name = _LONG_NSELIB[_name]
    _all_chunks = []
    _seg_start = _date(2019, 1, 1)

    while _seg_start <= today:
        # 3-month window
        _seg_end_month = _seg_start.month + 2
        _seg_end_year = _seg_start.year + (_seg_end_month - 1) // 12
        _seg_end_month = ((_seg_end_month - 1) % 12) + 1
        import calendar as _cal
        _last_day = _cal.monthrange(_seg_end_year, _seg_end_month)[1]
        _seg_end = min(_date(_seg_end_year, _seg_end_month, _last_day), today)

        _fs = _seg_start.strftime("%d-%m-%Y")
        _fe = _seg_end.strftime("%d-%m-%Y")
        try:
            _chunk = _cm.index_data(index=_nse_name, from_date=_fs, to_date=_fe)
            if _chunk is not None and not _chunk.empty:
                _all_chunks.append(_chunk)
        except Exception as _exc:
            print(f"     [WARN]  {_name} {_fs}-{_fe}: nselib error — {_exc}")

        # Advance by 3 months
        _next_month = _seg_start.month + 3
        _next_year = _seg_start.year + (_next_month - 1) // 12
        _next_month = ((_next_month - 1) % 12) + 1
        _seg_start = _date(_next_year, _next_month, 1)

    if not _all_chunks:
        print(f"     [WARN] {_name}: no nselib data fetched — cache NOT updated")
        continue

    _combined = pd.concat(_all_chunks, ignore_index=True)
    _combined["Date"] = pd.to_datetime(_combined["TIMESTAMP"], format="%d-%b-%Y")
    _combined.set_index("Date", inplace=True)

    # Dedup (keep last occurrence per date — same logic as data_sources.py)
    _dup = int(_combined.index.duplicated().sum())
    if _dup:
        print(f"     [DEDUP] {_name}: removed {_dup} duplicate date(s)")
        _combined = _combined[~_combined.index.duplicated(keep="last")]

    _combined.sort_index(inplace=True)
    _combined = _combined.rename(columns={
        "CLOSE_INDEX_VAL": "Close",
        "OPEN_INDEX_VAL": "Open",
        "HIGH_INDEX_VAL": "High",
        "LOW_INDEX_VAL": "Low",
    })

    _df_out = _combined[["Open", "High", "Low", "Close"]].reset_index()
    _df_out.to_csv(_out_csv, index=False)
    _last_date = _combined.index.max().date()
    print(f"     [OK]   {_name}: {len(_df_out)} rows, up to {_last_date} -> {_out_csv}")

print(f"\n[NEXT] Commit and push:")
print(f"     git add data/market_snapshot.json data/long_history/")
print(f"     git commit -m \"snapshot: week ending {end_date.strftime('%d-%b-%Y')}\"")
print(f"     git push")

