"""Tests for output_xlsx.py and output_docx.py — verify both generators create valid files.

Implementation: Claude Code Prompt 8 (Output Generation)
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.output_xlsx import OutputXlsxGenerator
from code.output_docx import OutputDocxGenerator

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "test"


@pytest.fixture
def config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def mock_results():
    """Minimal mock cell results — 3 cells covering PASS, FAIL, and edge cases."""
    return [
        {
            "bts": "SFY0803A",
            "tech_sector": "L19/Sector 1",
            "connection_mode": "LTE Only",
            "bandwidth": "20 MHz LTE",
            "pci": 101,
            "rsrp": -55.0,
            "rsrq": -5.0,
            "sinr": 28.0,
            "tx_power": -10.0,
            "sm_st_duration": 15,
            "dl_throughput": 85.5,
            "ul_throughput": 25.3,
            "comment": "PASS — DL 85.5 Mbps (min 50), UL 25.3 Mbps (min 15)",
            "observations": "RSRP -55 dBm — good signal within DAS thresholds. SINR 28 dB — excellent.",
            "recommendations": "No action required. All parameters within expected range.",
            "kpi_impact": "No negative KPI impact expected. Capacity and accessibility nominal.",
        },
        {
            "bts": "SFY0803A",
            "tech_sector": "N2500_C1 NSA/Sector 2",
            "connection_mode": "EN-DC",
            "bandwidth": "20 MHz LTE + 100 MHz NR",
            "pci": 202,
            "rsrp": -82.0,
            "rsrq": -9.5,
            "sinr": 12.0,
            "tx_power": 5.0,
            "sm_st_duration": 30,
            "dl_throughput": 120.0,
            "ul_throughput": 8.5,
            "comment": "FAIL — UL 8.5 Mbps (min 20). Delta: -11.5 Mbps",
            "observations": "RSRP -82 dBm — fair signal. SINR 12 dB — moderate interference. TX Power +5 dBm — ELEVATED.",
            "recommendations": "Investigate UL path loss. Check antenna feeder and splitter connections. TX power compensation indicates coverage issue.",
            "kpi_impact": "Potential ACC and RET KPI degradation. High TX power impacts PWR domain.",
        },
        {
            "bts": "SFY0803A",
            "tech_sector": "N2500_C1 SA/Sector 3",
            "connection_mode": "NR SA",
            "bandwidth": "100 MHz NR",
            "pci": 303,
            "rsrp": -68.0,
            "rsrq": -6.0,
            "sinr": 30.0,
            "tx_power": -15.0,
            "sm_st_duration": 10,
            "dl_throughput": 450.0,
            "ul_throughput": 95.0,
            "comment": "PASS — DL 450 Mbps (min 300), UL 95 Mbps (min 50)",
            "observations": "RSRP -68 dBm — good signal. SINR 30 dB — excellent quality.",
            "recommendations": "No issues detected. Performance within expected range for NR SA 100 MHz.",
            "kpi_impact": "All KPI domains nominal. NR SA throughput meets capacity targets.",
        },
    ]


@pytest.fixture
def mock_threshold_data():
    """Mock threshold data matching mop_thresholds.load_threshold_excel() output."""
    return {
        "service_mode": {
            "Radio End": {
                "rsrp_min": -60, "rsrp_max": -40, "sinr_min": 25,
                "rsrq_min": -12, "rsrq_max": -3, "tx_power": "negative",
            },
            "Antenna End": {
                "rsrp_min": -75, "rsrp_max": -50, "sinr_min": 25,
                "rsrq_min": -12, "rsrq_max": -3, "tx_power": "negative",
            },
        },
        "siso": [
            {
                "config": "SISO", "bw_lte": 20, "bw_nr_c1": 0, "bw_nr_c2": 0,
                "lte_dl_min": 50, "lte_dl_max": 75, "nr_dl_min": None, "nr_dl_max": None,
                "endc_dl_min": None, "endc_dl_max": None, "nrdc_dl_min": None, "nrdc_dl_max": None,
                "lte_ul_min": 15, "lte_ul_max": 30, "nr_ul_min": None, "nr_ul_max": None,
                "endc_ul_min": None, "endc_ul_max": None,
                "ul_sinr_15": None, "ul_sinr_19": None, "ul_sinr_20": None, "ul_sinr_22": None,
                "ul_sinr_24": None, "ul_sinr_26": None, "ul_sinr_28": None, "ul_sinr_30": None,
            },
        ],
        "mimo": [
            {
                "config": "MIMO", "bw_lte": 20, "bw_nr_c1": 100, "bw_nr_c2": 0,
                "lte_dl_min": 75, "lte_dl_max": 150, "nr_dl_min": 300, "nr_dl_max": 600,
                "endc_dl_min": 350, "endc_dl_max": 700, "nrdc_dl_min": None, "nrdc_dl_max": None,
                "lte_ul_min": 20, "lte_ul_max": 40, "nr_ul_min": 50, "nr_ul_max": 120,
                "endc_ul_min": 20, "endc_ul_max": 50,
                "ul_sinr_15": 10, "ul_sinr_19": 15, "ul_sinr_20": 18, "ul_sinr_22": 22,
                "ul_sinr_24": 28, "ul_sinr_26": 35, "ul_sinr_28": 42, "ul_sinr_30": 50,
            },
        ],
        "physical": [],
    }


@pytest.fixture
def mock_site_config():
    """Mock CIQ site configuration rows."""
    return [
        {"sector": "1", "technology": "LTE", "band": "B19", "bandwidth": "20 MHz", "mimo_config": "MIMO", "pci": 101, "earfcn": 6300},
        {"sector": "2", "technology": "NR", "band": "n41", "bandwidth": "100 MHz", "mimo_config": "MIMO", "pci": 202, "arfcn": 520000},
        {"sector": "3", "technology": "NR", "band": "n41", "bandwidth": "100 MHz", "mimo_config": "SISO", "pci": 303, "arfcn": 520000},
    ]


@pytest.fixture
def mock_analysis_data():
    """Mock aggregated analysis data for docx generator."""
    return {
        "site_id": "SFY0803A",
        "date": "2026-03-19",
        "kpi_impacts": [
            {
                "cell": "N2500_C1 NSA/Sector 2",
                "kpi_impact": "High TX power (+5 dBm) indicates UL coverage gap. ACC degradation from RRC setup failures. RET risk from radio link failures. PWR impact from UE battery drain.",
            },
        ],
    }


# =====================================================================
# OutputXlsxGenerator Tests
# =====================================================================

class TestOutputXlsxGenerate:
    """Test that generate() creates a valid .xlsx file."""

    def test_creates_file(self, config, mock_results, mock_threshold_data, tmp_path):
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "test_output.xlsx"
        result = gen.generate(mock_results, mock_threshold_data, out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_two_sheets(self, config, mock_results, mock_threshold_data, tmp_path):
        from openpyxl import load_workbook
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "test_output.xlsx"
        gen.generate(mock_results, mock_threshold_data, out)
        wb = load_workbook(str(out))
        assert "Validation Results" in wb.sheetnames
        assert "Thresholds Reference" in wb.sheetnames
        wb.close()

    def test_correct_row_count(self, config, mock_results, mock_threshold_data, tmp_path):
        from openpyxl import load_workbook
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "test_output.xlsx"
        gen.generate(mock_results, mock_threshold_data, out)
        wb = load_workbook(str(out))
        ws = wb["Validation Results"]
        # Header row + 3 data rows
        assert ws.max_row == 4
        wb.close()

    def test_header_values(self, config, mock_results, mock_threshold_data, tmp_path):
        from openpyxl import load_workbook
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "test_output.xlsx"
        gen.generate(mock_results, mock_threshold_data, out)
        wb = load_workbook(str(out))
        ws = wb["Validation Results"]
        headers = [ws.cell(row=1, column=i).value for i in range(1, 17)]
        from code.output_xlsx import COLUMNS
        assert headers == COLUMNS
        wb.close()

    def test_pass_fill_green(self, config, mock_results, mock_threshold_data, tmp_path):
        from openpyxl import load_workbook
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "test_output.xlsx"
        gen.generate(mock_results, mock_threshold_data, out)
        wb = load_workbook(str(out))
        ws = wb["Validation Results"]
        # Row 2 (first data row) should be PASS → green fill on Comment (col M=13)
        comment_cell = ws.cell(row=2, column=13)
        assert comment_cell.fill.start_color.rgb == "00C6EFCE"
        wb.close()

    def test_fail_fill_red(self, config, mock_results, mock_threshold_data, tmp_path):
        from openpyxl import load_workbook
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "test_output.xlsx"
        gen.generate(mock_results, mock_threshold_data, out)
        wb = load_workbook(str(out))
        ws = wb["Validation Results"]
        # Row 3 (second data row) should be FAIL → red fill on Comment
        comment_cell = ws.cell(row=3, column=13)
        assert comment_cell.fill.start_color.rgb == "00FFC7CE"
        wb.close()

    def test_threshold_tab_has_data(self, config, mock_results, mock_threshold_data, tmp_path):
        from openpyxl import load_workbook
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "test_output.xlsx"
        gen.generate(mock_results, mock_threshold_data, out)
        wb = load_workbook(str(out))
        ws = wb["Thresholds Reference"]
        # Should have content (SISO title + header + data + MIMO title + header + data + SM title + header + data)
        assert ws.max_row > 5
        wb.close()

    def test_empty_results(self, config, mock_threshold_data, tmp_path):
        gen = OutputXlsxGenerator(config)
        out = tmp_path / "empty_output.xlsx"
        result = gen.generate([], mock_threshold_data, out)
        assert result.exists()


# =====================================================================
# OutputDocxGenerator Tests
# =====================================================================

class TestOutputDocxGenerate:
    """Test that generate() creates a valid .docx file."""

    def test_creates_file(self, config, mock_results, mock_site_config, mock_analysis_data, tmp_path):
        gen = OutputDocxGenerator(config)
        out = tmp_path / "test_report.docx"
        result = gen.generate(mock_results, mock_site_config, mock_analysis_data, out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_has_title(self, config, mock_results, mock_site_config, mock_analysis_data, tmp_path):
        from docx import Document
        gen = OutputDocxGenerator(config)
        out = tmp_path / "test_report.docx"
        gen.generate(mock_results, mock_site_config, mock_analysis_data, out)
        doc = Document(str(out))
        # Check that title text is present somewhere in paragraphs
        all_text = " ".join(p.text for p in doc.paragraphs)
        assert "RF Throughput Analysis" in all_text
        assert "SFY0803A" in all_text

    def test_has_executive_summary(self, config, mock_results, mock_site_config, mock_analysis_data, tmp_path):
        from docx import Document
        gen = OutputDocxGenerator(config)
        out = tmp_path / "test_report.docx"
        gen.generate(mock_results, mock_site_config, mock_analysis_data, out)
        doc = Document(str(out))
        all_text = " ".join(p.text for p in doc.paragraphs)
        assert "Executive Summary" in all_text
        assert "3" in all_text  # total cell count

    def test_has_glossary(self, config, mock_results, mock_site_config, mock_analysis_data, tmp_path):
        from docx import Document
        gen = OutputDocxGenerator(config)
        out = tmp_path / "test_report.docx"
        gen.generate(mock_results, mock_site_config, mock_analysis_data, out)
        doc = Document(str(out))
        all_text = " ".join(p.text for p in doc.paragraphs)
        assert "Glossary" in all_text

    def test_has_tables(self, config, mock_results, mock_site_config, mock_analysis_data, tmp_path):
        from docx import Document
        gen = OutputDocxGenerator(config)
        out = tmp_path / "test_report.docx"
        gen.generate(mock_results, mock_site_config, mock_analysis_data, out)
        doc = Document(str(out))
        # Should have at least: site config table, RF params tables, summary table, band config table, glossary table
        assert len(doc.tables) >= 5

    def test_site_config_table(self, config, mock_results, mock_site_config, mock_analysis_data, tmp_path):
        from docx import Document
        gen = OutputDocxGenerator(config)
        out = tmp_path / "test_report.docx"
        gen.generate(mock_results, mock_site_config, mock_analysis_data, out)
        doc = Document(str(out))
        # First table after title page should be site config with 7 columns
        site_table = doc.tables[0]
        assert len(site_table.columns) == 7
        assert site_table.rows[0].cells[0].text == "Sector"

    def test_empty_results(self, config, mock_site_config, mock_analysis_data, tmp_path):
        gen = OutputDocxGenerator(config)
        out = tmp_path / "empty_report.docx"
        result = gen.generate([], mock_site_config, mock_analysis_data, out)
        assert result.exists()

    def test_kpi_section(self, config, mock_results, mock_site_config, mock_analysis_data, tmp_path):
        from docx import Document
        gen = OutputDocxGenerator(config)
        out = tmp_path / "test_report.docx"
        gen.generate(mock_results, mock_site_config, mock_analysis_data, out)
        doc = Document(str(out))
        all_text = " ".join(p.text for p in doc.paragraphs)
        assert "KPI Correlation" in all_text
        assert "ACC" in all_text  # KPI domain reference
