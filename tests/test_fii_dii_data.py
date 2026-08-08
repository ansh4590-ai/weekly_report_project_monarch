"""
Tests for get_fii_dii_data() branching logic (cached, live, missing, weekend).
"""

import pytest
import pandas as pd
from datetime import date, timedelta
from unittest.mock import patch, mock_open
import math

from data_sources import get_fii_dii_data

class TestFiiDiiData:
    
    @patch("data_sources.date")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data="date,fii,dii\n2026-07-20,100,200\n2026-07-21,-50,150\n")
    def test_cached_rows(self, mock_file, mock_exists, mock_date):
        """Mock CSV with known data returns status='cached'."""
        mock_exists.return_value = True
        mock_date.today.return_value = date(2026, 7, 24)
        
        start_date = date(2026, 7, 19)
        end_date = date(2026, 7, 21)
        
        df = get_fii_dii_data(start_date, end_date)
        
        # 2026-07-20 is Monday, 2026-07-21 is Tuesday
        assert len(df) == 2
        assert df.iloc[0]["date"] == date(2026, 7, 20)
        assert df.iloc[0]["status"] == "cached"
        assert df.iloc[0]["fii"] == 100
        assert df.iloc[0]["dii"] == 200
        
        assert df.iloc[1]["date"] == date(2026, 7, 21)
        assert df.iloc[1]["status"] == "cached"
        assert df.iloc[1]["fii"] == -50

    @patch("data_sources.date")
    @patch("os.path.exists")
    def test_weekend_rows(self, mock_exists, mock_date):
        """Sat/Sun return status='weekend' with NaN values."""
        mock_exists.return_value = False
        mock_date.today.return_value = date(2026, 7, 24)
        
        # 2026-07-18 is Saturday, 2026-07-19 is Sunday
        start_date = date(2026, 7, 17)
        end_date = date(2026, 7, 19)
        
        df = get_fii_dii_data(start_date, end_date)
        
        assert len(df) == 2
        assert df.iloc[0]["status"] == "weekend"
        assert math.isnan(df.iloc[0]["fii"])
        assert df.iloc[1]["status"] == "weekend"

    @patch("data_sources.date")
    @patch("os.path.exists")
    def test_missing_rows(self, mock_exists, mock_date):
        """Not in cache, not today, not weekend -> 'missing' with NaN values."""
        mock_exists.return_value = False
        mock_date.today.return_value = date(2026, 7, 24)
        
        # 2026-07-20 is Monday
        start_date = date(2026, 7, 19)
        end_date = date(2026, 7, 20)
        
        df = get_fii_dii_data(start_date, end_date)
        
        assert len(df) == 1
        assert df.iloc[0]["date"] == date(2026, 7, 20)
        assert df.iloc[0]["status"] == "missing"
        assert math.isnan(df.iloc[0]["fii"])

    @patch("data_sources._is_after_nse_release_time")
    @patch("data_sources.fetch_fii_dii")
    @patch("data_sources._write_to_cache")
    @patch("data_sources.date")
    @patch("os.path.exists")
    def test_live_capture(self, mock_exists, mock_date, mock_write, mock_fetch, mock_after_release):
        """Date is today, after 6:30 PM IST, not cached -> scrapes live, writes to cache, returns 'live'."""
        mock_exists.return_value = False
        today = date(2026, 7, 24)  # Friday
        mock_date.today.return_value = today

        # Simulate being after NSE's 6:30 PM release time
        mock_after_release.return_value = True

        # fetch_fii_dii is what get_fii_dii_data calls internally
        mock_fetch.return_value = {"fii": 555, "dii": 777}

        start_date = date(2026, 7, 23)
        end_date = date(2026, 7, 24)

        df = get_fii_dii_data(start_date, end_date)

        assert len(df) == 1
        assert df.iloc[0]["date"] == today
        assert df.iloc[0]["status"] == "live"
        assert df.iloc[0]["fii"] == 555
        assert df.iloc[0]["dii"] == 777

        # Ensure it attempted to save to cache
        mock_write.assert_called_once()
