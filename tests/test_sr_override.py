"""
Tests for Support/Resistance override logic.
(Validates how streamlit_app.py prepares mkt_data['sr'] before generation)
"""

import pytest

def apply_overrides(sr_rows, sr_inputs):
    """
    Simulates the override loop in streamlit_app.py:
    0 is treated as blank/None.
    """
    for row in sr_rows:
        name = row["name"]
        ov = sr_inputs.get(name, {})
        row["s2"] = ov.get("s2") or None
        row["s1"] = ov.get("s1") or None
        row["r1"] = ov.get("r1") or None
        row["r2"] = ov.get("r2") or None
        
        if not any([row["s1"], row["s2"], row["r1"], row["r2"]]):
            row["bias"] = ""
            
    return sr_rows


class TestSROverrides:

    def test_zero_treated_as_none(self):
        """Entering 0 for a level converts it to None in the final payload."""
        sr_rows = [{"name": "NIFTY", "s2": 1000, "s1": 2000, "r1": 3000, "r2": 4000, "bias": "positive"}]
        sr_inputs = {"NIFTY": {"s2": 0, "s1": 0, "r1": 0, "r2": 0}}
        
        result = apply_overrides(sr_rows, sr_inputs)
        assert result[0]["s2"] is None
        assert result[0]["s1"] is None
        assert result[0]["r1"] is None
        assert result[0]["r2"] is None

    def test_positive_value_preserved(self):
        """Entering a non-zero value overrides the original."""
        sr_rows = [{"name": "NIFTY", "s2": 1000, "s1": 2000, "r1": 3000, "r2": 4000, "bias": "positive"}]
        sr_inputs = {"NIFTY": {"s2": 900, "s1": 1900, "r1": 3100, "r2": 4100}}
        
        result = apply_overrides(sr_rows, sr_inputs)
        assert result[0]["s2"] == 900
        assert result[0]["s1"] == 1900
        assert result[0]["r1"] == 3100
        assert result[0]["r2"] == 4100

    def test_bias_cleared_when_all_blank(self):
        """If all 4 levels are blank (0), bias is cleared."""
        sr_rows = [{"name": "NIFTY", "s2": 1000, "s1": 2000, "r1": 3000, "r2": 4000, "bias": "positive"}]
        sr_inputs = {"NIFTY": {"s2": 0, "s1": 0, "r1": 0, "r2": 0}}
        
        result = apply_overrides(sr_rows, sr_inputs)
        assert result[0]["bias"] == ""

    def test_bias_kept_when_partial(self):
        """If at least one level is provided, bias remains untouched."""
        sr_rows = [{"name": "NIFTY", "s2": 1000, "s1": 2000, "r1": 3000, "r2": 4000, "bias": "positive"}]
        sr_inputs = {"NIFTY": {"s2": 0, "s1": 0, "r1": 3000, "r2": 0}}
        
        result = apply_overrides(sr_rows, sr_inputs)
        assert result[0]["bias"] == "positive"
