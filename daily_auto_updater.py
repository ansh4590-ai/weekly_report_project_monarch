"""
Daily FII/DII Auto-Updater — the unattended, scheduled version.

This is the ONE file meant to be run by Windows Task Scheduler / cron, not
by hand. It does exactly what the report generation script does for the day's
FII/DII capture — same cache file, same function — just without a person involved. 
Point a daily trigger at this file (see the two setup blocks at the bottom of this file) 
and every trading day gets captured automatically, so a normal Friday report already has a
complete week without anyone having manually fetched data Mon-Thu.
"""

import sys
import traceback
from datetime import date, datetime, timezone, timedelta
from data_sources import get_fii_dii_for_date, _is_after_nse_release_time


def main():
    print("=======================================")
    print(" FII/DII Daily Auto-Updater")
    print("=======================================")
    try:
        today = date.today()
        IST = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(IST)
        print(f"Checking {today.isoformat()} at {now_ist.strftime('%H:%M')} IST...")

        if today.weekday() >= 5:
            print("\n[SKIP] Weekend — markets closed, nothing to fetch.")
            return

        # NSE only releases final FII/DII figures after 6:30 PM IST.
        # Running before that time would cache provisional/intraday values.
        if not _is_after_nse_release_time():
            print(
                f"\n[SKIP] Current IST time is {now_ist.strftime('%H:%M')} — "
                "NSE has not yet released today's official FII/DII figures.\n"
                "Please run this script after 6:30 PM IST."
            )
            return

        # This function automatically scrapes the live NSE data if the target date is today,
        # and saves it into fii_dii_history.csv
        result = get_fii_dii_for_date(today)
        
        if result.get("fii") is not None:
            if result.get("source") == "live":
                print(f"\n[SUCCESS] Fetched and cached: FII={result['fii']:,.0f} Cr, "
                      f"DII={result['dii']:,.0f} Cr")
            else:
                print(f"\n[OK] Already cached from earlier today: "
                      f"FII={result['fii']:,.0f} Cr, DII={result['dii']:,.0f} Cr")
        else:
            print("\n[WARNING] Data unavailable. NSE might not have released "
                  "today's figures yet, or the request was blocked — try "
                  "scheduling this a little later in the evening.")
            
    except Exception:
        print("\n[ERROR] An unexpected error occurred:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

# ═══════════════════════════════════════════════════════════════════════
# ONE-TIME SETUP — schedule this file to run once every trading-day evening
# (after markets close, e.g. 18:00 IST) so the NSE figure has been published.
# Pick the block for your OS.
# ═══════════════════════════════════════════════════════════════════════
#
# ── Windows (Task Scheduler) ─────────────────────────────────────────────
# 1. Open Task Scheduler → Create Task
# 2. General tab: name it "FII DII Daily Updater", check "Run whether user
#    is logged on or not"
# 3. Triggers tab: New → Daily, start time 19:00 (IST), recur every 1 day.
#    NSE publishes final FII/DII data after 18:30 IST, so 19:00 is safe.
#    (It will still fire on weekends — the script itself checks and skips
#    them, so that's fine.)
# 4. Actions tab: New → Program/script:
#       C:\path\to\python.exe
#    Add arguments:
#       daily_auto_updater.py
#    Start in:
#       C:\path\to\equity_report_folder
#    (must be the folder containing data_sources.py, config.py, and
#    fii_dii_history.csv)
# 5. OK, enter your Windows password if prompted. Test it once with
#    right-click → Run.
#
# ── macOS / Linux (cron) ──────────────────────────────────────────────────
# Run: crontab -e
# Add this line (adjust paths):
#   30 13 * * 1-5 cd /path/to/equity_report_folder && /usr/bin/python3 daily_auto_updater.py >> daily_updater.log 2>&1
# 13:30 UTC = 19:00 IST (NSE data is published after 18:30 IST).
# This runs at 18:00, Monday–Friday only (the "1-5"), and appends output to
# daily_updater.log in the same folder so you can check it later.
# ═══════════════════════════════════════════════════════════════════════
