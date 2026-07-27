"""
NSE Historical Derivatives Data Downloader & Cache Manager

Cache structure:
    data/
      YYYY/
        YYYYMMDD/
          bhavcopy.csv
          metadata.json
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional


# ─── Archive URL base ────────────────────────────────────────────────────────
# NOTE: correct hostname is nsearchives.nseindia.com (not archives.nseindia.com)
_NSE_ARCHIVE_BASE = "https://nsearchives.nseindia.com/content/fo"
_MAX_LOOKBACK_DAYS = 7          # walk back at most 7 calendar days (handles mid-week holidays)


class HistoricalDerivativeFetcher:
    """
    Resolves, downloads, and caches the NSE FO BhavCopy CSV for any report week.

    Usage
    -----
    fetcher = HistoricalDerivativeFetcher(base_dir)
    csv_path = fetcher.get(report_end_date)   # returns str path or None
    """

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, report_date: date) -> Optional[str]:
        """
        Main entry point.

        Parameters
        ----------
        report_date : date
            The end Sunday of the report week.

        Returns
        -------
        str | None
            Absolute path to the cached bhavcopy.csv, or None on failure.
        """
        # Report week's Friday
        friday = report_date - timedelta(days=2)

        # Resolve last trading day (walk back, skipping weekends only —
        # actual market holiday detection is handled by trying download).
        trading_day = self._last_weekday_on_or_before(friday)
        if trading_day is None:
            print("  [WARN] Could not resolve last trading day.")
            return None

        # 1. Structured cache hit
        cached = self._csv_path(trading_day)
        if cached.exists():
            print(f"  [CACHE HIT] BhavCopy for {trading_day}: {cached}")
            return str(cached)

        # 2. Auto-download (walks back if a day turns out to be a holiday / 404)
        print(f"  [INFO] No cache for {trading_day}. Attempting NSE archive download...")
        return self._download_with_holiday_walk(trading_day)

    # ── Path helpers ──────────────────────────────────────────────────────────

    def _csv_path(self, day: date) -> Path:
        return self.data_dir / str(day.year) / day.strftime("%Y%m%d") / "bhavcopy.csv"

    def _meta_path(self, day: date) -> Path:
        return self.data_dir / str(day.year) / day.strftime("%Y%m%d") / "metadata.json"

    # ── Last-weekday resolver ─────────────────────────────────────────────────

    @staticmethod
    def _last_weekday_on_or_before(day: date) -> Optional[date]:
        """Return day itself or the nearest previous weekday (Mon–Fri)."""
        for _ in range(_MAX_LOOKBACK_DAYS):
            if day.weekday() < 5:   # 0=Mon … 4=Fri
                return day
            day -= timedelta(days=1)
        return None

    @staticmethod
    def _prev_weekday(day: date) -> date:
        """One step back, skipping weekends."""
        day -= timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day

    # ── Download orchestration ────────────────────────────────────────────────

    def _download_with_holiday_walk(self, start_day: date) -> Optional[str]:
        """
        Try downloading for start_day; if NSE returns 404 (holiday / no data),
        step back to the previous weekday and retry — up to _MAX_LOOKBACK_DAYS times.
        """
        # Lazy import to avoid circular dependency
        try:
            from data_sources import create_nse_session
            session = create_nse_session()
        except Exception as e:
            print(f"  [WARN] Could not create NSE session: {e}")
            session = None

        if session is None:
            print("  [WARN] NSE session unavailable. Skipping archive download.")
            return None

        day = start_day
        for attempt in range(_MAX_LOOKBACK_DAYS):
            if day.weekday() >= 5:
                day = self._prev_weekday(day)
                continue

            result = self._try_one_day(session, day)
            if result:
                return result

            print(f"  [INFO] No archive data for {day}. Trying previous trading day...")
            day = self._prev_weekday(day)

        print("  [WARN] Exhausted lookback window. Archive download failed.")
        return None

    def _resolve_via_reports_api(self, session, day: date):
        """
        Ask NSE's own "All Reports" API for the actual current download link
        for the "F&O - UDiFF Common Bhavcopy Final (zip)" report — the same
        call https://www.nseindia.com/all-reports-derivatives makes when you
        click that report's download button — instead of guessing the
        filename pattern ourselves.

        More robust than a hardcoded pattern since it stays correct even if
        NSE changes the file-naming convention again.

        Returns (url, fmt) on success, None on failure (caller falls back
        to the static Tier B guess).
        """
        import json
        from urllib.parse import quote

        date_str = day.strftime("%d-%m-%Y")   # NSE reports API uses DD-MM-YYYY
        archives_spec = json.dumps([{
            "name": "F&O - UDiFF Common Bhavcopy Final (zip)",
            "type": "archives",
            "category": "derivatives",
            "section": "equity",
        }])

        api_url = (
            "https://www.nseindia.com/api/reports"
            f"?archives={quote(archives_spec)}&date={date_str}&type=equity&mode=single"
        )

        try:
            resp = session.get(api_url, timeout=30)
            if resp.status_code != 200:
                print(f"  [INFO] Reports API HTTP {resp.status_code} for {date_str} — falling back to Tier B")
                return None

            payload = resp.json()

            # The API may return a list or a single dict
            entry = None
            if isinstance(payload, list) and payload:
                entry = payload[0]
            elif isinstance(payload, dict) and payload:
                entry = payload

            if not entry:
                print(f"  [INFO] Reports API: no entry for {date_str} "
                      f"(non-trading day or report not yet published)")
                return None

            # Probe all field names NSE has used across API versions
            link = (
                entry.get("link")
                or entry.get("file")
                or entry.get("filePath")
                or entry.get("fileLink")
            )
            if not link:
                print(f"  [WARN] Reports API entry had no recognisable link field: "
                      f"{list(entry.keys())} — falling back to Tier B")
                return None

            # Ensure the URL is absolute
            if not link.startswith("http"):
                prefix = "https://nsearchives.nseindia.com"
                link = prefix + (link if link.startswith("/") else "/" + link)

            lower = link.lower()
            fmt = "zip" if lower.endswith(".zip") else ("gz" if lower.endswith(".gz") else "csv")

            print(f"  [INFO] Reports API resolved link for {date_str}: {link}")
            return (link, fmt)

        except Exception as exc:
            print(f"  [WARN] Reports API lookup failed for {date_str}: {exc} — falling back to Tier B")
            return None

    def _try_one_day(self, session, day: date) -> Optional[str]:
        """
        Try all URL variants for a single trading day.
        Returns cached CSV path on success, None otherwise.
        """
        date_str = day.strftime("%Y%m%d")
        base_name = f"BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000"

        url_variants = []

        # Tier A: resolve real link via NSE's own Reports API (resilient to
        # future filename-convention changes on NSE's side)
        resolved = self._resolve_via_reports_api(session, day)
        if resolved:
            url_variants.append(resolved)

        # Tier B: guessed static URL pattern (known-good as of 2026;
        # kept as fallback in case Tier A is unavailable or returns nothing)
        url_variants += [
            (f"{_NSE_ARCHIVE_BASE}/{base_name}.csv.zip", "zip"),
            (f"{_NSE_ARCHIVE_BASE}/{base_name}.csv.gz",  "gz"),
            (f"{_NSE_ARCHIVE_BASE}/{base_name}.csv",     "csv"),
        ]

        cache_dir = self._csv_path(day).parent
        csv_out   = cache_dir / "bhavcopy.csv"

        for url, fmt in url_variants:
            try:
                print(f"  [DOWNLOAD] {url}")
                resp = session.get(url, timeout=60, stream=True)

                if resp.status_code == 404:
                    continue                         # try next format
                if resp.status_code != 200:
                    print(f"  [WARN] HTTP {resp.status_code} for {url}")
                    continue

                # Persist raw download
                cache_dir.mkdir(parents=True, exist_ok=True)
                raw_path = cache_dir / f"_raw.{fmt}"
                with open(raw_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=65536):
                        fh.write(chunk)

                # Extract → bhavcopy.csv
                if not self._extract(raw_path, csv_out, fmt):
                    raw_path.unlink(missing_ok=True)
                    continue

                # Remove raw archive
                if raw_path != csv_out:
                    raw_path.unlink(missing_ok=True)

                # Write metadata sidecar
                self._write_metadata(day, url, csv_out)

                print(f"  [OK] Cached: {csv_out} ({day})")
                return str(csv_out)

            except Exception as exc:
                print(f"  [WARN] Exception downloading {url}: {exc}")
                continue

        return None

    # ── Extraction ────────────────────────────────────────────────────────────

    @staticmethod
    def _extract(raw_path: Path, csv_out: Path, fmt: str) -> bool:
        """Extract raw download to csv_out. Returns True on success."""
        try:
            if fmt == "zip":
                with zipfile.ZipFile(raw_path, "r") as zf:
                    csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                    if not csv_members:
                        print(f"  [WARN] No .csv inside zip: {raw_path.name}")
                        return False
                    with zf.open(csv_members[0]) as src, open(csv_out, "wb") as dst:
                        shutil.copyfileobj(src, dst)

            elif fmt == "gz":
                with gzip.open(raw_path, "rb") as src, open(csv_out, "wb") as dst:
                    shutil.copyfileobj(src, dst)

            elif fmt == "csv":
                shutil.copy(raw_path, csv_out)

            else:
                return False

            return True

        except Exception as exc:
            print(f"  [WARN] Extraction error: {exc}")
            return False

    # ── Metadata ──────────────────────────────────────────────────────────────

    def _write_metadata(self, day: date, url: str, csv_path: Path) -> None:
        meta = {
            "downloaded":   date.today().isoformat(),
            "source":       "NSE Archive",
            "trading_day":  day.isoformat(),
            "url":          url,
            "sha256":       self._sha256(csv_path),
        }
        try:
            with open(self._meta_path(day), "w") as fh:
                json.dump(meta, fh, indent=2)
        except Exception as exc:
            print(f"  [WARN] Could not write metadata: {exc}")

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
