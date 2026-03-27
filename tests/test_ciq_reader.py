"""Tests for ciq_reader.py — CIQ Excel parsing and cell matching.

Implementation: Claude Code Prompt 10 (Testing)
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.ciq_reader import CIQReader
from code.utils.excel_utils import convert_bw_khz_to_mhz

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
CIQ_PATH = Path(__file__).resolve().parent.parent / "input" / "SFY0803A_MMBB_CIQ_EXPORT_20251127_173752.xlsx"


@pytest.fixture
def config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def reader(config):
    r = CIQReader(config)
    r.load(CIQ_PATH)
    return r


# ---------------------------------------------------------------------------
# Loading tests
# ---------------------------------------------------------------------------

class TestLoadCells:
    def test_load_eutran_parameters(self, reader):
        """Verify LTE cells loaded from eUtran Parameters sheet."""
        lte = reader.get_lte_cells()
        assert len(lte) == 6
        # Each cell should have required fields
        for cell in lte:
            assert "cellId" in cell
            assert "earfcnDl" in cell
            assert "dlChannelBandwidth" in cell
            assert "noOfTxAntennas" in cell

    def test_load_gutran_cells(self, reader):
        """Verify NR cells loaded from gUtranCell info sheet."""
        nr = reader.get_nr_cells()
        assert len(nr) == 15
        for cell in nr:
            assert "gUtranCell" in cell
            assert "arfcnDl" in cell
            assert "channelBandwidth" in cell

    def test_lte_cells_have_pci(self, reader):
        """LTE cells should have PCI from the PCI sheet join."""
        lte = reader.get_lte_cells()
        pci_count = sum(1 for c in lte if c["PCI"] is not None and c["PCI"] != 0)
        assert pci_count > 0, "At least some LTE cells should have PCI mapped"

    def test_nr_cells_have_pci(self, reader):
        """NR cells should have PCI directly from gUtranCell sheet."""
        nr = reader.get_nr_cells()
        pci_count = sum(1 for c in nr if c["PCI"] is not None and c["PCI"] != 0)
        assert pci_count > 0


# ---------------------------------------------------------------------------
# Bandwidth conversion tests
# ---------------------------------------------------------------------------

class TestBandwidthConversion:
    def test_bandwidth_conversion_20000(self):
        """20000 kHz → 20.0 MHz."""
        assert convert_bw_khz_to_mhz(20000) == 20.0

    def test_bandwidth_conversion_100000(self):
        """100000 kHz → 100.0 MHz."""
        assert convert_bw_khz_to_mhz(100000) == 100.0

    def test_bandwidth_conversion_5000(self):
        """5000 kHz → 5.0 MHz."""
        assert convert_bw_khz_to_mhz(5000) == 5.0

    def test_bandwidth_conversion_10000(self):
        """10000 kHz → 10.0 MHz."""
        assert convert_bw_khz_to_mhz(10000) == 10.0

    def test_lte_bandwidth_in_mhz(self, reader):
        """Verify LTE cell bandwidth is already converted to MHz during load."""
        lte = reader.get_lte_cells()
        for cell in lte:
            bw = cell["dlChannelBandwidth"]
            # Should be in MHz (small numbers like 5, 10, 15, 20), not kHz (5000, 10000, etc.)
            assert bw <= 100, f"Bandwidth {bw} looks like kHz, not MHz"


# ---------------------------------------------------------------------------
# MIMO detection tests
# ---------------------------------------------------------------------------

class TestMimoDetection:
    def test_mimo_detection_siso(self, reader):
        """noOfTxAntennas=1 → SISO."""
        cell = {"noOfTxAntennas": 1}
        assert reader.get_mimo_config(cell) == "SISO"

    def test_mimo_detection_mimo_2(self, reader):
        """noOfTxAntennas=2 → MIMO."""
        cell = {"noOfTxAntennas": 2}
        assert reader.get_mimo_config(cell) == "MIMO"

    def test_mimo_detection_mimo_4(self, reader):
        """noOfTxAntennas=4 → MIMO."""
        cell = {"noOfTxAntennas": 4}
        assert reader.get_mimo_config(cell) == "MIMO"

    def test_mimo_detection_zero(self, reader):
        """noOfTxAntennas=0 → SISO (fallback)."""
        cell = {"noOfTxAntennas": 0}
        assert reader.get_mimo_config(cell) == "SISO"

    def test_mimo_detection_missing(self, reader):
        """Missing noOfTxAntennas → SISO (fallback)."""
        cell = {}
        assert reader.get_mimo_config(cell) == "SISO"


# ---------------------------------------------------------------------------
# Cell matching tests
# ---------------------------------------------------------------------------

class TestMatchCell:
    def test_match_by_earfcn(self, reader):
        """Find LTE cell by EARFCN."""
        lte = reader.get_lte_cells()
        target_earfcn = lte[0]["earfcnDl"]
        matched = reader.match_cell(earfcn=target_earfcn)
        assert matched is not None
        assert matched["earfcnDl"] == target_earfcn

    def test_match_by_arfcn(self, reader):
        """Find NR cell by ARFCN."""
        nr = reader.get_nr_cells()
        target_arfcn = nr[0]["arfcnDl"]
        matched = reader.match_cell(arfcn=target_arfcn)
        assert matched is not None
        assert matched["arfcnDl"] == target_arfcn

    def test_match_by_pci(self, reader):
        """Find cell by PCI (fallback search)."""
        nr = reader.get_nr_cells()
        # Find a cell with a valid PCI
        target_cell = next((c for c in nr if c["PCI"] and c["PCI"] != 0), None)
        if target_cell:
            matched = reader.match_cell(pci=target_cell["PCI"])
            assert matched is not None
            assert matched["PCI"] == target_cell["PCI"]

    def test_match_earfcn_with_pci_tiebreaker(self, reader):
        """EARFCN + PCI narrows to exact cell."""
        lte = reader.get_lte_cells()
        target = lte[0]
        matched = reader.match_cell(
            earfcn=target["earfcnDl"],
            pci=target["PCI"],
        )
        assert matched is not None
        assert matched["cellId"] == target["cellId"]

    def test_match_no_match(self, reader):
        """No match returns None."""
        matched = reader.match_cell(earfcn=999999)
        assert matched is None

    def test_match_all_none(self, reader):
        """All params None returns None."""
        matched = reader.match_cell()
        assert matched is None


# ---------------------------------------------------------------------------
# Bandwidth accessor tests
# ---------------------------------------------------------------------------

class TestGetBandwidthMhz:
    def test_lte_bandwidth(self, reader):
        """Get bandwidth for LTE cell."""
        lte = reader.get_lte_cells()
        bw = reader.get_bandwidth_mhz(lte[0])
        assert bw > 0

    def test_nr_bandwidth(self, reader):
        """Get bandwidth for NR cell."""
        nr = reader.get_nr_cells()
        bw = reader.get_bandwidth_mhz(nr[0])
        assert bw > 0

    def test_empty_cell(self, reader):
        """Empty cell returns 0.0."""
        assert reader.get_bandwidth_mhz({}) == 0.0


# ---------------------------------------------------------------------------
# Sector mapping tests
# ---------------------------------------------------------------------------

class TestSectorMapping:
    def test_sector_extraction(self):
        """Verify sector number extracted from cell name."""
        assert CIQReader._extract_sector("LSFY0803A11") == 1
        assert CIQReader._extract_sector("ASFY0803A31") == 3
        assert CIQReader._extract_sector("NSFY0803A21") == 2

    def test_site_config_summary(self, reader):
        """Verify cells grouped by sector."""
        summary = reader.get_site_config_summary()
        assert len(summary) > 0
        for sector, cells in summary.items():
            assert "lte" in cells
            assert "nr" in cells

    def test_missing_ciq_raises_error(self, config):
        """FileNotFoundError for nonexistent CIQ file."""
        r = CIQReader(config)
        with pytest.raises(FileNotFoundError):
            r.load("/nonexistent/ciq.xlsx")
