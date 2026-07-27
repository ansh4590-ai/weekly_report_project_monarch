"""
Tests for validation.py — date parsing and Sunday enforcement.
"""

import pytest
from datetime import date
from validation import validate_end_sunday


class TestValidateEndSunday:
    """validate_end_sunday() must accept only DD-MM-YYYY Sundays."""

    def test_valid_sunday_accepted(self):
        """A correctly formatted Sunday returns (start, end) 7 days apart."""
        # 19-07-2026 is a Sunday
        start, end = validate_end_sunday("19-07-2026")
        assert end == date(2026, 7, 19)
        assert start == date(2026, 7, 12)
        assert (end - start).days == 7

    def test_non_sunday_rejected(self):
        """A valid date that is not Sunday raises ValueError."""
        # 21-07-2026 is a Monday
        with pytest.raises(ValueError, match="Sunday"):
            validate_end_sunday("21-07-2026")

    def test_bad_format_rejected(self):
        """Wrong date format raises ValueError."""
        # ISO format instead of DD-MM-YYYY
        with pytest.raises(ValueError):
            validate_end_sunday("2026-07-20")

    def test_empty_string_rejected(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            validate_end_sunday("")

    def test_result_types(self):
        """Both returned values are date objects, not datetime."""
        start, end = validate_end_sunday("19-07-2026")
        assert isinstance(start, date)
        assert isinstance(end, date)
