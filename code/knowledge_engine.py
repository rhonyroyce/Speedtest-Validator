"""Knowledge engine — loads and queries the 4 structured knowledge modules.

Aggregates RF parameter rules, throughput benchmarks, KPI mappings, and MOP
thresholds into a unified query interface. Does NOT use RAG/vector DB — all
lookups are direct Python dict access (~1ms vs ~260ms for RAG).

Implementation: Claude Code Prompt 5 (Knowledge Engine)
"""
import logging

from code.knowledge import rf_parameters, throughput_benchmarks, kpi_mappings, mop_thresholds

logger = logging.getLogger(__name__)

# Connection mode to DL/UL column prefix mapping
_CONN_MODE_DL_COL = {
    "LTE Only": ("lte_dl_min", "lte_dl_max"),
    "NR SA": ("nr_dl_min", "nr_dl_max"),
    "EN-DC": ("endc_dl_min", "endc_dl_max"),
    "NR-DC": ("nrdc_dl_min", "nrdc_dl_max"),
}

_CONN_MODE_UL_COL = {
    "LTE Only": ("lte_ul_min", "lte_ul_max"),
    "NR SA": ("nr_ul_min", "nr_ul_max"),
    "EN-DC": ("endc_ul_min", "endc_ul_max"),
}


class KnowledgeEngine:
    """Unified interface to all structured knowledge modules."""

    def __init__(self, config: dict):
        self.config = config
        self.thresholds = None

    def load_all(self) -> None:
        """Load thresholds from Excel and verify all knowledge dicts are accessible."""
        threshold_path = self.config.get("paths", {}).get(
            "threshold_excel", "./input/DAS_Validation_Thresholds.xlsx"
        )
        logger.info("Loading thresholds from %s", threshold_path)
        self.thresholds = mop_thresholds.load_threshold_excel(threshold_path)

        siso_count = len(self.thresholds.get("siso", []))
        mimo_count = len(self.thresholds.get("mimo", []))
        logger.info(
            "Loaded thresholds: %d SISO rows, %d MIMO rows, %d physical rules",
            siso_count,
            mimo_count,
            len(self.thresholds.get("physical", [])),
        )

        # Verify knowledge dicts are importable
        assert rf_parameters.RSRP_QUALITY, "RF parameters not loaded"
        assert throughput_benchmarks.THEORETICAL_DL_PEAKS, "Throughput benchmarks not loaded"
        assert kpi_mappings.RF_TO_KPI_MAPPINGS, "KPI mappings not loaded"

    def get_rf_observation(self, param: str, value: float, **context) -> str:
        """Generate an RF observation string.

        Delegates to rf_parameters.generate_observation().
        """
        return rf_parameters.generate_observation(param, value, **context)

    def get_throughput_context(
        self, tech: str, mimo: str, bw_mhz: int, direction: str = "dl"
    ) -> dict | None:
        """Look up theoretical peak and typical DAS throughput.

        Delegates to throughput_benchmarks.get_theoretical_peak().
        """
        return throughput_benchmarks.get_theoretical_peak(tech, mimo, bw_mhz, direction)

    def get_kpi_impacts(self, rf_data: dict) -> list[dict]:
        """Evaluate RF data against KPI impact rules.

        Delegates to kpi_mappings.get_kpi_impacts().
        """
        return kpi_mappings.get_kpi_impacts(rf_data)

    def get_kpi_impact_text(self, rf_data: dict) -> str:
        """Get formatted KPI impact text for the output column."""
        impacts = self.get_kpi_impacts(rf_data)
        return kpi_mappings.format_kpi_impact_text(impacts)

    def get_threshold(
        self,
        mimo_config: str,
        bw_lte: int,
        bw_nr_c1: int,
        bw_nr_c2: int,
        conn_mode: str,
    ) -> dict | None:
        """Look up speed test thresholds for a specific configuration.

        Args:
            mimo_config: "SISO" or "MIMO"
            bw_lte: LTE bandwidth in MHz (0 if not present)
            bw_nr_c1: NR C1 bandwidth in MHz (0 if not present)
            bw_nr_c2: NR C2 bandwidth in MHz (0 if not present)
            conn_mode: "LTE Only", "NR SA", "EN-DC", or "NR-DC"

        Returns:
            Dict with dl_min, dl_max, ul_min, ul_max, and progressive_ul dict,
            or None if no matching row found.
        """
        if self.thresholds is None:
            raise RuntimeError("Thresholds not loaded — call load_all() first")

        rows = self.thresholds.get(mimo_config.lower(), [])
        if not rows:
            logger.warning("No rows for config: %s", mimo_config)
            return None

        row = mop_thresholds.find_threshold_row(rows, bw_lte, bw_nr_c1, bw_nr_c2)
        if row is None:
            logger.warning(
                "No threshold row for %s: LTE=%d, NR_C1=%d, NR_C2=%d",
                mimo_config, bw_lte, bw_nr_c1, bw_nr_c2,
            )
            return None

        # Get DL columns for this connection mode
        dl_cols = _CONN_MODE_DL_COL.get(conn_mode)
        ul_cols = _CONN_MODE_UL_COL.get(conn_mode)

        result = {
            "mimo_config": mimo_config,
            "bw_lte": bw_lte,
            "bw_nr_c1": bw_nr_c1,
            "bw_nr_c2": bw_nr_c2,
            "conn_mode": conn_mode,
        }

        if dl_cols:
            result["dl_min"] = row.get(dl_cols[0])
            result["dl_max"] = row.get(dl_cols[1])

        if ul_cols:
            result["ul_min"] = row.get(ul_cols[0])
            result["ul_max"] = row.get(ul_cols[1])

        # Progressive UL thresholds (all SINR levels from the row)
        progressive = {}
        for sinr in mop_thresholds.PROGRESSIVE_UL_SINR_LEVELS:
            val = row.get(f"ul_sinr_{sinr}")
            if val is not None:
                progressive[sinr] = val
        result["progressive_ul"] = progressive

        return result

    def build_analysis_context(self, cell_data: dict) -> dict:
        """Assemble full context dict for LLM analysis prompt injection.

        Args:
            cell_data: Dict with extracted cell measurements:
                rsrp, sinr, rsrq, tx_power, dl_throughput, ul_throughput,
                tech, mimo_config, bw_lte_mhz, bw_nr_c1_mhz, bw_nr_c2_mhz,
                conn_mode, sinr_db (for progressive UL)

        Returns:
            Dict with rf_observations, throughput_context, thresholds,
            kpi_impacts, and kpi_impact_text ready for prompt injection.
        """
        context = {"cell_data": cell_data}

        # RF observations
        observations = []
        for param in ("rsrp", "sinr", "rsrq", "tx_power"):
            value = cell_data.get(param)
            if value is not None:
                obs = self.get_rf_observation(param, value)
                observations.append(obs)
        context["rf_observations"] = observations

        # Throughput context (theoretical peaks)
        tech = cell_data.get("tech", "LTE")
        mimo = cell_data.get("mimo_config", "MIMO")
        conn_mode = cell_data.get("conn_mode", "LTE Only")

        # Use primary bandwidth for peak lookup
        if conn_mode in ("NR SA", "NR-DC"):
            bw = cell_data.get("bw_nr_c1_mhz", 0)
            peak_tech = "NR"
        else:
            bw = cell_data.get("bw_lte_mhz", 0)
            peak_tech = tech if tech in ("LTE", "NR") else "LTE"

        dl_peak = self.get_throughput_context(peak_tech, mimo, bw, "dl")
        ul_peak = self.get_throughput_context(peak_tech, mimo, bw, "ul")
        context["throughput_context"] = {"dl": dl_peak, "ul": ul_peak}

        # Throughput efficiency
        dl_measured = cell_data.get("dl_throughput")
        if dl_measured is not None and dl_peak:
            context["dl_efficiency"] = throughput_benchmarks.compute_throughput_efficiency(
                dl_measured, dl_peak["peak"]
            )

        ul_measured = cell_data.get("ul_throughput")
        if ul_measured is not None and ul_peak:
            context["ul_efficiency"] = throughput_benchmarks.compute_throughput_efficiency(
                ul_measured, ul_peak["peak"]
            )

        # Speed test thresholds
        threshold = self.get_threshold(
            mimo,
            cell_data.get("bw_lte_mhz", 0),
            cell_data.get("bw_nr_c1_mhz", 0),
            cell_data.get("bw_nr_c2_mhz", 0),
            conn_mode,
        )
        context["thresholds"] = threshold

        # DL/UL pass/fail with observations
        if threshold and dl_measured is not None and threshold.get("dl_min") is not None:
            dl_obs = self.get_rf_observation(
                "dl", dl_measured, threshold=threshold["dl_min"], mode=conn_mode
            )
            observations.append(dl_obs)

        if threshold and ul_measured is not None and threshold.get("ul_min") is not None:
            ul_obs = self.get_rf_observation(
                "ul", ul_measured, threshold=threshold["ul_min"]
            )
            observations.append(ul_obs)

        # KPI impacts
        rf_data = {
            "rsrp": cell_data.get("rsrp"),
            "sinr": cell_data.get("sinr"),
            "rsrq": cell_data.get("rsrq"),
            "tx_power": cell_data.get("tx_power"),
        }
        if threshold and dl_measured is not None and threshold.get("dl_min") is not None:
            rf_data["dl_delta"] = dl_measured - threshold["dl_min"]
        if threshold and ul_measured is not None and threshold.get("ul_min") is not None:
            rf_data["ul_delta"] = ul_measured - threshold["ul_min"]

        impacts = self.get_kpi_impacts(rf_data)
        context["kpi_impacts"] = impacts
        context["kpi_impact_text"] = kpi_mappings.format_kpi_impact_text(impacts)

        return context
