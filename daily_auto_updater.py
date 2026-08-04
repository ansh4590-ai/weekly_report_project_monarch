"""
Daily FII/DII Auto-Updater — the unattended, scheduled version.

This is the ONE file meant to be run by Windows Task Scheduler / cron, not
by hand. It does exactly what the report generation script does for the day's
FII/DII capture — same cache file, same function — just without a person involved.
Point a daily trigger at this file (see the two setup blocks at the bottom of this file)
and every trading day gets captured automatically, so a normal Friday report already has
a complete week without anyone having manually fetched data Mon-Thu.

Cloud sync
----------
After a successful fetch, this script also stages, commits, and pushes
fii_dii_history.csv. The Streamlit Cloud deployment can't reach NSE directly
(same reason nselib/YF long-history has a committed-snapshot workaround — see
save_snapshot.py), so it only ever sees whatever was last pushed to the repo.
Without this push step, this script's fetch only ever updated the *local*
copy and the cloud app kept showing that day as "missing". Streamlit
Community Cloud auto-redeploys on a new push to the linked repo, so today's
figure should show up there shortly after this script runs.

This requires git to be installed and available on PATH, and configured for
*non-interactive* push (an SSH key with no passphrase, or a credential
helper with a stored PAT) under whatever account/session runs this on a
schedule — a plain HTTPS remote that prompts for a password will hang or
fail silently under Task Scheduler/cron. If git isn't set up that way, the
push step fails harmlessly and just prints a warning; the local cache is
still updated either way.
"""

import os
import subprocess
import sys
import traceback
from datetime import date, datetime, timezone, timedelta
from data_sources import get_fii_dii_for_date, _is_after_nse_release_time, FII_DII_LOG_FILENAME


def _git_commit_and_push(csv_filename: str) -> None:
    """
    Stage, commit, and push the FII/DII history CSV.

    Skips cleanly (with a warning, not an exception) if git isn't installed,
    this folder isn't a git repo, or the push fails for any reason (auth,
    network, no remote configured, etc.) — a failed sync should never make
    the overall run look like a failure, since the local fetch/cache already
    succeeded by the time this is called.
    """
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", csv_filename],
            cwd=repo_dir, capture_output=True, text=True, timeout=30,
        )
        if status.returncode != 0:
            print(f"  [WARN] git status failed — is {repo_dir} a git repo? "
                  f"{status.stderr.strip()}")
            return
        if not status.stdout.strip():
            print("  [INFO] No git changes to push — CSV already in sync with remote.")
            return

        subprocess.run(["git", "add", csv_filename], cwd=repo_dir, check=True, timeout=30)
        subprocess.run(
            ["git", "commit", "-m", f"fii/dii: auto-update {date.today().isoformat()}"],
            cwd=repo_dir, check=True, timeout=30,
        )
        push = subprocess.run(
            ["git", "push"], cwd=repo_dir, capture_output=True, text=True, timeout=60,
        )
        if push.returncode != 0:
            print(
                "  [WARN] git push failed — local cache is updated, but the "
                "Streamlit Cloud deployment won't see today's figure until "
                f"this is pushed manually.\n          {push.stderr.strip()}"
            )
            return

        print("  [OK] Pushed fii_dii_history.csv — Streamlit Cloud will pick "
              "this up on its next auto-redeploy.")

    except FileNotFoundError:
        print("  [WARN] git executable not found on PATH — skipping auto-push. "
              "Install git, or push the CSV manually after this runs.")
    except subprocess.CalledProcessError as e:
        print(f"  [WARN] git command failed: {e}. Local cache is still updated; "
              f"push {csv_filename} manually to sync the cloud deployment.")
    except Exception as e:
        print(f"  [WARN] Unexpected error during git sync: {e}")


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
                print("\n[GIT] Syncing to remote so Streamlit Cloud sees today's data...")
                _git_commit_and_push(FII_DII_LOG_FILENAME)
            else:
                print(f"\n[OK] Already cached from earlier today: "
                      f"FII={result['fii']:,.0f} Cr, DII={result['dii']:,.0f} Cr")
                # No new local write this run, so nothing new to push — but
                # if an earlier run today fetched data and the push failed
                # then (e.g. transient network issue), retry the sync now.
                _git_commit_and_push(FII_DII_LOG_FILENAME)
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
#
# Git prerequisite (for the Streamlit Cloud sync): this folder must be a
# git repo with a remote configured for non-interactive push — an SSH
# remote with a passphrase-less key, or an HTTPS remote with a credential
# helper that already has a token stored. Test manually first:
#   cd /path/to/equity_report_folder && git push
# If that prompts for a username/password, fix that before scheduling —
# under Task Scheduler/cron there's no one there to type it.
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
#    fii_dii_history.csv, and must be a git repo with push already working
#    non-interactively — see the git prerequisite note above)
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
# Note: cron jobs run with a minimal environment/PATH — if `git` isn't
# found, set an absolute path to it or source your shell profile first.
# ═══════════════════════════════════════════════════════════════════════
