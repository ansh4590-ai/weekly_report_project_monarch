"""
Debug script: replicates exactly what the Streamlit app's "Fetch Market Data"
button does, then prints every index close, prev-close, weekly%, and the
data source so we can compare against the terminal output.

Run from the project folder:
  python debug_fetch.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, timedelta
from validation import validate_end_sunday

# ── change this to whatever end-sunday you're testing ──────────────────────
END_SUNDAY_STR = "26-07-2026"
# ───────────────────────────────────────────────────────────────────────────

start_date, end_date = validate_end_sunday(END_SUNDAY_STR)
print(f"\nDate range  : {start_date}  to  {end_date}")
print(f"Week ending : {end_date - timedelta(days=2)}  (Friday)\n")

from weekly_equity_report import fetch_all_market_data

mkt = fetch_all_market_data(start_date, end_date)

print("\n" + "=" * 70)
print("INDICES (from fetch_all_market_data)")
print("=" * 70)
for row in mkt.get("indices", []):
    print(f"  {row['name']:20s}  close={row['close']}  pct={row['pct']}")

print("\n" + "=" * 70)
print("SECTORS (from fetch_all_market_data)")
print("=" * 70)
for row in mkt.get("sectors", []):
    print(f"  {row['name']:20s}  close={row['close']}  pct={row['pct']}")

print("\n" + "=" * 70)
print("S/R ROWS")
print("=" * 70)
for row in mkt.get("sr", []):
    print(f"  {row['name']:15s}  close={row.get('close')}  S2={row.get('s2')}  S1={row.get('s1')}  R1={row.get('r1')}  R2={row.get('r2')}")

print("\n" + "=" * 70)
print("EMA ROWS")
print("=" * 70)
for row in mkt.get("ema", []):
    emas = row.get("emas", {})
    ema_str = "  ".join(f"EMA{p}={v}" for p, v in sorted(emas.items()))
    print(f"  {row['name']:15s}  close={row.get('close')}  bias={row.get('bias')}  {ema_str}")

print("\n" + "=" * 70)
print("ACTUAL FRIDAYS detected")
print("=" * 70)
prev_fri, curr_fri = mkt.get("actual_fridays", (None, None))
print(f"  prev_friday_actual = {prev_fri}")
print(f"  curr_friday_actual = {curr_fri}")
print()
