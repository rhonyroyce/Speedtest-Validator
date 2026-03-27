"""Extraction validator — post-VLM sanity checks before CIQ correlation.

Validates extracted RF parameters against physical bounds and cross-checks
against CIQ data to catch VLM hallucinations early.

Sits between Phase 2 (VLM Extraction) and Phase 3 (CIQ Correlation).
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Physical bounds for RF parameters
# Values outside these ranges are physically impossible and indicate
# VLM extraction errors (hallucination, misread digits, wrong field).
# ---------------------------------------------------------------------------

PHYSICAL_BOUNDS: dict[str, dict[str, float | None]] = {
    # LTE parameters
    "rsrp_dbm":        {"min": -140.0, "max": -30.0},
    "rsrq_db":         {"min": -25.0,  "max": 0.0},
    "sinr_db":         {"min": -25.0,  "max": 50.0},
    "tx_power_dbm":    {"min": -50.0,  "max": 30.0},
    "earfcn":          {"min": 0,      "max": 262143},
    "pci":             {"min": 0,      "max": 503},
    "bandwidth_mhz":   {"min": 1.4,    "max": 100.0},
    "band":            {"min": 1,      "max": 256},
    # NR parameters
    "nr5g_rsrp_dbm":   {"min": -156.0, "max": -30.0},
    "nr5g_rsrq_db":    {"min": -25.0,  "max": 0.0},
    "nr5g_sinr_db":    {"min": -25.0,  "max": 50.0},
    "nr_tx_power_dbm": {"min": -50.0,  "max": 30.0},
    "nr_arfcn":        {"min": 0,      "max": 3279165},
    "nr_pci":          {"min": 0,      "max": 1007},
    "nr_bandwidth_mhz": {"min": 5.0,   "max": 400.0},
    "nr_band":         {"min": 1,      "max": 512},
    "nr_bler_pct":     {"min": 0.0,    "max": 100.0},
    "nr_dl_scheduling_pct": {"min": 0.0, "max": 100.0},
    "nr_scs_khz":      {"min": 15,     "max": 240},
    "nr_ant_max_rsrp":  {"min": -156.0, "max": -30.0},
    "nr_ant_min_rsrp":  {"min": -156.0, "max": -30.0},
    "endc_total_tx_power_dbm": {"min": -50.0, "max": 30.0},
    "nr_rx0_rsrp":     {"min": -156.0, "max": -30.0},
    "nr_rx1_rsrp":     {"min": -156.0, "max": -30.0},
    "nr_rx2_rsrp":     {"min": -156.0, "max": -30.0},
    "nr_rx3_rsrp":     {"min": -156.0, "max": -30.0},
    # Speedtest parameters
    "dl_throughput_mbps": {"min": 0.0, "max": 10000.0},
    "ul_throughput_mbps": {"min": 0.0, "max": 5000.0},
    "ping_idle_ms":      {"min": 0.0, "max": 5000.0},
    "ping_dl_ms":        {"min": 0.0, "max": 5000.0},
    "ping_ul_ms":        {"min": 0.0, "max": 5000.0},
    "jitter_ms":         {"min": 0.0, "max": 1000.0},
    "packet_loss_pct":   {"min": 0.0, "max": 100.0},
}


def _deep_get(data: dict, key: str) -> Any:
    """Search for a key in a nested dict structure.

    Searches top-level keys first, then recurses into nested dicts.
    Returns the first match found, or None if not found.

    Args:
        data: Nested dict (e.g., extracted service mode data).
        key: Key to search for.

    Returns:
        Value if found, None otherwise.
    """
    if key in data:
        return data[key]

    for v in data.values():
        if isinstance(v, dict):
            result = _deep_get(v, key)
            if result is not None:
                return result

    return None


def validate_extraction(
    extracted: dict,
    ciq_data: dict | None = None,
) -> dict[str, Any]:
    """Validate VLM-extracted data against physical bounds and CIQ.

    Args:
        extracted: Extracted data dict from ScreenshotParser (service_mode or speedtest).
        ciq_data: Optional CIQ row dict for cross-validation (EARFCN, PCI, bandwidth).

    Returns:
        Dict with:
            valid (bool): True if no critical flags.
            flags (list[str]): Human-readable warning/error strings.
            ciq_mismatches (list[str]): Fields that don't match CIQ data.
    """
    flags: list[str] = []
    ciq_mismatches: list[str] = []

    # --- 1. Physical bounds check ---
    for param, bounds in PHYSICAL_BOUNDS.items():
        value = _deep_get(extracted, param)
        if value is None:
            continue

        try:
            val = float(value)
        except (TypeError, ValueError):
            continue

        lo = bounds.get("min")
        hi = bounds.get("max")

        if lo is not None and val < lo:
            flags.append(f"{param}={val} below physical minimum {lo}")
        if hi is not None and val > hi:
            flags.append(f"{param}={val} above physical maximum {hi}")

    # --- 2. Internal consistency checks ---
    lte = extracted.get("lte_params") or {}
    nr = extracted.get("nr_params") or {}

    # RSRP should be more negative than RSRQ (RSRP ≤ RSRQ in magnitude terms)
    rsrp = lte.get("rsrp_dbm")
    rsrq = lte.get("rsrq_db")
    if rsrp is not None and rsrq is not None:
        try:
            if float(rsrp) > float(rsrq):
                flags.append(
                    f"LTE RSRP ({rsrp}) > RSRQ ({rsrq}) — unusual, possible field swap"
                )
        except (TypeError, ValueError):
            pass

    # NR antenna max should be >= min
    ant_max = nr.get("nr_ant_max_rsrp")
    ant_min = nr.get("nr_ant_min_rsrp")
    if ant_max is not None and ant_min is not None:
        try:
            if float(ant_max) < float(ant_min):
                flags.append(
                    f"NR ant_max_rsrp ({ant_max}) < ant_min_rsrp ({ant_min}) — swapped"
                )
        except (TypeError, ValueError):
            pass

    # --- 3. CIQ cross-validation ---
    if ciq_data:
        # EARFCN match
        ext_earfcn = lte.get("earfcn")
        ciq_earfcn = ciq_data.get("earfcnDl")
        if ext_earfcn is not None and ciq_earfcn is not None:
            try:
                if int(ext_earfcn) != int(ciq_earfcn):
                    ciq_mismatches.append(
                        f"EARFCN: extracted={ext_earfcn} vs CIQ={ciq_earfcn}"
                    )
            except (TypeError, ValueError):
                pass

        # NR ARFCN match
        ext_arfcn = nr.get("nr_arfcn")
        ciq_arfcn = ciq_data.get("arfcnDl")
        if ext_arfcn is not None and ciq_arfcn is not None:
            try:
                if int(ext_arfcn) != int(ciq_arfcn):
                    ciq_mismatches.append(
                        f"NR ARFCN: extracted={ext_arfcn} vs CIQ={ciq_arfcn}"
                    )
            except (TypeError, ValueError):
                pass

        # PCI match
        ext_pci = lte.get("pci") or nr.get("nr_pci")
        ciq_pci = ciq_data.get("pci") or ciq_data.get("physicalCellId")
        if ext_pci is not None and ciq_pci is not None:
            try:
                if int(ext_pci) != int(ciq_pci):
                    ciq_mismatches.append(
                        f"PCI: extracted={ext_pci} vs CIQ={ciq_pci}"
                    )
            except (TypeError, ValueError):
                pass

    # --- Determine validity ---
    # Critical flags: values outside physical bounds
    has_critical = any(
        "below physical minimum" in f or "above physical maximum" in f
        for f in flags
    )

    return {
        "valid": not has_critical,
        "flags": flags,
        "ciq_mismatches": ciq_mismatches,
    }
