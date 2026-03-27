"""Tests for screenshot_parser.py — VLM extraction and JSON validation.

Implementation: Claude Code Prompt 10 (Testing)
"""
import base64
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.screenshot_parser import (
    LTEParams,
    NRParams,
    ScreenshotParser,
    ServiceModeData,
    SpeedtestData,
)
from code.utils.file_utils import parse_screenshot_filename
from code.utils.text_utils import extract_json, strip_markdown_fences, strip_thinking_tags


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    return {
        "ollama": {
            "base_url": "http://localhost:11434",
            "vision_model": "qwen3-vl:8b",
            "analysis_model": "gpt-oss:20b",
            "max_retries": 3,
            "extraction_temperature": 0.15,
            "analysis_temperature": 0.3,
            "timeout": 300,
        }
    }


@pytest.fixture
def mock_ollama():
    return MagicMock()


@pytest.fixture
def parser(mock_config, mock_ollama):
    with patch("code.screenshot_parser.OllamaClient"):
        p = ScreenshotParser.__new__(ScreenshotParser)
        p.config = mock_config
        p.client = mock_ollama
        prompts_dir = Path(__file__).resolve().parent.parent / "code" / "prompts"
        p._sm_prompt = (prompts_dir / "service_mode_extraction.md").read_text()
        p._st_prompt = (prompts_dir / "speedtest_extraction.md").read_text()
        return p


@pytest.fixture
def dummy_image(tmp_path):
    """Create a minimal valid JPEG file for testing."""
    from PIL import Image
    img_path = tmp_path / "test_image.jpg"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(str(img_path), format="JPEG")
    return img_path


# ---------------------------------------------------------------------------
# VLM extraction tests
# ---------------------------------------------------------------------------

class TestParseServiceMode:
    def test_parse_service_mode_valid_json(self, parser, mock_ollama, dummy_image):
        """Verify valid JSON extraction from a mock service mode response."""
        mock_response = {
            "screenshot_type": "service_mode",
            "technology": "LTE",
            "connection_mode": "LTE_ONLY",
            "lte_params": {
                "band": 2,
                "bandwidth_mhz": 20.0,
                "earfcn": 600,
                "pci": 101,
                "rsrp_dbm": -55.0,
                "rsrq_db": -5.0,
                "sinr_db": 28.0,
                "tx_power_dbm": -10.0,
            },
            "nr_params": None,
            "confidence": 0.95,
        }
        mock_ollama.chat_vision_json.return_value = (mock_response, 1)

        result = parser.extract_service_mode(dummy_image)

        assert result["screenshot_type"] == "service_mode"
        assert result["lte_params"]["rsrp_dbm"] == -55.0
        assert result["lte_params"]["sinr_db"] == 28.0
        assert result["confidence"] == 0.95

    def test_parse_speedtest_valid_json(self, parser, mock_ollama, dummy_image):
        """Verify valid JSON extraction from a mock speedtest response."""
        mock_response = {
            "screenshot_type": "speedtest",
            "dl_throughput_mbps": 250.5,
            "ul_throughput_mbps": 45.2,
            "ping_idle_ms": 12.0,
            "jitter_ms": 2.5,
            "confidence": 0.9,
        }
        mock_ollama.chat_vision_json.return_value = (mock_response, 1)

        result = parser.extract_speedtest(dummy_image)

        assert result["dl_throughput_mbps"] == 250.5
        assert result["ul_throughput_mbps"] == 45.2

    def test_extraction_fails_on_none(self, parser, mock_ollama, dummy_image):
        """ValueError raised when VLM returns None (all retries failed)."""
        mock_ollama.chat_vision_json.return_value = (None, 3)

        with pytest.raises(ValueError, match="Failed to extract JSON"):
            parser.extract_service_mode(dummy_image)


# ---------------------------------------------------------------------------
# Connection mode detection tests
# ---------------------------------------------------------------------------

class TestDetectConnectionMode:
    def test_detect_connection_mode_lte_only(self):
        """No NR fields → LTE_ONLY."""
        data = {
            "lte_params": {"band": 2, "earfcn": 600, "rsrp_dbm": -55.0},
            "nr_params": None,
        }
        assert ScreenshotParser.detect_connection_mode(data) == "LTE_ONLY"

    def test_detect_connection_mode_lte_only_empty_nr(self):
        """Empty NR params → LTE_ONLY."""
        data = {
            "lte_params": {"band": 2, "earfcn": 600, "rsrp_dbm": -55.0},
            "nr_params": {"nr_band": None, "nr_arfcn": None, "nr5g_rsrp_dbm": None},
        }
        assert ScreenshotParser.detect_connection_mode(data) == "LTE_ONLY"

    def test_detect_connection_mode_endc(self):
        """NR_SB_Status = 'LTE+NR' with both techs → ENDC."""
        data = {
            "lte_params": {"band": 2, "earfcn": 600, "rsrp_dbm": -55.0},
            "nr_params": {
                "nr_band": 41,
                "nr_arfcn": 520000,
                "nr5g_rsrp_dbm": -75.0,
                "nr_sb_status": "LTE+NR",
            },
        }
        assert ScreenshotParser.detect_connection_mode(data) == "ENDC"

    def test_detect_connection_mode_nr_sa(self):
        """NR_SB_Status = 'NR only' without LTE → NR_SA."""
        data = {
            "lte_params": None,
            "nr_params": {
                "nr_band": 41,
                "nr_arfcn": 520000,
                "nr5g_rsrp_dbm": -68.0,
                "nr_sb_status": "NR only",
            },
        }
        assert ScreenshotParser.detect_connection_mode(data) == "NR_SA"

    def test_detect_connection_mode_nrdc(self):
        """Dual NR carriers with VLM NRDC tag → NRDC."""
        data = {
            "connection_mode": "NRDC",
            "lte_params": None,
            "nr_params": {
                "nr_band": 41,
                "nr_arfcn": 520000,
                "nr5g_rsrp_dbm": -68.0,
                "nr_sb_status": "NR only",
            },
        }
        assert ScreenshotParser.detect_connection_mode(data) == "NRDC"

    def test_detect_endc_fallback_no_status(self):
        """Both LTE and NR present without explicit nr_sb_status → ENDC fallback."""
        data = {
            "lte_params": {"band": 2, "earfcn": 600, "rsrp_dbm": -55.0},
            "nr_params": {
                "nr_band": 41,
                "nr_arfcn": 520000,
                "nr5g_rsrp_dbm": -75.0,
                "nr_sb_status": "",
            },
        }
        assert ScreenshotParser.detect_connection_mode(data) == "ENDC"

    def test_detect_no_params(self):
        """No LTE or NR params → LTE_ONLY default."""
        data = {"lte_params": None, "nr_params": None}
        assert ScreenshotParser.detect_connection_mode(data) == "LTE_ONLY"


# ---------------------------------------------------------------------------
# Sanitization tests
# ---------------------------------------------------------------------------

class TestSanitize:
    def test_sanitize_thinking_tags(self):
        """<think> tags stripped before JSON parsing."""
        raw = '<think>Let me analyze this carefully...</think>{"rsrp": -55}'
        result = strip_thinking_tags(raw)
        assert "<think>" not in result
        assert '{"rsrp": -55}' == result

    def test_sanitize_thinking_tags_multiline(self):
        """Multi-line think blocks stripped."""
        raw = '<think>\nI see the values:\n- RSRP = -55\n</think>\n{"rsrp": -55}'
        result = strip_thinking_tags(raw)
        assert "<think>" not in result
        parsed = extract_json(result)
        assert parsed == {"rsrp": -55}

    def test_sanitize_markdown_fences(self):
        """Markdown code fences stripped before JSON parsing."""
        raw = '```json\n{"rsrp": -55}\n```'
        result = strip_markdown_fences(raw)
        assert "```" not in result
        assert '{"rsrp": -55}' == result

    def test_sanitize_markdown_fences_no_lang(self):
        """Fences without language tag also stripped."""
        raw = '```\n{"rsrp": -55}\n```'
        result = strip_markdown_fences(raw)
        assert '{"rsrp": -55}' == result

    def test_extract_json_combined_sanitization(self):
        """Full pipeline: think tags + fences + unicode → valid JSON."""
        raw = '<think>reasoning</think>\n```json\n{"rsrp": -55, "sinr": 28}\n```'
        parsed = extract_json(raw)
        assert parsed == {"rsrp": -55, "sinr": 28}

    def test_extract_json_with_surrounding_text(self):
        """JSON extracted even with surrounding non-JSON text."""
        raw = 'Here are the results: {"rsrp": -55} as extracted.'
        parsed = extract_json(raw)
        assert parsed == {"rsrp": -55}


# ---------------------------------------------------------------------------
# Base64 encoding tests
# ---------------------------------------------------------------------------

class TestBase64Encoding:
    def test_base64_encoding(self, dummy_image):
        """Verify image encoded as base64, not file path."""
        encoded = ScreenshotParser._encode_image(dummy_image)

        # Should be a valid base64 string (not the file path itself)
        assert str(dummy_image) not in encoded
        assert isinstance(encoded, str)
        assert len(encoded) > 0

        # Should be valid base64 that decodes to a JPEG
        decoded = base64.b64decode(encoded)
        assert decoded[:2] == b"\xff\xd8", "Decoded bytes should be a JPEG (SOI marker)"

    def test_base64_encoding_missing_file(self):
        """FileNotFoundError for nonexistent image."""
        with pytest.raises(FileNotFoundError):
            ScreenshotParser._encode_image("/nonexistent/image.jpg")


# ---------------------------------------------------------------------------
# Pydantic schema validation tests
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_service_mode_valid(self):
        """Valid service mode data passes Pydantic validation."""
        data = ServiceModeData(
            screenshot_type="service_mode",
            connection_mode="ENDC",
            lte_params=LTEParams(rsrp_dbm=-55.0),
            nr_params=NRParams(nr5g_rsrp_dbm=-68.0),
            confidence=0.95,
        )
        assert data.connection_mode == "ENDC"

    def test_service_mode_invalid_connection_mode(self):
        """Invalid connection_mode rejected by Pydantic."""
        with pytest.raises(ValueError):
            ServiceModeData(connection_mode="INVALID_MODE")

    def test_speedtest_valid(self):
        """Valid speedtest data passes Pydantic validation."""
        data = SpeedtestData(
            dl_throughput_mbps=250.5,
            ul_throughput_mbps=45.2,
            confidence=0.9,
        )
        assert data.dl_throughput_mbps == 250.5

    def test_confidence_bounds(self):
        """Confidence must be 0.0-1.0."""
        with pytest.raises(ValueError):
            ServiceModeData(confidence=1.5)


# ---------------------------------------------------------------------------
# Gallery filename parsing tests
# ---------------------------------------------------------------------------

class TestGalleryFilename:
    def test_parse_gallery_filename(self):
        """Gallery suffix recognized as service_mode screenshot type."""
        result = parse_screenshot_filename("CELL01_LTE_20250101_120000_Gallery.jpg")
        assert result is not None
        assert result["screenshot_type"] == "service_mode"
        assert result["cell_id"] == "CELL01"
        assert result["tech"] == "LTE"
        assert result["date"] == "20250101"
        assert result["time"] == "120000"

    def test_parse_gallery_case_insensitive(self):
        """Gallery matching is case-insensitive."""
        result = parse_screenshot_filename("CELL02_NR_20250315_093045_gallery.jpg")
        assert result is not None
        assert result["screenshot_type"] == "service_mode"

    def test_parse_gallery_uppercase(self):
        """Uppercase GALLERY also works."""
        result = parse_screenshot_filename("CELL03_NR_20250315_093045_GALLERY.jpg")
        assert result is not None
        assert result["screenshot_type"] == "service_mode"


# ---------------------------------------------------------------------------
# Extraction failure handling tests
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_image(tmp_path):
    """Create a valid JPEG file that Pillow can open."""
    from PIL import Image
    img_path = tmp_path / "valid_test.jpg"
    img = Image.new("RGB", (100, 100), color="red")
    img.save(str(img_path), format="JPEG")
    return img_path


class TestExtractionFailure:
    def test_extraction_failure_skipped(self, parser, mock_ollama, valid_image):
        """Failed extraction marks result as EXTRACTION_FAILED and continues."""
        # Both attempts raise ValueError
        mock_ollama.chat_vision_json.return_value = (None, 3)

        pairs = [{
            "service_mode": {"path": valid_image},
            "speedtest": {"path": valid_image},
            "cell_id": "CELL01",
            "sector": 1,
            "tech_subfolder": "L19",
            "tech_info": {"tech": "LTE", "band": "B19"},
            "duration_sec": 30,
        }]

        results = parser.process_all_pairs(pairs)
        assert len(results) == 1
        assert results[0]["status"] == "EXTRACTION_FAILED"
        assert results[0]["error"] is not None
        assert results[0]["service_mode"] is None

    def test_successful_extraction_has_no_status(self, parser, mock_ollama, valid_image):
        """Successful extraction does not set EXTRACTION_FAILED status."""
        mock_ollama.chat_vision_json.side_effect = [
            ({"screenshot_type": "service_mode", "connection_mode": "LTE_ONLY",
              "lte_params": {"rsrp_dbm": -55.0}, "confidence": 0.9}, 1),
            ({"screenshot_type": "speedtest", "dl_throughput_mbps": 200.0,
              "ul_throughput_mbps": 40.0, "confidence": 0.9}, 1),
        ]

        pairs = [{
            "service_mode": {"path": valid_image},
            "speedtest": {"path": valid_image},
            "cell_id": "CELL02",
            "sector": 1,
            "tech_subfolder": "L19",
            "tech_info": {"tech": "LTE", "band": "B19"},
            "duration_sec": 25,
        }]

        results = parser.process_all_pairs(pairs)
        assert len(results) == 1
        assert results[0].get("status") != "EXTRACTION_FAILED"
        assert results[0]["service_mode"] is not None
