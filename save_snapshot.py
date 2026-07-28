"""
save_snapshot.py — Run this locally every Sunday after market close.

Usage:
    python save_snapshot.py 26-07-2026

This fetches the full market data (nselib for sectors, YF for indices) and saves
a pre-computed snapshot to data/market_snapshot.json.

After running, commit + push the updated JSON so the Streamlit Cloud deployment
always has accurate sector data, even though NSE APIs are blocked on the cloud.

    git add data/market_snapshot.json
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

print(f"\n[NEXT] Commit and push:")
print(f"     git add data/market_snapshot.json")
print(f"     git commit -m \"snapshot: week ending {end_date.strftime('%d-%b-%Y')}\"")
print(f"     git push")
