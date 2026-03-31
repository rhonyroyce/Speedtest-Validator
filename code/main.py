"""DAS Speed Test Validator — CLI entry point and pipeline orchestrator.

Processes a DAS site folder of Samsung Service Mode and Speedtest screenshots,
extracts RF parameters via VLM (see config.yaml), correlates with CIQ, checks thresholds,
generates analysis via LLM (see config.yaml), and produces Output.xlsx + RF_Throughput_Analysis.docx.

Usage:
    # Full site processing
        cd /home/k8s/Projects/Speedtest-Validator
python -m code.main --site-folder ./input/SFY0803A --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251127_173752.xlsx --output-dir ./outputs

python -m code.main --site-folder ./input/SFY0803A --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251127_173752.xlsx --output-dir ./outputs

python -m code.main --site-folder ./input/SFY0803A --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251127_173752.xlsx --output-dir ./outputs

    # Dry run (2 screenshots only)
    python -m code.main --site-folder ./SFY0803A \\
        --ciq ./SFY0803A_MMBB_CIQ_EXPORT_*.xlsx \\
        --dry-run


"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import yaml

from .analysis_engine import AnalysisEngine
from .ciq_reader import CIQReader
from .extraction_validator import validate_extraction
from .knowledge_engine import KnowledgeEngine
from .ollama_client import OllamaClient
from .output_xlsx import OutputXlsxGenerator
from .screenshot_parser import ScreenshotParser
from .threshold_engine import ThresholdEngine
from .utils.file_utils import discover_screenshots, pair_screenshots

logger = logging.getLogger(__name__)

# Map VLM/parser connection modes to threshold engine format
_CONN_MODE_MAP = {
    "LTE_ONLY": "LTE Only",
    "NR_SA": "NR SA",
    "ENDC": "EN-DC",
    "NRDC": "NR-DC",
    # Pass-through for already-normalized values
    "LTE Only": "LTE Only",
    "NR SA": "NR SA",
    "EN-DC": "EN-DC",
    "NR-DC": "NR-DC",
}


class DASValidator:
    """Pipeline orchestrator for DAS site RF validation."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(self.config_path) as f:
            self.config = yaml.safe_load(f)

        # Initialize all modules
        self.ollama = OllamaClient(self.config)
        self.screenshot_parser = ScreenshotParser(self.config, self.ollama)
        self.ciq_reader = CIQReader(self.config)
        self.knowledge_engine = KnowledgeEngine(self.config)
        self.threshold_engine = ThresholdEngine(self.config, self.knowledge_engine)
        self.analysis_engine = AnalysisEngine(self.config, self.ollama, self.knowledge_engine)
        self.output_xlsx = OutputXlsxGenerator(self.config)

        logger.info("DASValidator initialized with config: %s", config_path)

    @staticmethod
    def _extract_carrier(tech_subfolder: str | None) -> int | None:
        """Extract carrier number (1 or 2) from tech subfolder or filename tech.

        Examples: 'N2500_C1_NSA' → 1, 'N2500_C2 SA' → 2, 'L1900' → None
        """
        if not tech_subfolder:
            return None
        m = re.search(r'_C(\d)', tech_subfolder)
        return int(m.group(1)) if m else None

    @staticmethod
    def _pick_rf_value(conn_mode: str, lte_val, nr_val):
        """Pick the right RF value based on connection mode.

        - NR SA: use NR value (no LTE anchor)
        - EN-DC: prefer LTE for anchor params, but use whichever is available
        - LTE Only: use LTE value
        """
        if conn_mode == "NR SA":
            return nr_val if nr_val is not None else lte_val or ""
        # LTE Only or EN-DC: prefer LTE, fall back to NR
        return lte_val if lte_val is not None else nr_val or ""

    def run(
        self,
        site_folder: str,
        ciq_path: str,
        output_dir: str,
        dry_run: bool = False,
        mode: str = "fast",
        site_name: str | None = None,
    ) -> None:
        """Execute the DAS validation pipeline (Phase 0–6).

        Args:
            mode: "fast" skips Phase 5 (13-col output), "full" runs analysis (16-col output).
            site_name: Override for output filenames (default: site folder name).
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        site_id = site_name or Path(site_folder).name

        # Set up file logging to {output_dir}/{site_id}_run.log
        log_path = output_path / f"{site_id}_run.log"
        file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logging.getLogger().addHandler(file_handler)
        logger.info("Run log: %s", log_path)

        # ── Phase 0: Pre-flight Check ─────────────────────────────
        logger.info("Phase 0: Pre-flight Check")
        if not self.ollama.health_check():
            raise ConnectionError(f"Ollama not reachable at {self.ollama.base_url}")
        missing = self.ollama.validate_models_available()
        if missing:
            raise RuntimeError(
                f"Missing Ollama models: {missing}. "
                f"Pull with: ollama pull {'&&ollama pull '.join(missing)}"
            )
        if not Path(ciq_path).is_file():
            raise FileNotFoundError(f"CIQ file not found: {ciq_path}")
        logger.info("Pre-flight check passed")

        # ── Phase 1: Screenshot Discovery ──────────────────────────
        logger.info("Phase 1: Screenshot Discovery")
        extensions = self.config.get("screenshot", {}).get("supported_extensions", [".jpg", ".jpeg", ".png"])
        all_screenshots = discover_screenshots(site_folder, extensions=extensions)
        pairs = pair_screenshots(all_screenshots)

        if not pairs:
            logger.error("No screenshot pairs found in %s", site_folder)
            print(f"ERROR: No screenshot pairs found in {site_folder}")
            return

        sectors = {p.get("sector") for p in pairs}
        print(f"Found {len(pairs)} screenshot pairs across {len(sectors)} sectors")

        if dry_run:
            pairs = pairs[:2]
            print(f"Dry run: processing only {len(pairs)} pairs")

        # ── Phase 2: VLM Extraction (qwen3-vl:8b) ──────────────────
        logger.info("Phase 2: VLM Extraction")
        vision_model = self.config["ollama"]["vision_model"]
        self.ollama.ensure_model_loaded(vision_model)

        extraction_results = self.screenshot_parser.process_all_pairs(
            pairs, checkpoint_dir=output_path,
        )
        logger.info("Extracted data from %d pairs", len(extraction_results))

        self.ollama.unload_model(vision_model)
        loaded = self.ollama.get_loaded_models()
        if loaded:
            logger.warning("Models still loaded after unload: %s", loaded)
        else:
            logger.info("VLM model unloaded successfully")

        # Split successful vs failed extractions
        successful = [r for r in extraction_results if r.get("status") != "EXTRACTION_FAILED"]
        failed = [r for r in extraction_results if r.get("status") == "EXTRACTION_FAILED"]
        if failed:
            logger.warning("%d pairs failed extraction and will be skipped in analysis", len(failed))

        # ── Phase 2.5: Extraction Validation ─────────────────────────
        logger.info("Phase 2.5: Extraction Validation")
        for result in successful:
            sm = result.get("service_mode")
            st = result.get("speedtest")
            if sm:
                sm_validation = validate_extraction(sm)
                if sm_validation["flags"]:
                    logger.warning("SM validation flags for %s: %s",
                                   result.get("cell_id", "?"), sm_validation["flags"])
                result["sm_validation"] = sm_validation
            if st:
                st_validation = validate_extraction(st)
                if st_validation["flags"]:
                    logger.warning("ST validation flags for %s: %s",
                                   result.get("cell_id", "?"), st_validation["flags"])
                result["st_validation"] = st_validation

        # ── Phase 3: CIQ Correlation ────────────────────────────────
        logger.info("Phase 3: CIQ Correlation")
        self.ciq_reader.load(ciq_path)

        for result in successful:
            sm = result.get("service_mode") or {}
            lte = sm.get("lte_params") or {}
            nr = sm.get("nr_params") or {}

            earfcn = lte.get("earfcn")
            arfcn = nr.get("nr_arfcn")
            pci = lte.get("pci") or nr.get("nr_pci")

            # Convert to int safely
            earfcn = int(earfcn) if earfcn is not None else None
            arfcn = int(arfcn) if arfcn is not None else None
            pci = int(pci) if pci is not None else None

            # Pass NR band/BW/carrier hints for PCI collision disambiguation
            nr_band_hint = nr.get("nr_band")  # e.g. "n41"
            nr_bw_hint = int(nr.get("nr_bandwidth_mhz") or 0) or None
            carrier_hint = self._extract_carrier(result.get("tech_subfolder"))
            matched = self.ciq_reader.match_cell(
                earfcn=earfcn, arfcn=arfcn, pci=pci,
                nr_band=str(nr_band_hint) if nr_band_hint else None,
                nr_bw_mhz=nr_bw_hint,
                carrier=carrier_hint,
            )
            if matched:
                result["ciq"] = matched
                result["bandwidth_mhz"] = self.ciq_reader.get_bandwidth_mhz(matched)
                result["mimo_config"] = self.ciq_reader.get_mimo_config(matched)
                logger.debug("Matched cell PCI=%s to CIQ: %s", pci, matched.get("cellId") or matched.get("gUtranCell"))
            else:
                result["ciq"] = {}
                result["bandwidth_mhz"] = 0.0
                result["mimo_config"] = "SISO"
                logger.warning("No CIQ match for EARFCN=%s ARFCN=%s PCI=%s", earfcn, arfcn, pci)

        # ── Phase 4: Threshold Check ────────────────────────────────
        logger.info("Phase 4: Threshold Check")
        self.knowledge_engine.load_all()
        self.threshold_engine.load_thresholds()

        for result in successful:
            sm = result.get("service_mode") or {}
            st = result.get("speedtest") or {}
            lte = sm.get("lte_params") or {}
            nr = sm.get("nr_params") or {}

            # Service mode check
            rsrp = lte.get("rsrp_dbm") or nr.get("nr5g_rsrp_dbm")
            sinr = lte.get("sinr_db") or nr.get("nr5g_sinr_db")
            rsrq = lte.get("rsrq_db") or nr.get("nr5g_rsrq_db")
            tx_power = lte.get("tx_power_dbm") or nr.get("nr_tx_power_dbm")

            sm_result = self.threshold_engine.check_service_mode(
                rsrp=float(rsrp) if rsrp is not None else None,
                sinr=float(sinr) if sinr is not None else None,
                rsrq=float(rsrq) if rsrq is not None else None,
                tx_power=float(tx_power) if tx_power is not None else None,
                end_type="antenna_end",
            )

            # Speed test check — 5-dimensional lookup
            conn_mode = _CONN_MODE_MAP.get(sm.get("connection_mode", "LTE_ONLY"), "LTE Only")

            # Determine BW components — CIQ is source of truth, VLM is fallback
            ciq = result.get("ciq", {})
            is_nr_cell = "gUtranCell" in ciq or str(ciq.get("radioType", "")).upper().startswith("NR")
            ciq_bw = int(result.get("bandwidth_mhz", 0))

            if is_nr_cell:
                # CIQ matched as NR cell — use CIQ BW for NR
                bw_nr_c1 = ciq_bw or int(nr.get("nr_bandwidth_mhz") or 0)
                bw_nr_c2 = int(nr.get("bandwidth_c2_mhz") or 0)
                # Look up LTE BW separately from CIQ if EN-DC
                bw_lte = 0
                if conn_mode == "EN-DC":
                    lte_earfcn = lte.get("earfcn")
                    if lte_earfcn:
                        lte_match = self.ciq_reader.match_cell(earfcn=int(lte_earfcn))
                        if lte_match:
                            bw_lte = int(self.ciq_reader.get_bandwidth_mhz(lte_match))
            else:
                # CIQ matched as LTE cell (or no match)
                bw_lte = ciq_bw or int(lte.get("bandwidth_mhz") or 0)
                # NR BW: try CIQ lookup by ARFCN, fall back to VLM
                bw_nr_c1 = int(nr.get("nr_bandwidth_mhz") or 0)
                nr_arfcn = nr.get("nr_arfcn")
                nr_pci = nr.get("nr_pci")
                if nr_arfcn or nr_pci:
                    nr_match = self.ciq_reader.match_cell(
                        arfcn=int(nr_arfcn) if nr_arfcn else None,
                        pci=int(nr_pci) if nr_pci else None,
                        nr_band=str(nr.get("nr_band")) if nr.get("nr_band") else None,
                        nr_bw_mhz=int(nr.get("nr_bandwidth_mhz") or 0) or None,
                        carrier=self._extract_carrier(result.get("tech_subfolder")),
                    )
                    if nr_match:
                        bw_nr_c1 = int(self.ciq_reader.get_bandwidth_mhz(nr_match)) or bw_nr_c1
                bw_nr_c2 = int(nr.get("bandwidth_c2_mhz") or 0)

            # Infer connection mode from BW data when VLM defaults to LTE Only
            original_mode = conn_mode
            if conn_mode == "LTE Only":
                if bw_lte > 0 and bw_nr_c1 > 0:
                    conn_mode = "EN-DC"
                elif bw_lte == 0 and bw_nr_c1 > 0:
                    conn_mode = "NR SA"
            if conn_mode != original_mode:
                logger.info("Connection mode override: %s → %s (cell=%s, BW LTE=%d NR_C1=%d)",
                            original_mode, conn_mode,
                            result.get("cell_id", "?"), bw_lte, bw_nr_c1)

            st_result = self.threshold_engine.check_speed_test(
                dl_mbps=float(st.get("dl_throughput_mbps") or 0),
                ul_mbps=float(st.get("ul_throughput_mbps") or 0),
                mimo_config=result.get("mimo_config", "SISO"),
                bw_lte_mhz=bw_lte,
                bw_nr_c1_mhz=bw_nr_c1,
                bw_nr_c2_mhz=bw_nr_c2,
                connection_mode=conn_mode,
                sinr_db=float(sinr) if sinr is not None else None,
            )

            comment = self.threshold_engine.get_comment(sm_result, st_result)
            result["threshold_sm"] = sm_result
            result["threshold_st"] = st_result
            result["comment"] = comment

            # Physical layer checks (if measurements present)
            if result.get("physical_measurements"):
                physical_results = []
                for param, value in result["physical_measurements"].items():
                    physical_results.append(
                        self.threshold_engine.check_physical_layer(
                            param, value, band=result.get("band", ""),
                        )
                    )
                result["physical_results"] = physical_results

            # Preserve decomposed BW and inferred conn_mode for Phase 5/6
            result["bw_lte_mhz"] = bw_lte
            result["bw_nr_c1_mhz"] = bw_nr_c1
            result["bw_nr_c2_mhz"] = bw_nr_c2
            result["inferred_conn_mode"] = conn_mode

        # ── Phase 5: Knowledge Analysis (gpt-oss:20b) ──────────────
        analysis_data = {}
        if mode == "full":
            logger.info("Phase 5: Knowledge Analysis")
            analysis_model = self.config["ollama"]["analysis_model"]
            self.ollama.ensure_model_loaded(analysis_model)

            for i, result in enumerate(successful):
                cell_id = result.get("cell_id", f"cell_{i}")
                logger.info("Analyzing cell %d/%d: %s", i + 1, len(successful), cell_id)

                sm = result.get("service_mode") or {}
                st = result.get("speedtest") or {}
                lte = sm.get("lte_params") or {}
                nr = sm.get("nr_params") or {}
                inferred_mode = result.get("inferred_conn_mode", "LTE Only")
                cell_data = {
                    "rsrp": lte.get("rsrp_dbm") or nr.get("nr5g_rsrp_dbm"),
                    "sinr": lte.get("sinr_db") or nr.get("nr5g_sinr_db"),
                    "rsrq": lte.get("rsrq_db") or nr.get("nr5g_rsrq_db"),
                    "tx_power": lte.get("tx_power_dbm") or nr.get("nr_tx_power_dbm"),
                    "dl_throughput": st.get("dl_throughput_mbps"),
                    "ul_throughput": st.get("ul_throughput_mbps"),
                    "tech": "NR" if nr.get("nr_band") else "LTE",
                    "conn_mode": inferred_mode,
                    "bw_lte_mhz": result.get("bw_lte_mhz", 0),
                    "bw_nr_c1_mhz": result.get("bw_nr_c1_mhz", 0),
                    "bw_nr_c2_mhz": result.get("bw_nr_c2_mhz", 0),
                    "mimo_config": result.get("mimo_config", "SISO"),
                    "sector": result.get("sector"),
                    "tech_subfolder": result.get("tech_subfolder"),
                }

                analysis = self.analysis_engine.analyze_cell(
                    cell_data=cell_data,
                    ciq_config=result.get("ciq", {}),
                    threshold_result={
                        "service_mode": result.get("threshold_sm", {}),
                        "speed_test": result.get("threshold_st", {}),
                        "comment": result.get("comment", ""),
                    },
                )

                result["observations"] = analysis.get("observations", "")
                result["recommendations"] = analysis.get("recommendations", "")
                result["kpi_impact"] = analysis.get("kpi_impact", "")
                analysis_data[cell_id] = analysis

            self.ollama.unload_model(analysis_model)
            logger.info("Analysis model unloaded")
        else:
            logger.info("Phase 5: Skipped (fast mode)")

        # ── Phase 6: Output Generation ──────────────────────────────
        logger.info("Phase 6: Output Generation")

        # Build output rows from successful extractions
        output_results = []
        for result in successful:
            sm = result.get("service_mode") or {}
            st = result.get("speedtest") or {}
            lte = sm.get("lte_params") or {}
            nr = sm.get("nr_params") or {}

            bw_lte = result.get("bw_lte_mhz", 0)
            bw_nr_c1 = result.get("bw_nr_c1_mhz", 0)
            bw_nr_c2 = result.get("bw_nr_c2_mhz", 0)
            if bw_nr_c1 or bw_nr_c2:
                bandwidth = f"LTE {bw_lte} / NR C1 {bw_nr_c1} / NR C2 {bw_nr_c2}"
            else:
                bandwidth = f"LTE {bw_lte}"

            conn_mode_str = result.get("inferred_conn_mode", _CONN_MODE_MAP.get(sm.get("connection_mode", "LTE_ONLY"), "LTE Only"))
            row = {
                "bts": site_id,
                "tech_sector": f"SECTOR {result.get('sector', '?')} / {result.get('tech_subfolder') or (result.get('tech_info') or {}).get('band', 'Unknown')}",
                "connection_mode": conn_mode_str,
                "bandwidth": bandwidth,
                "pci": self._pick_rf_value(conn_mode_str, lte.get("pci"), nr.get("nr_pci")),
                "rsrp": self._pick_rf_value(conn_mode_str, lte.get("rsrp_dbm"), nr.get("nr5g_rsrp_dbm")),
                "rsrq": self._pick_rf_value(conn_mode_str, lte.get("rsrq_db"), nr.get("nr5g_rsrq_db")),
                "sinr": self._pick_rf_value(conn_mode_str, lte.get("sinr_db"), nr.get("nr5g_sinr_db")),
                "tx_power": self._pick_rf_value(conn_mode_str, lte.get("tx_power_dbm"), nr.get("nr_tx_power_dbm")),
                "sm_st_duration": result.get("duration_sec", ""),
                "dl_throughput": st.get("dl_throughput_mbps") or "",
                "ul_throughput": st.get("ul_throughput_mbps") or "",
                "comment": result.get("comment", ""),
                "observations": result.get("observations", ""),
                "recommendations": result.get("recommendations", ""),
                "kpi_impact": result.get("kpi_impact", ""),
            }
            output_results.append(row)

        # Threshold data for Tab 2
        threshold_data = {
            "siso": self.threshold_engine.siso,
            "mimo": self.threshold_engine.mimo,
            "service_mode": self.threshold_engine.service_mode,
        }

        xlsx_path = output_path / f"{site_id}_Output.xlsx"
        self.output_xlsx.generate(
            output_results, threshold_data, xlsx_path, failed=failed, mode=mode,
        )

        print(f"\u2705 Output saved to {output_dir}")
        print(f"   {site_id}_Output.xlsx ({len(output_results)} rows, mode={mode})")

        # Clean up file handler
        logging.getLogger().removeHandler(file_handler)
        file_handler.close()


def _run_investigation(validator: DASValidator, question: str) -> None:
    """Run optional agentic investigation on the first cell's data."""
    from .investigate_engine import InvestigateEngine
    from .knowledge.causal_dag import CausalDAG

    logger.info("Running agentic investigation: %s", question)
    try:
        dag = CausalDAG(validator.config)
        engine = InvestigateEngine(
            validator.config, validator.ollama, dag, validator.threshold_engine,
        )

        # Use a sample cell_data dict (first successful extraction)
        # The pipeline stores results internally; for investigation we build a minimal cell_data
        cell_data = {"question_context": "Post-pipeline investigation"}
        answer = engine.investigate(cell_data, question)
        print(f"\n--- Investigation Result ---\n{answer}\n")
    except Exception as exc:
        logger.error("Investigation failed: %s", exc)
        print(f"Investigation failed: {exc}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="das-validator",
        description="DAS Speed Test Validator — automate T-Mobile DAS site RF validation",
    )
    parser.add_argument(
        "--site-folder",
        required=True,
        help="Path to site screenshot folder",
    )
    parser.add_argument(
        "--ciq",
        required=True,
        help="Path to CIQ Excel file",
    )
    parser.add_argument(
        "--output-dir",
        default="./outputs",
        help="Output directory (default: ./outputs)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Config file path (default: config.yaml)",
    )
    parser.add_argument(
        "--mode",
        choices=["fast", "full"],
        default="fast",
        help="fast: skip LLM analysis (13 cols); full: run analysis model (16 cols) (default: fast)",
    )
    parser.add_argument(
        "--site-name",
        default=None,
        help="Override site name for output filenames (default: site folder name)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process only first 2 screenshot pairs",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--investigate",
        type=str,
        default=None,
        metavar="QUESTION",
        help="Run agentic investigation on first cell (optional, not in core pipeline)",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Validate inputs
    if not Path(args.site_folder).is_dir():
        print(f"ERROR: Site folder not found: {args.site_folder}", file=sys.stderr)
        sys.exit(1)
    if not Path(args.ciq).is_file():
        print(f"ERROR: CIQ file not found: {args.ciq}", file=sys.stderr)
        sys.exit(1)

    start_time = time.time()

    try:
        validator = DASValidator(config_path=args.config)
        validator.run(
            site_folder=args.site_folder,
            ciq_path=args.ciq,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            mode=args.mode,
            site_name=args.site_name,
        )

        # Optional: agentic investigation (not in core pipeline)
        if args.investigate:
            _run_investigation(validator, args.investigate)

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(130)
    except Exception as e:
        logger.exception("Pipeline failed")
        print(f"ERROR: Pipeline failed — {e}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - start_time
    minutes, seconds = divmod(int(elapsed), 60)
    print(f"\nCompleted in {minutes}m {seconds}s")


if __name__ == "__main__":
    main()
