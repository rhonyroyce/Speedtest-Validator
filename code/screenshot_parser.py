"""Screenshot discovery and VLM extraction.

Discovers screenshot pairs (Service Mode + Speedtest) in site folders,
calls qwen3-vl:8b for extraction, validates JSON schema, builds manifest.

Implementation: Claude Code Prompt 3 (Screenshot Parser)
"""
import base64
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .ollama_client import OllamaClient
from .utils.file_utils import discover_screenshots, pair_screenshots

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas for VLM JSON validation
# ---------------------------------------------------------------------------

class LTEParams(BaseModel):
    band: int | None = None
    bandwidth_mhz: float | None = None
    earfcn: int | None = None
    pci: int | None = None
    rsrp_dbm: float | None = None
    rsrq_db: float | None = None
    sinr_db: float | None = None
    tx_power_dbm: float | None = None
    mimo_configured: str | None = None
    upperlayer_ind_r15: str | None = None
    dcnr_restriction: str | None = None
    ca_status: str | None = None
    ul_ca_status: str | None = None

    @field_validator("mimo_configured", mode="before")
    @classmethod
    def coerce_mimo_to_str(cls, v: Any) -> str | None:
        return str(v) if v is not None else None


class NRParams(BaseModel):
    nr_band: int | str | None = None
    nr_bandwidth_mhz: float | None = None
    nr_arfcn: int | None = None
    nr_pci: int | None = None
    nr5g_rsrp_dbm: float | None = None
    nr5g_rsrq_db: float | None = None
    nr5g_sinr_db: float | None = None
    nr_tx_power_dbm: float | None = None
    nr_bler_pct: float | None = None
    nr_dl_scheduling_pct: float | None = None
    nr_scs_khz: int | None = None
    nr_sb_status: str | None = None
    nr_cdrx: str | None = None
    nr_ant_max_rsrp: float | None = None
    nr_ant_min_rsrp: float | None = None
    endc_total_tx_power_dbm: float | None = None
    nr_rx0_rsrp: float | None = None
    nr_rx1_rsrp: float | None = None
    nr_rx2_rsrp: float | None = None
    nr_rx3_rsrp: float | None = None


class ServiceModeData(BaseModel):
    screenshot_type: str = "service_mode"
    technology: str | None = None
    connection_mode: str | None = None
    lte_params: LTEParams | None = None
    nr_params: NRParams | None = None
    timestamp: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("connection_mode")
    @classmethod
    def validate_connection_mode(cls, v: str | None) -> str | None:
        if v is not None:
            allowed = {"LTE_ONLY", "NR_SA", "ENDC", "NRDC"}
            if v not in allowed:
                raise ValueError(f"connection_mode must be one of {allowed}, got '{v}'")
        return v


class SpeedtestData(BaseModel):
    screenshot_type: str = "speedtest"
    dl_throughput_mbps: float | None = None
    ul_throughput_mbps: float | None = None
    ping_idle_ms: float | None = None
    ping_dl_ms: float | None = None
    ping_ul_ms: float | None = None
    jitter_ms: float | None = None
    packet_loss_pct: float | None = None
    server_name: str | None = None
    isp: str | None = None
    timestamp: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# ScreenshotParser
# ---------------------------------------------------------------------------

class ScreenshotParser:
    """Extracts RF parameters from Samsung Service Mode and Speedtest screenshots."""

    def __init__(self, config: dict, ollama_client: OllamaClient):
        self.config = config
        self.client = ollama_client
        prompts_dir = Path(__file__).parent / "prompts"
        self._sm_prompt = (prompts_dir / "service_mode_extraction.md").read_text()
        self._st_prompt = (prompts_dir / "speedtest_extraction.md").read_text()

    # ------------------------------------------------------------------
    # Image encoding
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_image(image_path: str | Path) -> str:
        """Read an image file and return its base64-encoded string."""
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    # ------------------------------------------------------------------
    # VLM extraction
    # ------------------------------------------------------------------

    def extract_service_mode(self, image_path: str | Path) -> dict[str, Any]:
        """Extract Service Mode parameters from a screenshot via VLM.

        Encodes image as base64, sends to qwen3-vl:8b with the service mode
        prompt, validates JSON against ServiceModeData schema. Retries up to 3 times.

        Returns:
            Validated service mode data dict.

        Raises:
            ValueError: If all extraction attempts fail validation.
        """
        img_b64 = self._encode_image(image_path)
        parsed, attempt = self.client.chat_vision_json(img_b64, self._sm_prompt)

        if parsed is None:
            raise ValueError(f"Failed to extract JSON from service mode screenshot: {image_path}")

        # Validate with Pydantic
        try:
            validated = ServiceModeData(**parsed)
            data = validated.model_dump()
            if attempt > 1:
                logger.warning("Service mode extraction required %d attempts: %s",
                               attempt, image_path)
            return data
        except Exception as exc:
            raise ValueError(
                f"Service mode schema validation failed for {image_path}: {exc}"
            ) from exc

    def extract_speedtest(self, image_path: str | Path) -> dict[str, Any]:
        """Extract Speedtest results from a screenshot via VLM.

        Encodes image as base64, sends to qwen3-vl:8b with the speedtest
        prompt, validates JSON against SpeedtestData schema. Retries up to 3 times.

        Returns:
            Validated speedtest data dict.

        Raises:
            ValueError: If all extraction attempts fail validation.
        """
        img_b64 = self._encode_image(image_path)
        parsed, attempt = self.client.chat_vision_json(img_b64, self._st_prompt)

        if parsed is None:
            raise ValueError(f"Failed to extract JSON from speedtest screenshot: {image_path}")

        try:
            validated = SpeedtestData(**parsed)
            data = validated.model_dump()
            if attempt > 1:
                logger.warning("Speedtest extraction required %d attempts: %s",
                               attempt, image_path)
            return data
        except Exception as exc:
            raise ValueError(
                f"Speedtest schema validation failed for {image_path}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Connection mode detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_connection_mode(service_mode_data: dict) -> str:
        """Determine connection mode from extracted Service Mode fields.

        Detection logic (from CLAUDE.md):
          - LTE_ONLY: No NR fields, NR_SB_Status absent/empty
          - NR_SA: NR_SB_Status = "NR only" or NR_BAND without ENDC
          - ENDC: NR_SB_Status = "LTE+NR", both LTE and NR params present
          - NRDC: Two NR ARFCNs or NR C1+C2 active without LTE anchor

        Returns:
            One of: "LTE_ONLY", "NR_SA", "ENDC", "NRDC"
        """
        lte = service_mode_data.get("lte_params") or {}
        nr = service_mode_data.get("nr_params") or {}
        nr_sb_status = (nr.get("nr_sb_status") or "").strip().lower()

        has_lte = any(lte.get(k) is not None for k in ("band", "earfcn", "rsrp_dbm"))
        has_nr = any(nr.get(k) is not None for k in ("nr_band", "nr_arfcn", "nr5g_rsrp_dbm"))

        # VLM may have already detected it — trust if valid
        vlm_mode = service_mode_data.get("connection_mode")
        if vlm_mode in ("LTE_ONLY", "NR_SA", "ENDC", "NRDC"):
            # Cross-validate against extracted fields
            pass  # fall through to rule-based as override check

        # ENDC: both techs present, NR_SB_Status indicates LTE+NR
        if has_lte and has_nr and "lte+nr" in nr_sb_status:
            return "ENDC"

        # NRDC: dual NR carriers without LTE anchor
        if has_nr and not has_lte:
            # Check for dual NR carriers (C1 + C2 indicators)
            if nr_sb_status in ("nr only", "") and nr.get("nr_arfcn") is not None:
                # Could be NR_SA or NRDC — NRDC needs two carriers
                # Heuristic: if VLM explicitly tagged NRDC, trust it
                if vlm_mode == "NRDC":
                    return "NRDC"
                return "NR_SA"

        # NR SA: NR fields without LTE anchor
        if has_nr and not has_lte:
            return "NR_SA"

        # ENDC fallback: both techs present even if nr_sb_status wasn't "lte+nr"
        if has_lte and has_nr:
            return "ENDC"

        # Default: LTE only
        return "LTE_ONLY"

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def process_all_pairs(self, screenshot_pairs: list[dict]) -> list[dict]:
        """Extract data from all screenshot pairs and detect connection modes.

        Args:
            screenshot_pairs: Output of pair_screenshots() — list of pair dicts.

        Returns:
            List of cell_data dicts with extracted SM/ST data and connection mode.
        """
        results = []
        total = len(screenshot_pairs)

        for i, pair in enumerate(screenshot_pairs, 1):
            sm_path = pair["service_mode"]["path"]
            st_path = pair["speedtest"]["path"]
            logger.info("Processing pair %d/%d: %s + %s",
                        i, total, sm_path.name, st_path.name)

            try:
                sm_data = self.extract_service_mode(sm_path)
            except ValueError as exc:
                logger.error("Service mode extraction failed: %s", exc)
                sm_data = None

            try:
                st_data = self.extract_speedtest(st_path)
            except ValueError as exc:
                logger.error("Speedtest extraction failed: %s", exc)
                st_data = None

            connection_mode = None
            if sm_data:
                connection_mode = self.detect_connection_mode(sm_data)
                sm_data["connection_mode"] = connection_mode

            results.append({
                "cell_id": pair["cell_id"],
                "sector": pair["sector"],
                "tech_subfolder": pair["tech_subfolder"],
                "tech_info": pair["tech_info"],
                "duration_sec": pair["duration_sec"],
                "connection_mode": connection_mode,
                "service_mode": sm_data,
                "speedtest": st_data,
            })

        logger.info("Processed %d/%d pairs successfully",
                     sum(1 for r in results if r["service_mode"] and r["speedtest"]),
                     total)
        return results
