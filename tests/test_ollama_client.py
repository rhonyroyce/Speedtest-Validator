"""Tests for ollama_client.py — health check and model validation."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.ollama_client import OllamaClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    return {
        "ollama": {
            "base_url": "http://localhost:11434",
            "vision_model": "qwen2.5vl:7b",
            "analysis_model": "gpt-oss:20b",
            "max_retries": 3,
            "extraction_temperature": 0.15,
            "analysis_temperature": 0.3,
            "timeout": 300,
        }
    }


@pytest.fixture
def client(mock_config):
    return OllamaClient(mock_config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_success(self, client):
        with patch.object(client, "_request", return_value={"models": []}):
            assert client.health_check() is True

    def test_health_check_failure(self, client):
        with patch.object(client, "_request", side_effect=ConnectionError("refused")):
            assert client.health_check() is False


class TestValidateModelsAvailable:
    def test_all_models_present(self, client):
        resp = {
            "models": [
                {"name": "qwen2.5vl:7b", "size": 6_000_000_000},
                {"name": "gpt-oss:20b", "size": 13_000_000_000},
                {"name": "llama3:8b", "size": 4_700_000_000},
            ]
        }
        with patch.object(client, "_request", return_value=resp):
            assert client.validate_models_available() == []

    def test_vision_model_missing(self, client):
        resp = {
            "models": [
                {"name": "gpt-oss:20b", "size": 13_000_000_000},
            ]
        }
        with patch.object(client, "_request", return_value=resp):
            missing = client.validate_models_available()
            assert missing == ["qwen2.5vl:7b"]

    def test_analysis_model_missing(self, client):
        resp = {
            "models": [
                {"name": "qwen2.5vl:7b", "size": 6_000_000_000},
            ]
        }
        with patch.object(client, "_request", return_value=resp):
            missing = client.validate_models_available()
            assert missing == ["gpt-oss:20b"]

    def test_both_models_missing(self, client):
        resp = {
            "models": [
                {"name": "llama3:8b", "size": 4_700_000_000},
            ]
        }
        with patch.object(client, "_request", return_value=resp):
            missing = client.validate_models_available()
            assert missing == ["qwen2.5vl:7b", "gpt-oss:20b"]

    def test_api_unreachable_returns_both(self, client):
        with patch.object(client, "_request", side_effect=ConnectionError("refused")):
            missing = client.validate_models_available()
            assert missing == ["qwen2.5vl:7b", "gpt-oss:20b"]

    def test_empty_models_list(self, client):
        resp = {"models": []}
        with patch.object(client, "_request", return_value=resp):
            missing = client.validate_models_available()
            assert missing == ["qwen2.5vl:7b", "gpt-oss:20b"]
