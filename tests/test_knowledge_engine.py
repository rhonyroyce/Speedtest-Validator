"""Tests for knowledge_engine.py — knowledge base loading and query.

Implementation: Claude Code Prompt 5 (Knowledge Engine)
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.knowledge import rf_parameters, throughput_benchmarks, kpi_mappings, mop_thresholds
from code.knowledge_engine import KnowledgeEngine

THRESHOLD_EXCEL = Path(__file__).resolve().parent.parent / "input" / "DAS_Validation_Thresholds.xlsx"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@pytest.fixture
def config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def engine(config):
    eng = KnowledgeEngine(config)
    eng.load_all()
    return eng


# === mop_thresholds tests ===

class TestMopThresholds:
    def test_load_siso_rows(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        assert len(data["siso"]) >= 16, "SISO sheet should have at least 16 BW combination rows"

    def test_load_mimo_rows(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        assert len(data["mimo"]) >= 16, "MIMO sheet should have at least 16 BW combination rows"

    def test_service_mode_loaded(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        assert "service_mode" in data
        assert len(data["service_mode"]) == 2

    def test_physical_thresholds_loaded(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        assert len(data["physical"]) == 13

    def test_find_threshold_row_exact_match(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        row = mop_thresholds.find_threshold_row(data["siso"], 20, 100, 0)
        assert row is not None
        assert row["bw_lte"] == 20
        assert row["bw_nr_c1"] == 100
        assert row["bw_nr_c2"] == 0

    def test_find_threshold_row_no_match(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        row = mop_thresholds.find_threshold_row(data["siso"], 99, 99, 99)
        assert row is None

    def test_progressive_ul_sinr_22(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        row = mop_thresholds.find_threshold_row(data["siso"], 20, 100, 0)
        ul = mop_thresholds.get_progressive_ul_threshold(row, 22)
        assert ul is not None
        assert ul == row["ul_sinr_22"]

    def test_progressive_ul_below_min(self):
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        row = mop_thresholds.find_threshold_row(data["siso"], 20, 100, 0)
        assert mop_thresholds.get_progressive_ul_threshold(row, 10) is None

    def test_progressive_ul_interpolates_down(self):
        """SINR=23 should use level 22 (nearest lower)."""
        data = mop_thresholds.load_threshold_excel(THRESHOLD_EXCEL)
        row = mop_thresholds.find_threshold_row(data["siso"], 20, 100, 0)
        ul = mop_thresholds.get_progressive_ul_threshold(row, 23)
        assert ul == row["ul_sinr_22"]


# === rf_parameters tests ===

class TestRfParameters:
    def test_classify_rsrp_excellent(self):
        result = rf_parameters.classify_rsrp(-45)
        assert result["quality"] == "good"

    def test_classify_rsrp_poor(self):
        result = rf_parameters.classify_rsrp(-95)
        assert result["quality"] == "poor"

    def test_classify_sinr_excellent(self):
        result = rf_parameters.classify_sinr(30)
        assert result["quality"] == "excellent"

    def test_classify_sinr_poor(self):
        result = rf_parameters.classify_sinr(0)
        assert result["quality"] == "poor"

    def test_classify_rsrq_good(self):
        result = rf_parameters.classify_rsrq(-5)
        assert result["quality"] == "good"

    def test_generate_observation_rsrp(self):
        obs = rf_parameters.generate_observation("rsrp", -55)
        assert "good" in obs.lower() or "Good" in obs
        assert "-55" in obs

    def test_generate_observation_sinr_poor(self):
        obs = rf_parameters.generate_observation("sinr", 3)
        assert "interference" in obs.lower() or "poor" in obs.lower()

    def test_generate_observation_tx_elevated(self):
        obs = rf_parameters.generate_observation("tx_power", 5)
        assert "POSITIVE" in obs

    def test_generate_observation_dl_pass(self):
        obs = rf_parameters.generate_observation("dl", 200, threshold=150, mode="EN-DC")
        assert "PASS" in obs

    def test_generate_observation_dl_fail(self):
        obs = rf_parameters.generate_observation("dl", 50, threshold=150, mode="EN-DC")
        assert "FAIL" in obs
        assert "100" in obs  # delta


# === throughput_benchmarks tests ===

class TestThroughputBenchmarks:
    def test_lte_mimo_20mhz_dl(self):
        peak = throughput_benchmarks.get_theoretical_peak("LTE", "MIMO", 20, "dl")
        assert peak is not None
        assert peak["peak"] == 300
        assert peak["typical_das"] == 220

    def test_nr_siso_100mhz_dl(self):
        peak = throughput_benchmarks.get_theoretical_peak("NR", "SISO", 100, "dl")
        assert peak is not None
        assert peak["peak"] == 1000

    def test_unknown_tech_returns_none(self):
        assert throughput_benchmarks.get_theoretical_peak("5G", "MIMO", 20) is None

    def test_unknown_bw_returns_none(self):
        assert throughput_benchmarks.get_theoretical_peak("LTE", "MIMO", 99) is None

    def test_compute_efficiency(self):
        assert throughput_benchmarks.compute_throughput_efficiency(220, 300) == 73.3

    def test_compute_efficiency_zero_peak(self):
        assert throughput_benchmarks.compute_throughput_efficiency(100, 0) == 0.0


# === kpi_mappings tests ===

class TestKpiMappings:
    def test_low_rsrp_triggers_impacts(self):
        impacts = kpi_mappings.get_kpi_impacts({"rsrp": -80})
        assert len(impacts) > 0
        domains = {i["domain"] for i in impacts}
        assert "ACC" in domains
        assert "RET" in domains

    def test_low_sinr_triggers_impacts(self):
        impacts = kpi_mappings.get_kpi_impacts({"sinr": 12})
        assert len(impacts) > 0
        assert any(i["domain"] == "CAP" for i in impacts)

    def test_dl_fail_triggers_impacts(self):
        impacts = kpi_mappings.get_kpi_impacts({"dl_delta": -20})
        assert any(i["kpi"] == "DL User Throughput" for i in impacts)

    def test_no_impacts_when_all_good(self):
        impacts = kpi_mappings.get_kpi_impacts({
            "rsrp": -50, "sinr": 30, "rsrq": -5, "tx_power": -10,
        })
        assert len(impacts) == 0

    def test_sorted_by_domain_priority(self):
        impacts = kpi_mappings.get_kpi_impacts({
            "rsrp": -80, "sinr": 12, "rsrq": -14, "tx_power": 3
        })
        priority = ["AVL", "ACC", "RET", "CAP", "MOB", "PWR"]
        domain_order = [i["domain"] for i in impacts]
        indices = [priority.index(d) for d in domain_order]
        assert indices == sorted(indices)

    def test_format_kpi_impact_text(self):
        impacts = kpi_mappings.get_kpi_impacts({"rsrp": -80})
        text = kpi_mappings.format_kpi_impact_text(impacts)
        assert "[ACC]" in text
        assert "RRC Setup Success Rate" in text

    def test_format_empty_impacts(self):
        assert kpi_mappings.format_kpi_impact_text([]) == ""


# === KnowledgeEngine integration tests ===

class TestKnowledgeEngine:
    def test_load_all_modules(self, engine):
        assert engine.thresholds is not None
        assert len(engine.thresholds["siso"]) >= 16
        assert len(engine.thresholds["mimo"]) >= 16

    def test_rf_observation_rsrp_excellent(self, engine):
        obs = engine.get_rf_observation("rsrp", -45)
        assert "good" in obs.lower() or "Good" in obs

    def test_rf_observation_sinr_poor(self, engine):
        obs = engine.get_rf_observation("sinr", 3)
        assert "interference" in obs.lower() or "poor" in obs.lower()

    def test_throughput_context_lte_mimo_20mhz(self, engine):
        ctx = engine.get_throughput_context("LTE", "MIMO", 20, "dl")
        assert ctx["peak"] == 300

    def test_kpi_impacts_low_rsrp(self, engine):
        impacts = engine.get_kpi_impacts({"rsrp": -80})
        assert len(impacts) > 0

    def test_get_threshold_endc(self, engine):
        t = engine.get_threshold("MIMO", 20, 100, 0, "EN-DC")
        assert t is not None
        assert "dl_min" in t
        assert "dl_max" in t
        assert "progressive_ul" in t
        assert len(t["progressive_ul"]) == 8

    def test_get_threshold_lte_only(self, engine):
        t = engine.get_threshold("MIMO", 20, 0, 0, "LTE Only")
        # BW combo 20/0/0 should exist — row with bw_lte=20, nr_c1=0
        # This doesn't exist in the Excel (all rows have nr_c1>0 except none with lte=20,nr=0)
        # Actually checking: rows have bw_lte=5,5,0; 10,10,0; etc. LTE=20 NR=0 doesn't exist
        # so this should return None
        # Let's use a combo that exists: 10/10/0
        t = engine.get_threshold("MIMO", 10, 10, 0, "LTE Only")
        assert t is not None
        assert t["dl_min"] is not None

    def test_build_analysis_context(self, engine):
        cell = {
            "rsrp": -55, "sinr": 28, "rsrq": -5, "tx_power": -10,
            "dl_throughput": 250, "ul_throughput": 30,
            "tech": "LTE", "mimo_config": "MIMO",
            "bw_lte_mhz": 20, "bw_nr_c1_mhz": 100, "bw_nr_c2_mhz": 0,
            "conn_mode": "EN-DC",
        }
        ctx = engine.build_analysis_context(cell)
        assert "rf_observations" in ctx
        assert "throughput_context" in ctx
        assert "thresholds" in ctx
        assert "kpi_impacts" in ctx
        assert "kpi_impact_text" in ctx
        assert len(ctx["rf_observations"]) >= 4

    def test_no_kpi_impacts_when_all_pass(self, engine):
        cell = {
            "rsrp": -50, "sinr": 30, "rsrq": -5, "tx_power": -10,
            "dl_throughput": 900, "ul_throughput": 100,
            "tech": "LTE", "mimo_config": "MIMO",
            "bw_lte_mhz": 20, "bw_nr_c1_mhz": 100, "bw_nr_c2_mhz": 0,
            "conn_mode": "EN-DC",
        }
        ctx = engine.build_analysis_context(cell)
        assert len(ctx["kpi_impacts"]) == 0
