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

from .image_preprocessor import SM_LAYOUT, ST_LAYOUT, split_panels
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


def _safe_int(v: Any) -> int | None:
    """Coerce VLM output to int, returning None for garbage like '94-3344' or '7cd'."""
    if v is None:
        return None
    s = str(v).strip()
    # Reject strings with non-numeric chars (except leading minus and decimal point)
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _safe_float(v: Any) -> float | None:
    """Coerce VLM output to float, returning None for garbage."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


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

    @field_validator("dcnr_restriction", "mimo_configured", "upperlayer_ind_r15", mode="before")
    @classmethod
    def coerce_str_fields(cls, v: Any) -> str | None:
        """Coerce bool/int to str — VLM returns False instead of 'FALSE'."""
        return str(v) if v is not None else None
    ca_status: str | None = None
    ul_ca_status: str | None = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_placeholders(cls, data: Any) -> Any:
        return _sanitize_numeric_fields(data) if isinstance(data, dict) else data

    @field_validator("band", "earfcn", "pci", mode="before")
    @classmethod
    def coerce_int_fields(cls, v: Any) -> int | None:
        return _safe_int(v)

    @field_validator("bandwidth_mhz", "rsrp_dbm", "rsrq_db", "sinr_db", "tx_power_dbm", mode="before")
    @classmethod
    def coerce_float_fields(cls, v: Any) -> float | None:
        return _safe_float(v)



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

    @field_validator("nr_arfcn", "nr_pci", "nr_scs_khz", mode="before")
    @classmethod
    def coerce_int_fields(cls, v: Any) -> int | None:
        return _safe_int(v)

    @field_validator("nr_bandwidth_mhz", "nr5g_rsrp_dbm", "nr5g_rsrq_db", "nr5g_sinr_db",
                     "nr_tx_power_dbm", "nr_bler_pct", "nr_dl_scheduling_pct",
                     "nr_ant_max_rsrp", "nr_ant_min_rsrp", "endc_total_tx_power_dbm",
                     "nr_rx0_rsrp", "nr_rx1_rsrp", "nr_rx2_rsrp", "nr_rx3_rsrp", mode="before")
    @classmethod
    def coerce_float_fields(cls, v: Any) -> float | None:
        return _safe_float(v)


class ServiceModeData(BaseModel):
    screenshot_type: str = "service_mode"
    technology: str | None = None
    connection_mode: str | None = None
    lte_params: LTEParams | None = None
    nr_params: NRParams | None = None
    timestamp: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("connection_mode", mode="before")
    @classmethod
    def validate_connection_mode(cls, v: str | None) -> str | None:
        if v is None:
            return None
        allowed = {"LTE_ONLY", "NR_SA", "ENDC", "NRDC"}
        v = str(v).strip()
        if v in allowed:
            return v
        # VLM sometimes returns the template literal "LTE_ONLY|NR_SA|ENDC|NRDC"
        # or partial like "LTE_ONLY|NR_SA" — default to None, let detect_connection_mode fix it
        return None


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
        self._max_dim = config.get("ollama", {}).get("max_image_dimension", 768)
        prompts_dir = Path(__file__).parent / "prompts"
        self._sm_prompt = (prompts_dir / "service_mode_extraction.md").read_text()
        self._st_prompt = (prompts_dir / "speedtest_extraction.md").read_text()
        self._nr_prompt = (prompts_dir / "nr_focused_extraction.md").read_text()

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

    def extract_service_mode(self, image_path: str | Path, max_dimension: int | None = None) -> dict[str, Any]:
        """Extract Service Mode parameters from a screenshot via VLM.

        Single full-image call for speed. No panel splitting.

        Returns:
            Validated service mode data dict.

        Raises:
            ValueError: If all extraction attempts fail validation.
        """
        img_b64 = self._encode_image(image_path, max_dimension=max_dimension or self._max_dim)
        parsed, attempt = self.client.chat_vision_json(img_b64, self._sm_prompt)

        if parsed is None:
            raise ValueError(f"Failed to extract JSON from service mode screenshot: {image_path}")

        try:
            validated = ServiceModeData(**parsed)
            data = validated.model_dump()
            if attempt > 1:
                logger.warning("Service mode extraction required %d attempts: %s",
                               attempt, image_path)
        except Exception as exc:
            raise ValueError(
                f"Service mode schema validation failed for {image_path}: {exc}"
            ) from exc

        # NR backfill: if LTE params present but NR params all null, try focused NR extraction
        # This catches dense EN-DC screenshots where VLM focuses on LTE and misses NR
        if self._needs_nr_backfill(data):
            logger.debug("NR backfill triggered for %s", Path(image_path).name)
            nr_data = self._extract_nr_focused(img_b64, image_path)
            if nr_data:
                data["nr_params"] = nr_data

        return data

    def extract_speedtest(self, image_path: str | Path, max_dimension: int | None = None) -> dict[str, Any]:
        """Extract Speedtest results from a screenshot via VLM.

        Single full-image call for speed. No panel splitting.

        Returns:
            Validated speedtest data dict.

        Raises:
            ValueError: If all extraction attempts fail validation.
        """
        img_b64 = self._encode_image(image_path, max_dimension=max_dimension or self._max_dim)
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
    # NR backfill for dense EN-DC screenshots
    # ------------------------------------------------------------------

    @staticmethod
    def _needs_nr_backfill(data: dict) -> bool:
        """Check if LTE is populated but NR is empty — indicates missed NR on ENDC."""
        lte = data.get("lte_params") or {}
        nr = data.get("nr_params") or {}
        has_lte = any(lte.get(k) is not None for k in ("band", "earfcn", "rsrp_dbm"))
        has_nr = any(nr.get(k) is not None for k in ("nr_band", "nr_arfcn", "nr5g_rsrp_dbm", "nr_pci"))
        # Also check if dcnr_restriction=FALSE or NR-related hints suggest ENDC
        dcnr = str(lte.get("dcnr_restriction") or "").upper()
        expects_nr = dcnr == "FALSE" or has_lte
        return has_lte and not has_nr and expects_nr

    def _extract_nr_focused(self, img_b64: str, image_path: str | Path) -> dict | None:
        """Send full image with NR-only focused prompt. Returns NR params dict or None."""
        parsed, attempt = self.client.chat_vision_json(img_b64, self._nr_prompt)
        if parsed is None:
            logger.debug("NR focused extraction failed for %s", Path(image_path).name)
            return None
        try:
            validated = NRParams(**parsed)
            result = validated.model_dump()
            logger.info("NR backfill succeeded for %s", Path(image_path).name)
            return result
        except Exception as exc:
            logger.debug("NR backfill validation failed for %s: %s", Path(image_path).name, exc)
            return None

    # ------------------------------------------------------------------
    # Panel extraction helpers
    # ------------------------------------------------------------------

    def _extract_panel(self, panel_b64: str, panel_type: str, image_path: str | Path) -> dict | None:
        """Extract data from a single panel image.

        Args:
            panel_b64: Base64-encoded panel image.
            panel_type: "lte" or "nr" — determines prompt focus.
            image_path: Original image path (for logging).

        Returns:
            Parsed JSON dict or None on failure.
        """
        prompt = self._sm_prompt
        if panel_type == "lte":
            prompt += "\n\nFocus on LTE parameters only. Ignore NR fields if visible."
        elif panel_type == "nr":
            prompt += "\n\nFocus on NR/5G parameters only. Ignore LTE fields if visible."

        parsed, attempt = self.client.chat_vision_json(panel_b64, prompt)
        if parsed is None:
            logger.debug("Panel %s extraction failed for %s", panel_type, Path(image_path).name)
        return parsed

    @staticmethod
    def _merge_panel_extractions(lte_parsed: dict | None, nr_parsed: dict | None) -> dict | None:
        """Merge LTE and NR panel extractions into a single ServiceModeData dict.

        Returns None if both panels failed.
        """
        if lte_parsed is None and nr_parsed is None:
            return None

        merged: dict[str, Any] = {
            "screenshot_type": "service_mode",
        }

        # Take LTE params from lte_parsed
        if lte_parsed:
            merged["lte_params"] = lte_parsed.get("lte_params") or lte_parsed
            merged["technology"] = lte_parsed.get("technology")
            merged["connection_mode"] = lte_parsed.get("connection_mode")
            merged["timestamp"] = lte_parsed.get("timestamp")
            merged["confidence"] = lte_parsed.get("confidence", 0.0)

        # Take NR params from nr_parsed
        if nr_parsed:
            merged["nr_params"] = nr_parsed.get("nr_params") or nr_parsed
            # Prefer NR connection mode if it indicates ENDC/NRDC
            nr_mode = nr_parsed.get("connection_mode")
            if nr_mode in ("ENDC", "NRDC", "NR_SA"):
                merged["connection_mode"] = nr_mode
            if not merged.get("timestamp"):
                merged["timestamp"] = nr_parsed.get("timestamp")

        # Clean up: if lte_params or nr_params is the full extraction dict, extract sub-dict
        for key in ("lte_params", "nr_params"):
            val = merged.get(key)
            if isinstance(val, dict) and "screenshot_type" in val:
                # This is a full extraction, not a sub-dict — extract the nested params
                merged[key] = val.get(key)

        return merged

    @staticmethod
    def _merge_speedtest_panels(results: dict, details: dict) -> dict:
        """Merge results panel and details panel extractions for Speedtest.

        Results panel provides DL/UL throughput; details provides ping/jitter/loss.
        """
        merged = dict(results)
        # Fill in missing fields from details panel
        for key in ("ping_idle_ms", "ping_dl_ms", "ping_ul_ms", "jitter_ms",
                     "packet_loss_pct", "server_name", "isp"):
            if merged.get(key) is None and details.get(key) is not None:
                merged[key] = details[key]
        return merged

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

            # Extract service mode — single attempt, no fallback
            try:
                sm_data = self.extract_service_mode(sm_path)
            except (ValueError, KeyError) as exc:
                logger.warning("SM extraction failed for %s: %s", sm_path, exc)
                result["status"] = "EXTRACTION_FAILED"
                result["error"] = str(exc)
                result["service_mode"] = None
                result["speedtest"] = None
                result["connection_mode"] = None
                results.append(result)
                self._save_checkpoint(checkpoint_path, results, i + 1)
                continue

            # Extract speedtest — single attempt, no fallback
            try:
                st_data = self.extract_speedtest(st_path)
            except (ValueError, KeyError) as exc:
                logger.warning("ST extraction failed for %s: %s", st_path, exc)
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
