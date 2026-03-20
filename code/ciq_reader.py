"""CIQ Excel parser — extracts per-cell configuration from eUtran Parameters and gUtranCell sheets.

Key fields: dlChannelBandwidth (kHz→MHz), noOfTxAntennas (SISO/MIMO), earfcnDl, PCI, radioType.

Implementation: Claude Code Prompt 4 (CIQ Reader)
"""
import logging
from collections import defaultdict
from pathlib import Path

from code.utils.excel_utils import convert_bw_khz_to_mhz, read_sheet_as_dicts, safe_int

logger = logging.getLogger(__name__)


class CIQReader:
    """Reads and queries T-Mobile CIQ Excel exports."""

    def __init__(self, config: dict):
        self._config = config
        self._lte_cells: list[dict] = []
        self._nr_cells: list[dict] = []
        self._pci_map: dict[str, int] = {}  # EutranCellFDDId -> PCI

    def load(self, ciq_path: str | Path) -> None:
        """Load CIQ Excel and parse LTE + NR cell lists.

        Args:
            ciq_path: Path to CIQ .xlsx export file
        """
        ciq_path = Path(ciq_path)
        if not ciq_path.exists():
            raise FileNotFoundError(f"CIQ file not found: {ciq_path}")

        logger.info("Loading CIQ from %s", ciq_path)

        # Load PCI mapping from PCI sheet (LTE cells don't have PCI in eUtran Parameters)
        pci_rows = read_sheet_as_dicts(ciq_path, "PCI")
        for row in pci_rows:
            cell_name = row.get("EutranCellFDDId")
            pci = row.get("PCI")
            if cell_name is not None and pci is not None:
                self._pci_map[str(cell_name)] = safe_int(pci)

        # Parse eUtran Parameters → LTE cells
        lte_rows = read_sheet_as_dicts(ciq_path, "eUtran Parameters")
        self._lte_cells = []
        for row in lte_rows:
            cell_id = row.get("EutranCellFDDId", "")
            bw_khz = safe_int(row.get("dlChannelBandwidth"), 0)
            self._lte_cells.append({
                "eNBId": safe_int(row.get("eNBId")),
                "cellId": str(cell_id),
                "earfcnDl": safe_int(row.get("earfcnDl")),
                "dlChannelBandwidth": convert_bw_khz_to_mhz(bw_khz) if bw_khz else 0.0,
                "noOfTxAntennas": safe_int(row.get("noOfTxAntennas")),
                "PCI": self._pci_map.get(str(cell_id)),
                "radioType": row.get("radioType", ""),
            })
        logger.info("Loaded %d LTE cells from eUtran Parameters", len(self._lte_cells))

        # Parse gUtranCell info → NR cells
        nr_rows = read_sheet_as_dicts(ciq_path, "gUtranCell info")
        self._nr_cells = []
        for row in nr_rows:
            bw_khz = safe_int(row.get("channelBandwidth"), 0)
            self._nr_cells.append({
                "gNBID": safe_int(row.get("gNBID")),
                "gUtranCell": str(row.get("gUtranCell", "")),
                "arfcnDl": safe_int(row.get("arfcnDl")),
                "channelBandwidth": convert_bw_khz_to_mhz(bw_khz) if bw_khz else 0.0,
                "PCI": safe_int(row.get("PCI")),
                "radioType": row.get("radioType", ""),
                "configuredMaxTxPower": safe_int(row.get("configuredMaxTxPower")),
            })
        logger.info("Loaded %d NR cells from gUtranCell info", len(self._nr_cells))

    def get_lte_cells(self) -> list[dict]:
        """Return list of parsed LTE cell dicts."""
        return self._lte_cells

    def get_nr_cells(self) -> list[dict]:
        """Return list of parsed NR cell dicts."""
        return self._nr_cells

    def match_cell(self, earfcn: int | None = None, arfcn: int | None = None,
                   pci: int | None = None) -> dict | None:
        """Find a matching CIQ cell entry by EARFCN, ARFCN, or PCI.

        Search priority: EARFCN (LTE) → ARFCN (NR) → PCI (both).
        If multiple match, PCI is used as a tiebreaker when provided alongside freq.

        Returns:
            Matching cell dict, or None
        """
        # Search LTE by EARFCN
        if earfcn is not None:
            candidates = [c for c in self._lte_cells if c["earfcnDl"] == earfcn]
            if candidates and pci is not None:
                pci_match = [c for c in candidates if c["PCI"] == pci]
                if pci_match:
                    return pci_match[0]
            if candidates:
                return candidates[0]

        # Search NR by ARFCN
        if arfcn is not None:
            candidates = [c for c in self._nr_cells if c["arfcnDl"] == arfcn]
            if candidates and pci is not None:
                pci_match = [c for c in candidates if c["PCI"] == pci]
                if pci_match:
                    return pci_match[0]
            if candidates:
                return candidates[0]

        # Fallback: search by PCI across both lists
        if pci is not None:
            for cell in self._lte_cells:
                if cell["PCI"] == pci:
                    return cell
            for cell in self._nr_cells:
                if cell["PCI"] == pci:
                    return cell

        return None

    def get_mimo_config(self, cell: dict) -> str:
        """Determine SISO or MIMO from noOfTxAntennas.

        Args:
            cell: Cell dict (LTE or NR)

        Returns:
            "SISO" if 1 antenna, "MIMO" if 2+
        """
        tx = cell.get("noOfTxAntennas", 0)
        return "SISO" if tx <= 1 else "MIMO"

    def get_bandwidth_mhz(self, cell: dict) -> float:
        """Return bandwidth in MHz (already converted from kHz during load).

        Args:
            cell: Cell dict with dlChannelBandwidth (LTE) or channelBandwidth (NR)
        """
        return cell.get("dlChannelBandwidth") or cell.get("channelBandwidth") or 0.0

    def get_site_config_summary(self) -> dict:
        """Summarize all cells grouped by sector for output generation.

        Returns:
            Dict keyed by sector number, each containing lists of LTE and NR cells.
            Sector is derived from the cell name pattern (digit before last two chars).
        """
        summary: dict[int, dict[str, list]] = defaultdict(lambda: {"lte": [], "nr": []})

        for cell in self._lte_cells:
            sector = self._extract_sector(cell["cellId"])
            summary[sector]["lte"].append(cell)

        for cell in self._nr_cells:
            sector = self._extract_sector(cell["gUtranCell"])
            summary[sector]["nr"].append(cell)

        return dict(summary)

    @staticmethod
    def _extract_sector(cell_name: str) -> int:
        """Extract sector number from cell name.

        Convention: sector digit is at position [-2] in the cell name.
        E.g., LSFY0803A11 → sector 1, ASFY0803A31 → sector 3
        """
        if len(cell_name) >= 2:
            try:
                return int(cell_name[-2])
            except ValueError:
                pass
        return 0
