"""Threshold engine — multi-dimensional pass/fail logic from DAS_Validation_Thresholds.xlsx.

Speed test thresholds are a 5-dimensional lookup:
  (1) SISO vs MIMO  (2) BW LTE MHz  (3) BW NR C1 MHz  (4) BW NR C2 MHz  (5) Connection Mode

Loads thresholds from Excel at runtime — NEVER hardcode speed test values.
Service mode thresholds use DAS_SERVICE_MODE_THRESHOLDS from rf_parameters.

Implementation: Claude Code Prompt 6 (Threshold Engine)
"""
import logging

from .knowledge import rf_parameters, mop_thresholds

logger = logging.getLogger(__name__)


class ThresholdEngine:
    """Multi-dimensional pass/fail engine for DAS RF validation."""

    def __init__(self, config: dict, knowledge_engine):
        self.config = config
        self.knowledge_engine = knowledge_engine
        self.service_mode = None
        self.siso = None
        self.mimo = None
        self.physical = None

    def load_thresholds(self) -> None:
        """Load threshold data from knowledge engine.

        Requires knowledge_engine.load_all() to have been called first.
        """
        thresholds = self.knowledge_engine.thresholds
        if thresholds is None:
            raise RuntimeError(
                "Knowledge engine thresholds not loaded — call knowledge_engine.load_all() first"
            )

        self.service_mode = thresholds.get("service_mode", {})
        self.siso = thresholds.get("siso", [])
        self.mimo = thresholds.get("mimo", [])
        self.physical = thresholds.get("physical", [])

        logger.info(
            "ThresholdEngine loaded: %d SISO rows, %d MIMO rows, %d physical rules",
            len(self.siso),
            len(self.mimo),
            len(self.physical),
        )

    def check_service_mode(
        self,
        rsrp: float,
        sinr: float,
        rsrq: float,
        tx_power: float,
        end_type: str = "radio_end",
    ) -> dict:
        """Check RF parameters against service mode thresholds.

        Args:
            rsrp: Measured RSRP in dBm
            sinr: Measured SINR in dB
            rsrq: Measured RSRQ in dB
            tx_power: Measured TX power in dBm
            end_type: "radio_end" or "antenna_end"

        Returns:
            Dict keyed by parameter, each with value, min, max, pass_fail, delta.
        """
        thresholds = rf_parameters.DAS_SERVICE_MODE_THRESHOLDS.get(end_type)
        if thresholds is None:
            raise ValueError(f"Unknown end_type: {end_type}")

        results = {}

        # RSRP
        rsrp_t = thresholds["rsrp"]
        rsrp_min, rsrp_max = rsrp_t["min"], rsrp_t["max"]
        if rsrp is not None:
            results["rsrp"] = {
                "value": rsrp,
                "min": rsrp_min,
                "max": rsrp_max,
                "pass_fail": "PASS" if rsrp_min <= rsrp <= rsrp_max else "FAIL",
                "delta": round(rsrp - rsrp_min, 2) if rsrp < rsrp_min else (
                    round(rsrp - rsrp_max, 2) if rsrp > rsrp_max else 0
                ),
            }
        else:
            results["rsrp"] = {"value": None, "min": rsrp_min, "max": rsrp_max, "pass_fail": "N/A", "delta": 0}

        # SINR
        sinr_t = thresholds["sinr"]
        sinr_min = sinr_t["min"]
        if sinr is not None:
            results["sinr"] = {
                "value": sinr,
                "min": sinr_min,
                "max": None,
                "pass_fail": "PASS" if sinr >= sinr_min else "FAIL",
                "delta": round(sinr - sinr_min, 2),
            }
        else:
            results["sinr"] = {"value": None, "min": sinr_min, "max": None, "pass_fail": "N/A", "delta": 0}

        # RSRQ
        rsrq_t = thresholds["rsrq"]
        rsrq_min, rsrq_max = rsrq_t["min"], rsrq_t["max"]
        if rsrq is not None:
            results["rsrq"] = {
                "value": rsrq,
                "min": rsrq_min,
                "max": rsrq_max,
                "pass_fail": "PASS" if rsrq_min <= rsrq <= rsrq_max else "FAIL",
                "delta": round(rsrq - rsrq_min, 2) if rsrq < rsrq_min else (
                    round(rsrq - rsrq_max, 2) if rsrq > rsrq_max else 0
                ),
            }
        else:
            results["rsrq"] = {"value": None, "min": rsrq_min, "max": rsrq_max, "pass_fail": "N/A", "delta": 0}

        # TX Power — must always be negative
        if tx_power is not None:
            results["tx_power"] = {
                "value": tx_power,
                "min": None,
                "max": 0,
                "pass_fail": "PASS" if tx_power < 0 else "FAIL",
                "delta": round(tx_power, 2),
            }
        else:
            results["tx_power"] = {"value": None, "min": None, "max": 0, "pass_fail": "N/A", "delta": 0}

        return results

    def check_speed_test(
        self,
        dl_mbps: float,
        ul_mbps: float,
        mimo_config: str,
        bw_lte_mhz: int,
        bw_nr_c1_mhz: int,
        bw_nr_c2_mhz: int,
        connection_mode: str,
        sinr_db: float | None = None,
    ) -> dict:
        """Check speed test results against multi-dimensional thresholds.

        5-dimensional lookup:
          1. SISO/MIMO → select sheet
          2. (bw_lte, bw_nr_c1, bw_nr_c2) → find row
          3. connection_mode → select DL column
          4. connection_mode (+ sinr for EN-DC UL) → select UL column
          5. PASS if measured >= min

        Args:
            dl_mbps: Measured DL throughput in Mbps
            ul_mbps: Measured UL throughput in Mbps
            mimo_config: "SISO" or "MIMO"
            bw_lte_mhz: LTE bandwidth in MHz (0 if not present)
            bw_nr_c1_mhz: NR C1 bandwidth in MHz (0 if not present)
            bw_nr_c2_mhz: NR C2 bandwidth in MHz (0 if not present)
            connection_mode: "LTE Only", "NR SA", "EN-DC", or "NR-DC"
            sinr_db: Measured SINR in dB (used for EN-DC progressive UL)

        Returns:
            Dict with dl, ul results, connection_mode, bw_combo.
        """
        # Step 1: Get threshold via knowledge engine
        threshold = self.knowledge_engine.get_threshold(
            mimo_config, bw_lte_mhz, bw_nr_c1_mhz, bw_nr_c2_mhz, connection_mode
        )

        bw_combo = f"LTE {bw_lte_mhz} / NR C1 {bw_nr_c1_mhz} / NR C2 {bw_nr_c2_mhz}"

        if threshold is None:
            logger.warning(
                "No threshold row found for %s %s", mimo_config, bw_combo
            )
            return {
                "dl": {
                    "value": dl_mbps,
                    "threshold_min": None,
                    "threshold_max": None,
                    "pass_fail": "NO_THRESHOLD",
                    "delta": None,
                },
                "ul": {
                    "value": ul_mbps,
                    "threshold_min": None,
                    "threshold_max": None,
                    "pass_fail": "NO_THRESHOLD",
                    "delta": None,
                },
                "connection_mode": connection_mode,
                "bw_combo": bw_combo,
            }

        # Step 3: DL check
        dl_min = threshold.get("dl_min")
        dl_max = threshold.get("dl_max")
        dl_result = self._check_throughput(dl_mbps, dl_min, dl_max)

        # Step 4: UL check — for EN-DC, use progressive UL if sinr_db provided
        ul_min = threshold.get("ul_min")
        ul_max = threshold.get("ul_max")

        if connection_mode == "EN-DC" and sinr_db is not None:
            progressive = threshold.get("progressive_ul", {})
            prog_ul = self._get_progressive_ul(progressive, sinr_db)
            if prog_ul is not None:
                ul_min = prog_ul

        ul_result = self._check_throughput(ul_mbps, ul_min, ul_max)

        return {
            "dl": dl_result,
            "ul": ul_result,
            "connection_mode": connection_mode,
            "bw_combo": bw_combo,
        }

    def get_comment(
        self,
        service_mode_result: dict,
        speed_test_result: dict,
    ) -> str:
        """Generate the Comment column text combining service mode and speed test results.

        Args:
            service_mode_result: Output from check_service_mode()
            speed_test_result: Output from check_speed_test()

        Returns:
            Human-readable comment string, e.g.:
              "PASS — DL 285 Mbps (min 200), UL 45 Mbps (min 30)"
              "FAIL — DL 85 Mbps below 200 Mbps min (delta: -115 Mbps)"
        """
        parts = []
        overall = "PASS"

        # Service mode failures
        sm_failures = []
        for param, result in service_mode_result.items():
            if result["pass_fail"] == "FAIL":
                overall = "FAIL"
                val = result["value"]
                if result["min"] is not None and val < result["min"]:
                    sm_failures.append(
                        f"{param.upper()} {val} below {result['min']} min"
                    )
                elif result["max"] is not None and val > result["max"]:
                    sm_failures.append(
                        f"{param.upper()} {val} above {result['max']} max"
                    )
                else:
                    sm_failures.append(f"{param.upper()} {val} FAIL")

        if sm_failures:
            parts.append("SM: " + "; ".join(sm_failures))

        # Speed test results
        dl = speed_test_result.get("dl", {})
        ul = speed_test_result.get("ul", {})

        if dl.get("pass_fail") == "FAIL":
            overall = "FAIL"
            parts.append(
                f"DL {dl['value']} Mbps below {dl['threshold_min']} Mbps min "
                f"(delta: {dl['delta']} Mbps)"
            )
        elif dl.get("pass_fail") == "PASS":
            parts.append(
                f"DL {dl['value']} Mbps (min {dl['threshold_min']})"
            )

        if ul.get("pass_fail") == "FAIL":
            overall = "FAIL"
            parts.append(
                f"UL {ul['value']} Mbps below {ul['threshold_min']} Mbps min "
                f"(delta: {ul['delta']} Mbps)"
            )
        elif ul.get("pass_fail") == "PASS":
            parts.append(
                f"UL {ul['value']} Mbps (min {ul['threshold_min']})"
            )

        detail = ", ".join(parts) if parts else "No data"
        return f"{overall} — {detail}"

    def summarize_cell(self, all_results: dict) -> dict:
        """Aggregate pass/fail across service mode + speed test for a single cell.

        Args:
            all_results: Dict with 'service_mode' and 'speed_test' keys,
                         each containing check results.

        Returns:
            Dict with overall_pass_fail, sm_pass_fail, st_pass_fail, failed_params list,
            and comment string.
        """
        sm = all_results.get("service_mode", {})
        st = all_results.get("speed_test", {})

        sm_pass = all(
            r["pass_fail"] == "PASS" for r in sm.values()
        ) if sm else True

        st_dl = st.get("dl", {}).get("pass_fail", "NO_DATA")
        st_ul = st.get("ul", {}).get("pass_fail", "NO_DATA")
        st_pass = st_dl in ("PASS", "NO_DATA") and st_ul in ("PASS", "NO_DATA")

        overall = "PASS" if (sm_pass and st_pass) else "FAIL"

        failed_params = []
        for param, result in sm.items():
            if result["pass_fail"] == "FAIL":
                failed_params.append(param)
        if st_dl == "FAIL":
            failed_params.append("dl_throughput")
        if st_ul == "FAIL":
            failed_params.append("ul_throughput")

        comment = self.get_comment(sm, st)

        return {
            "overall_pass_fail": overall,
            "sm_pass_fail": "PASS" if sm_pass else "FAIL",
            "st_pass_fail": "PASS" if st_pass else "FAIL",
            "failed_params": failed_params,
            "comment": comment,
        }

    def check_physical_layer(
        self,
        parameter: str,
        value: float,
        band: str = "",
        equipment: str = "",
    ) -> dict:
        """Check physical layer parameter against thresholds.

        Composite key: (parameter, band, equipment) — case-insensitive matching.

        Args:
            parameter: Parameter name (e.g. "RSSI Hot", "VSWR", "Fiber Loss")
            value: Measured value
            band: Band/frequency (e.g. "PCS", "N2500") — partial match
            equipment: Equipment type (e.g. "RRU 4402", "RRU 8863") — partial match

        Returns:
            Dict with parameter, value, min_value, max_value, pass_fail, delta.
        """
        rules = self.physical or []
        matching = [
            r for r in rules
            if r["parameter"].lower() == parameter.lower()
            and (not band or band.lower() in r.get("band", "").lower())
            and (not equipment or equipment.lower() in r.get("equipment", "").lower())
        ]

        if not matching:
            return {
                "parameter": parameter,
                "value": value,
                "min_value": None,
                "max_value": None,
                "pass_fail": "NO_RULE",
                "delta": 0,
            }

        # Check against each matching rule
        for rule in matching:
            min_val = rule.get("min_value")
            max_val = rule.get("max_value")
            if min_val is not None and value < min_val:
                return {
                    **rule,
                    "value": value,
                    "pass_fail": "FAIL",
                    "delta": round(value - min_val, 2),
                }
            if max_val is not None and value > max_val:
                return {
                    **rule,
                    "value": value,
                    "pass_fail": "FAIL",
                    "delta": round(value - max_val, 2),
                }

        return {**matching[0], "value": value, "pass_fail": "PASS", "delta": 0}

    # --- Private helpers ---

    @staticmethod
    def _check_throughput(
        measured: float,
        threshold_min: float | None,
        threshold_max: float | None,
    ) -> dict:
        """Check a single throughput value against min/max thresholds."""
        if threshold_min is None:
            return {
                "value": measured,
                "threshold_min": None,
                "threshold_max": threshold_max,
                "pass_fail": "NO_THRESHOLD",
                "delta": None,
            }

        delta = round(measured - threshold_min, 2)
        return {
            "value": measured,
            "threshold_min": threshold_min,
            "threshold_max": threshold_max,
            "pass_fail": "PASS" if measured >= threshold_min else "FAIL",
            "delta": delta,
        }

    @staticmethod
    def _get_progressive_ul(progressive: dict, sinr_db: float) -> float | None:
        """Get EN-DC progressive UL threshold for a given SINR level.

        Uses the nearest lower SINR level from the progressive UL table.
        """
        if not progressive:
            return None

        levels = sorted(progressive.keys())
        if sinr_db < levels[0]:
            return None

        selected = levels[0]
        for level in levels:
            if level <= sinr_db:
                selected = level
            else:
                break

        return progressive[selected]
