"""Screenshot discovery and VLM extraction.

Discovers screenshot pairs (Service Mode + Speedtest) in site folders,
calls qwen3-vl:8b for extraction, validates JSON schema, builds manifest.

Implementation: Claude Code Prompt 3 (Screenshot Parser)
"""
import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .ollama_client import OllamaClient
from .utils.file_utils import discover_screenshots, pair_screenshots

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas for VLM JSON validation
# ---------------------------------------------------------------------------

def _strip_units(value: Any) -> Any:
    """Strip common RF unit suffixes so Pydantic can parse as number.

    Handles: "20 MHz", "-23 dBm", "15kHz", "-52.3dBm", "100 Mbps",
             "-3.5 dB", "30 dB", "2.1 ratio", etc.
    """
    if not isinstance(value, str):
        return value
    cleaned = _UNIT_PATTERN.sub('', value.strip())
    if not cleaned:
        return value
    return cleaned


# Common RF unit suffixes to strip (case-insensitive)
_UNIT_PATTERN = re.compile(
    r'\s*(MHz|dBm|dB|kHz|Mbps|bps|ms|pct|%|ratio)\s*$',
    re.IGNORECASE,
)


def _sanitize_numeric_fields(data: dict) -> dict:
    """Convert VLM placeholder strings and unit-suffixed values for numeric fields."""
    if not isinstance(data, dict):
        return data
    placeholders = {
        "--", "---", "N/A", "n/a", "NA", "null", "None", "",
        "Not Configured", "not configured", "Not Available", "not available",
        "Not Supported", "not supported", "Disabled", "disabled",
        "OFF", "off", "No Data", "no data",
    }
    sanitized = {}
    for k, v in data.items():
        if isinstance(v, str):
            stripped = v.strip()
            if stripped in placeholders:
                sanitized[k] = None
            else:
                cleaned = _UNIT_PATTERN.sub('', stripped)
                sanitized[k] = cleaned if cleaned != stripped else v
        else:
            sanitized[k] = v
    return sanitized


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

    @model_validator(mode="before")
    @classmethod
    def sanitize_placeholders(cls, data: Any) -> Any:
        return _sanitize_numeric_fields(data) if isinstance(data, dict) else data

    @field_validator("band", mode="before")
    @classmethod
    def coerce_band(cls, v: Any) -> int | None:
        """Handle VLM returning PLMN ID (e.g. '310-260') instead of band number."""
        if v is None:
            return None
        s = str(v).strip()
        if "-" in s and not s.startswith("-"):
            # PLMN ID like "310-260" — not a band number
            return None
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None

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

    @model_validator(mode="before")
    @classmethod
    def sanitize_placeholders(cls, data: Any) -> Any:
        return _sanitize_numeric_fields(data) if isinstance(data, dict) else data


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
    def _encode_image(image_path: str | Path, max_dimension: int = 1024) -> str:
        """Read image, resize to max_dimension, return base64-encoded JPEG string."""
        from PIL import Image
        import io

        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")

        img = Image.open(path)

        # Resize if larger than max_dimension on either side
        if max(img.size) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        # Convert to RGB if needed (handles RGBA, palette images)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Encode to JPEG bytes in memory
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        return base64.b64encode(buffer.read()).decode("utf-8")

    # ------------------------------------------------------------------
    # VLM extraction
    # ------------------------------------------------------------------

    def extract_service_mode(self, image_path: str | Path, max_dimension: int = 1024) -> dict[str, Any]:
        """Extract Service Mode parameters from a screenshot via VLM.

        Encodes image as base64, sends to qwen3-vl:8b with the service mode
        prompt, validates JSON against ServiceModeData schema. Retries up to 3 times.

        Returns:
            Validated service mode data dict.

        Raises:
            ValueError: If all extraction attempts fail validation.
        """
        img_b64 = self._encode_image(image_path, max_dimension=max_dimension)
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

    def extract_speedtest(self, image_path: str | Path, max_dimension: int = 1024) -> dict[str, Any]:
        """Extract Speedtest results from a screenshot via VLM.

        Encodes image as base64, sends to qwen3-vl:8b with the speedtest
        prompt, validates JSON against SpeedtestData schema. Retries up to 3 times.

        Returns:
            Validated speedtest data dict.

        Raises:
            ValueError: If all extraction attempts fail validation.
        """
        img_b64 = self._encode_image(image_path, max_dimension=max_dimension)
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

    def process_all_pairs(
        self,
        screenshot_pairs: list[dict],
        checkpoint_dir: str | Path | None = None,
    ) -> list[dict]:
        """Extract data from all screenshot pairs and detect connection modes.

        Args:
            screenshot_pairs: Output of pair_screenshots() — list of pair dicts.
            checkpoint_dir: Directory for .checkpoint.json (enables resume). If None, no checkpoint.

        Returns:
            List of cell_data dicts with extracted SM/ST data and connection mode.
        """
        results = []
        total = len(screenshot_pairs)
        start_idx = 0

        # Load checkpoint if available
        checkpoint_path = None
        if checkpoint_dir:
            checkpoint_path = Path(checkpoint_dir) / ".checkpoint.json"
            if checkpoint_path.exists():
                try:
                    checkpoint = json.loads(checkpoint_path.read_text())
                    results = checkpoint.get("results", [])
                    start_idx = checkpoint.get("next_index", 0)
                    # Convert path strings back to Path objects in results
                    logger.info("Resuming from checkpoint: %d/%d already processed", start_idx, total)
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Corrupt checkpoint file, starting from scratch")
                    results = []
                    start_idx = 0

        batch_start = time.monotonic()

        for i, pair in enumerate(screenshot_pairs):
            if i < start_idx:
                continue

            pair_num = i + 1
            sm_path = pair["service_mode"]["path"]
            st_path = pair["speedtest"]["path"]

            # Progress with ETA
            elapsed = time.monotonic() - batch_start
            processed_in_batch = pair_num - start_idx
            if processed_in_batch > 1 and elapsed > 0:
                avg_per_pair = elapsed / (processed_in_batch - 1)
                remaining = (total - pair_num) * avg_per_pair
                eta_min = int(remaining // 60)
                eta_sec = int(remaining % 60)
                pct = int(pair_num / total * 100)
                logger.info("Processing %d/%d [%d%%] — ETA: %dm %ds — %s + %s",
                            pair_num, total, pct, eta_min, eta_sec,
                            sm_path.name, st_path.name)
            else:
                pct = int(pair_num / total * 100)
                logger.info("Processing %d/%d [%d%%] — %s + %s",
                            pair_num, total, pct, sm_path.name, st_path.name)

            pair_start = time.monotonic()

            result = {
                "cell_id": pair["cell_id"],
                "sector": pair["sector"],
                "tech_subfolder": pair["tech_subfolder"],
                "tech_info": pair["tech_info"],
                "duration_sec": pair["duration_sec"],
            }

            # Extract service mode with retry at lower resolution
            try:
                sm_data = self.extract_service_mode(sm_path)
            except (ValueError, KeyError) as exc:
                logger.warning("Extraction failed for %s: %s", sm_path, exc)
                try:
                    sm_data = self.extract_service_mode(sm_path, max_dimension=768)
                except Exception:
                    logger.error("Retry also failed for %s", sm_path)
                    result["status"] = "EXTRACTION_FAILED"
                    result["error"] = str(exc)
                    result["service_mode"] = None
                    result["speedtest"] = None
                    result["connection_mode"] = None
                    results.append(result)
                    self._save_checkpoint(checkpoint_path, results, i + 1)
                    continue

            # Extract speedtest with retry at lower resolution
            try:
                st_data = self.extract_speedtest(st_path)
            except (ValueError, KeyError) as exc:
                logger.warning("Extraction failed for %s: %s", st_path, exc)
                try:
                    st_data = self.extract_speedtest(st_path, max_dimension=768)
                except Exception:
                    logger.error("Retry also failed for %s", st_path)
                    result["status"] = "EXTRACTION_FAILED"
                    result["error"] = str(exc)
                    result["service_mode"] = sm_data
                    result["speedtest"] = None
                    result["connection_mode"] = None
                    results.append(result)
                    self._save_checkpoint(checkpoint_path, results, i + 1)
                    continue

            connection_mode = None
            if sm_data:
                connection_mode = self.detect_connection_mode(sm_data)
                sm_data["connection_mode"] = connection_mode

            result["connection_mode"] = connection_mode
            result["service_mode"] = sm_data
            result["speedtest"] = st_data

            pair_elapsed = time.monotonic() - pair_start
            logger.debug("Pair %d/%d completed in %.1fs", pair_num, total, pair_elapsed)

            results.append(result)
            self._save_checkpoint(checkpoint_path, results, i + 1)

        total_elapsed = time.monotonic() - batch_start
        success_count = sum(1 for r in results if r.get("service_mode") and r.get("speedtest"))
        logger.info("Processed %d/%d pairs successfully in %.0fs (%.1fs/pair avg)",
                     success_count, total, total_elapsed,
                     total_elapsed / max(total - start_idx, 1))

        # Remove checkpoint on successful completion
        if checkpoint_path and checkpoint_path.exists():
            checkpoint_path.unlink()
            logger.debug("Checkpoint file removed after successful completion")

        return results

    @staticmethod
    def _save_checkpoint(checkpoint_path: Path | None, results: list[dict], next_index: int) -> None:
        """Save extraction progress to checkpoint file for resume."""
        if checkpoint_path is None:
            return
        try:
            # Serialize results — convert Path objects to strings
            serializable = []
            for r in results:
                entry = {}
                for k, v in r.items():
                    if isinstance(v, Path):
                        entry[k] = str(v)
                    elif isinstance(v, dict):
                        entry[k] = {
                            dk: str(dv) if isinstance(dv, Path) else dv
                            for dk, dv in v.items()
                        }
                    else:
                        entry[k] = v
                serializable.append(entry)
            checkpoint_path.write_text(json.dumps({
                "next_index": next_index,
                "results": serializable,
            }, default=str, indent=2))
        except Exception as exc:
            logger.warning("Failed to save checkpoint: %s", exc)
