"""Tests for extraction_validator.py — physical bounds, consistency, and CIQ cross-checks.

Tests:
1. test_valid_extraction_passes — all values within physical bounds
2. test_rsrp_out_of_bounds — RSRP below physical minimum flags invalid
3. test_internal_consistency_rsrp_rsrq — RSRP > RSRQ triggers flag
4. test_ciq_earfcn_mismatch — EARFCN mismatch detected
5. test_deep_get_nested — _deep_get finds values in nested dicts
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.extraction_validator import PHYSICAL_BOUNDS, _deep_get, validate_extraction


class TestPhysicalBounds:
    def test_valid_extraction_passes(self):
        """All values within physical bounds should return valid=True, no flags."""
        extracted = {
            "lte_params": {
                "rsrp_dbm": -65.0,
                "rsrq_db": -8.0,
                "sinr_db": 28.0,
                "tx_power_dbm": -15.0,
                "earfcn": 2175,
                "pci": 120,
                "bandwidth_mhz": 20.0,
                "band": 2,
            },
            "nr_params": None,
        }
        result = validate_extraction(extracted)
        assert result["valid"] is True
        assert len(result["flags"]) == 0
        assert len(result["ciq_mismatches"]) == 0

    def test_rsrp_out_of_bounds(self):
        """RSRP below physical minimum (-140 dBm) should flag as invalid."""
        extracted = {
            "lte_params": {
                "rsrp_dbm": -200.0,  # Impossible
                "rsrq_db": -8.0,
                "sinr_db": 28.0,
                "tx_power_dbm": -15.0,
            },
            "nr_params": None,
        }
        result = validate_extraction(extracted)
        assert result["valid"] is False
        assert any("rsrp_dbm" in f and "below physical minimum" in f for f in result["flags"])


class TestInternalConsistency:
    def test_rsrp_greater_than_rsrq_flags(self):
        """RSRP > RSRQ (e.g. -40 > -8) is unusual and should be flagged."""
        extracted = {
            "lte_params": {
                "rsrp_dbm": -40.0,
                "rsrq_db": -8.0,
                # -40 > -8 is False, so this should NOT flag
                # Let's use a case where RSRP > RSRQ numerically
            },
            "nr_params": None,
        }
        # RSRP = -3 > RSRQ = -8 → flags
        extracted["lte_params"]["rsrp_dbm"] = -3.0
        extracted["lte_params"]["rsrq_db"] = -8.0
        result = validate_extraction(extracted)
        assert any("RSRP" in f and "RSRQ" in f for f in result["flags"])

    def test_nr_antenna_max_less_than_min_flags(self):
        """NR ant_max < ant_min should flag as swapped."""
        extracted = {
            "lte_params": None,
            "nr_params": {
                "nr_ant_max_rsrp": -90.0,
                "nr_ant_min_rsrp": -70.0,  # min > max → swapped
            },
        }
        result = validate_extraction(extracted)
        assert any("swapped" in f for f in result["flags"])


class TestCIQCrossValidation:
    def test_ciq_earfcn_mismatch(self):
        """EARFCN mismatch between VLM extraction and CIQ should be reported."""
        extracted = {
            "lte_params": {
                "earfcn": 2175,
                "pci": 120,
            },
            "nr_params": None,
        }
        ciq_data = {
            "earfcnDl": 5035,  # Different EARFCN
            "pci": 120,
        }
        result = validate_extraction(extracted, ciq_data)
        assert len(result["ciq_mismatches"]) >= 1
        assert any("EARFCN" in m for m in result["ciq_mismatches"])


class TestDeepGet:
    def test_deep_get_finds_nested_value(self):
        """_deep_get should find values in arbitrarily nested dicts."""
        data = {
            "top_level": "a",
            "nested": {
                "middle": {
                    "deep_key": 42,
                },
            },
        }
        assert _deep_get(data, "deep_key") == 42
        assert _deep_get(data, "top_level") == "a"
        assert _deep_get(data, "nonexistent") is None
