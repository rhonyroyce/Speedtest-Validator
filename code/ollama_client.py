"""Ollama API client — vision + text model support with VRAM-aware model switching.

CRITICAL: 16GB VRAM constraint. Cannot run both models simultaneously.
Model names are configured in config.yaml — do not hardcode here.
Must unload one model before loading the other via keep_alive: 0.

Implementation: Claude Code Prompt 2 (Ollama Client)
"""
import json
import logging
import time
import urllib.error
import urllib.request

from .utils.text_utils import extract_json as _extract_json_text

logger = logging.getLogger(__name__)


class OllamaClient:
    """Unified Ollama API client for vision and text models (see config.yaml)."""

    def __init__(self, config: dict):
        ollama_cfg = config.get("ollama", {})
        self.base_url = ollama_cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.vision_model = ollama_cfg.get("vision_model", "qwen2.5-vl:7b")
        self.analysis_model = ollama_cfg.get("analysis_model", "gpt-oss:20b")
        self.max_retries = ollama_cfg.get("max_retries", 3)
        self.extraction_temperature = ollama_cfg.get("extraction_temperature", 0.15)
        self.analysis_temperature = ollama_cfg.get("analysis_temperature", 0.3)
        self.timeout = ollama_cfg.get("timeout", 300)
        self.vision_timeout = ollama_cfg.get("vision_timeout", 600)

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None,
                 timeout: int | None = None) -> dict:
        """Send an HTTP request to the Ollama API and return parsed JSON."""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
            return json.loads(resp.read().decode())

    def _request_with_retry(self, method: str, path: str, body: dict | None = None,
                            timeout: int | None = None) -> dict:
        """HTTP request with exponential backoff on connection/timeout errors."""
        last_err = None
        for attempt in range(self.max_retries):
            try:
                return self._request(method, path, body, timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_err = exc
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning("Ollama request failed (attempt %d/%d): %s — retrying in %ds",
                               attempt + 1, self.max_retries, exc, wait)
                time.sleep(wait)
        raise ConnectionError(f"Ollama unreachable after {self.max_retries} attempts: {last_err}")

    # ------------------------------------------------------------------
    # Health & model status
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Verify Ollama is running via GET /api/ps. Returns True if HTTP 200."""
        try:
            self._request("GET", "/api/ps", timeout=10)
            return True
        except Exception:
            return False

    def validate_models_available(self) -> list[str]:
        """Check that vision and analysis models are pulled locally.

        Queries GET /api/tags and compares against self.vision_model and
        self.analysis_model. Returns list of model names that are missing.
        """
        try:
            resp = self._request("GET", "/api/tags", timeout=10)
        except Exception:
            return [self.vision_model, self.analysis_model]

        available = {m["name"] for m in resp.get("models", [])}
        missing = []
        for required in (self.vision_model, self.analysis_model):
            if required not in available:
                missing.append(required)
        return missing

    def get_loaded_models(self) -> list[str]:
        """Return list of currently loaded model names via GET /api/ps."""
        try:
            resp = self._request("GET", "/api/ps", timeout=10)
            return [m["name"] for m in resp.get("models", [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Model lifecycle (VRAM-critical)
    # ------------------------------------------------------------------

    def unload_model(self, model_name: str) -> None:
        """Unload a model from VRAM via keep_alive: 0. Verify via /api/ps."""
        logger.info("Unloading model: %s", model_name)
        self._request_with_retry("POST", "/api/generate", {
            "model": model_name,
            "prompt": "",
            "keep_alive": 0,
        })
        # Verify unloaded
        for _ in range(10):
            loaded = self.get_loaded_models()
            if model_name not in loaded:
                logger.info("Model %s unloaded successfully", model_name)
                return
            time.sleep(1)
        logger.warning("Model %s may still be loaded after unload request", model_name)

    def ensure_model_loaded(self, model_name: str) -> None:
        """Load a model into VRAM. Triggers load via empty generate, waits for /api/ps."""
        loaded = self.get_loaded_models()
        if model_name in loaded:
            logger.debug("Model %s already loaded", model_name)
            return

        # Unload any other models first (VRAM constraint)
        for other in loaded:
            if other != model_name:
                self.unload_model(other)

        logger.info("Loading model: %s", model_name)
        self._request_with_retry("POST", "/api/generate", {
            "model": model_name,
            "prompt": "",
            "keep_alive": "5m",
        }, timeout=600)

        # Wait for model to appear in /api/ps
        for _ in range(60):
            if model_name in self.get_loaded_models():
                logger.info("Model %s loaded successfully", model_name)
                return
            time.sleep(2)
        raise TimeoutError(f"Model {model_name} did not load within timeout")

    # ------------------------------------------------------------------
    # Chat endpoints
    # ------------------------------------------------------------------

    def _chat(self, model: str, messages: list[dict], temperature: float,
              timeout: int | None = None) -> str:
        """Send a chat request and return the assistant's response text."""
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        resp = self._request_with_retry("POST", "/api/chat", body, timeout=timeout or self.timeout)
        return resp.get("message", {}).get("content", "")

    def chat_with_vision(self, image_base64: str, prompt: str,
                         model: str | None = None,
                         temperature: float | None = None) -> str:
        """Send an image + prompt to the vision model. Returns raw response text.

        Args:
            image_base64: Base64-encoded image (no data URI prefix).
            prompt: Text prompt for the vision model.
            model: Model name (defaults to configured vision_model).
            temperature: Sampling temperature (defaults to extraction_temperature).
        """
        model = model or self.vision_model
        temp = temperature if temperature is not None else self.extraction_temperature
        messages = [{
            "role": "user",
            "content": prompt,
            "images": [image_base64],
        }]
        return self._chat(model, messages, temp, timeout=self.vision_timeout)

    def chat_text(self, prompt: str, model: str | None = None,
                  temperature: float | None = None) -> str:
        """Send a text-only prompt to the analysis model. Returns raw response text.

        Args:
            prompt: Text prompt.
            model: Model name (defaults to configured analysis_model).
            temperature: Sampling temperature (defaults to analysis_temperature).
        """
        model = model or self.analysis_model
        temp = temperature if temperature is not None else self.analysis_temperature
        messages = [{"role": "user", "content": prompt}]
        return self._chat(model, messages, temp)

    # ------------------------------------------------------------------
    # JSON extraction with retry
    # ------------------------------------------------------------------

    def extract_json(self, raw_response: str) -> dict | list | None:
        """Sanitize LLM output and parse JSON using text_utils pipeline."""
        return _extract_json_text(raw_response)

    def chat_vision_json(self, image_base64: str, prompt: str,
                         model: str | None = None,
                         temperature: float | None = None) -> tuple[dict | list | None, int]:
        """Vision call with automatic JSON extraction and retry on parse failure.

        Returns:
            Tuple of (parsed_json, attempt_number). attempt_number indicates confidence:
            1 = high confidence, 2 = medium, 3 = low.
        """
        model = model or self.vision_model
        temp = temperature if temperature is not None else self.extraction_temperature

        for attempt in range(1, self.max_retries + 1):
            current_prompt = prompt
            if attempt > 1:
                current_prompt = prompt + "\n\nOutput ONLY valid JSON. No markdown, no explanation."

            raw = self.chat_with_vision(image_base64, current_prompt, model, temp)
            logger.debug("VLM raw response length: %d chars", len(raw) if raw else 0)
            logger.debug("VLM raw response (first 500 chars): %s", raw[:500] if raw else "EMPTY")
            parsed = self.extract_json(raw)
            if parsed is not None:
                return parsed, attempt

            logger.warning("JSON parse failed on vision response (attempt %d/%d)",
                           attempt, self.max_retries)

        logger.error("All %d JSON extraction attempts failed", self.max_retries)
        return None, self.max_retries

    def chat_text_json(self, prompt: str, model: str | None = None,
                       temperature: float | None = None) -> tuple[dict | list | None, int]:
        """Text call with automatic JSON extraction and retry on parse failure.

        Returns:
            Tuple of (parsed_json, attempt_number). attempt_number indicates confidence:
            1 = high confidence, 2 = medium, 3 = low.
        """
        model = model or self.analysis_model
        temp = temperature if temperature is not None else self.analysis_temperature

        for attempt in range(1, self.max_retries + 1):
            current_prompt = prompt
            if attempt > 1:
                current_prompt = prompt + "\n\nOutput ONLY valid JSON. No markdown, no explanation."

            raw = self.chat_text(current_prompt, model, temp)
            parsed = self.extract_json(raw)
            if parsed is not None:
                return parsed, attempt

            logger.warning("JSON parse failed on text response (attempt %d/%d)",
                           attempt, self.max_retries)

        logger.error("All %d JSON extraction attempts failed", self.max_retries)
        return None, self.max_retries
