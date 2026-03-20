"""DAS Speed Test Validator — CLI entry point and pipeline orchestrator.

Processes a DAS site folder of Samsung Service Mode and Speedtest screenshots,
extracts RF parameters via qwen3-vl:8b, correlates with CIQ, checks thresholds,
generates analysis via gpt-oss:20b, and produces Output.xlsx + RF_Throughput_Analysis.docx.

Usage:
    # Full site processing
        cd /home/k8s/Projects/Speedtest-Validator
python -m code.main --site-folder ./input/SFY0803A --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx --output-dir ./outputs


    # Dry run (2 screenshots only)
    python -m code.main --site-folder ./SFY0803A \\
        --ciq ./SFY0803A_MMBB_CIQ_EXPORT_*.xlsx \\
        --dry-run


"""

import argparse
import logging
import sys
import time
from pathlib import Path

import yaml

from .analysis_engine import AnalysisEngine
from .ciq_reader import CIQReader
from .knowledge_engine import KnowledgeEngine
from .ollama_client import OllamaClient
from .output_docx import OutputDocxGenerator
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
        self.output_docx = OutputDocxGenerator(self.config)

        logger.info("DASValidator initialized with config: %s", config_path)

    def run(
        self,
        site_folder: str,
        ciq_path: str,
        output_dir: str,
        dry_run: bool = False,
    ) -> None:
        """Execute the 6-phase DAS validation pipeline."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        site_id = Path(site_folder).name

        # ── Phase 1: Screenshot Discovery ──────────────────────────
        logger.info("Phase 1: Screenshot Discovery")
        all_screenshots = discover_screenshots(site_folder)
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

        extraction_results = self.screenshot_parser.process_all_pairs(pairs)
        logger.info("Extracted data from %d pairs", len(extraction_results))

        self.ollama.unload_model(vision_model)
        loaded = self.ollama.get_loaded_models()
        if loaded:
            logger.warning("Models still loaded after unload: %s", loaded)
        else:
            logger.info("VLM model unloaded successfully")

        # ── Phase 3: CIQ Correlation ────────────────────────────────
        logger.info("Phase 3: CIQ Correlation")
        self.ciq_reader.load(ciq_path)

        for result in extraction_results:
            sm = result.get("service_mode", {})
            lte = sm.get("lte_params") or {}
            nr = sm.get("nr_params") or {}

            earfcn = lte.get("earfcn")
            arfcn = nr.get("nr_arfcn")
            pci = lte.get("pci") or nr.get("nr_pci")

            # Convert to int safely
            earfcn = int(earfcn) if earfcn is not None else None
            arfcn = int(arfcn) if arfcn is not None else None
            pci = int(pci) if pci is not None else None

            matched = self.ciq_reader.match_cell(earfcn=earfcn, arfcn=arfcn, pci=pci)
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
        self.threshold_engine.load_thresholds()

        for result in extraction_results:
            sm = result.get("service_mode", {})
            st = result.get("speedtest", {})
            lte = sm.get("lte_params") or {}
            nr = sm.get("nr_params") or {}

            # Service mode check
            rsrp = lte.get("rsrp_dbm") or nr.get("nr5g_rsrp_dbm")
            sinr = lte.get("sinr_db") or nr.get("nr5g_sinr_db")
            rsrq = lte.get("rsrq_db") or nr.get("nr5g_rsrq_db")
            tx_power = lte.get("tx_power_dbm") or nr.get("nr_tx_power_dbm")

            sm_result = self.threshold_engine.check_service_mode(
                rsrp=float(rsrp) if rsrp is not None else 0.0,
                sinr=float(sinr) if sinr is not None else 0.0,
                rsrq=float(rsrq) if rsrq is not None else 0.0,
                tx_power=float(tx_power) if tx_power is not None else 0.0,
                end_type="antenna_end",
            )

            # Speed test check — 5-dimensional lookup
            conn_mode = _CONN_MODE_MAP.get(sm.get("connection_mode", "LTE_ONLY"), "LTE Only")

            # Determine BW components for lookup
            bw_lte = int(result.get("bandwidth_mhz", 0)) if lte else 0
            bw_nr_c1 = int(nr.get("nr_bandwidth_mhz") or 0)
            bw_nr_c2 = int(nr.get("bandwidth_c2_mhz") or 0)

            # If we have CIQ data for NR bandwidth, prefer that
            ciq = result.get("ciq", {})
            if ciq.get("radioType") in ("NR", "nr"):
                bw_nr_c1 = int(result.get("bandwidth_mhz", 0))
                if conn_mode in ("EN-DC",):
                    # EN-DC needs both LTE and NR BW — look up LTE from CIQ
                    lte_earfcn = lte.get("earfcn")
                    if lte_earfcn:
                        lte_match = self.ciq_reader.match_cell(earfcn=int(lte_earfcn))
                        if lte_match:
                            bw_lte = int(self.ciq_reader.get_bandwidth_mhz(lte_match))
                        else:
                            bw_lte = 0
                    else:
                        bw_lte = 0
                else:
                    bw_lte = 0

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

        # ── Phase 5: Knowledge Analysis (gpt-oss:20b) ──────────────
        logger.info("Phase 5: Knowledge Analysis")
        analysis_model = self.config["ollama"]["analysis_model"]
        self.ollama.ensure_model_loaded(analysis_model)

        analysis_data = {}
        for i, result in enumerate(extraction_results):
            cell_id = result.get("cell_id", f"cell_{i}")
            logger.info("Analyzing cell %d/%d: %s", i + 1, len(extraction_results), cell_id)

            cell_data = {
                "service_mode": result.get("service_mode", {}),
                "speedtest": result.get("speedtest", {}),
                "connection_mode": _CONN_MODE_MAP.get(result.get("service_mode", {}).get("connection_mode", "LTE_ONLY"), "LTE Only"),
                "bandwidth_mhz": result.get("bandwidth_mhz", 0),
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

        # ── Phase 6: Output Generation ──────────────────────────────
        logger.info("Phase 6: Output Generation")

        # Build output rows
        output_results = []
        for result in extraction_results:
            sm = result.get("service_mode", {})
            st = result.get("speedtest", {})
            lte = sm.get("lte_params") or {}
            nr = sm.get("nr_params") or {}

            row = {
                "bts": site_id,
                "tech_sector": result.get("tech_subfolder", ""),
                "connection_mode": _CONN_MODE_MAP.get(sm.get("connection_mode", "LTE_ONLY"), "LTE Only"),
                "bandwidth": result.get("bandwidth_mhz", ""),
                "pci": lte.get("pci") or nr.get("nr_pci") or "",
                "rsrp": lte.get("rsrp_dbm") or nr.get("nr5g_rsrp_dbm") or "",
                "rsrq": lte.get("rsrq_db") or nr.get("nr5g_rsrq_db") or "",
                "sinr": lte.get("sinr_db") or nr.get("nr5g_sinr_db") or "",
                "tx_power": lte.get("tx_power_dbm") or nr.get("nr_tx_power_dbm") or "",
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
        self.output_xlsx.generate(output_results, threshold_data, xlsx_path)

        # Site config for docx
        site_config = self.ciq_reader.get_site_config_summary()

        docx_path = output_path / f"{site_id}_RF_Throughput_Analysis.docx"
        self.output_docx.generate(output_results, site_config, analysis_data, docx_path)

        print(f"\u2705 Output saved to {output_dir}")
        print(f"   {site_id}_Output.xlsx ({len(output_results)} rows)")
        print(f"   {site_id}_RF_Throughput_Analysis.docx")


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
        "--dry-run",
        action="store_true",
        help="Process only first 2 screenshot pairs",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
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
        )
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
