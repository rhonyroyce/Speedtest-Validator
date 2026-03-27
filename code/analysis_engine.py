"""Analysis engine — correlates RF data with knowledge base, calls gpt-oss:20b.

Orchestrates the analysis phase of the pipeline:
1. Receives extracted RF data (from VLM) + CIQ config + threshold results
2. Builds rich context from knowledge engine
3. Sends structured prompts to gpt-oss:20b for Observations, Recommendations, KPI Impact
4. Validates and sanitizes LLM output (retry on empty/invalid)

CRITICAL: This runs during the ANALYSIS phase — qwen3-vl:8b must be unloaded first.

Implementation: Claude Code Prompt 7 (Analysis Engine)
"""
import logging
import os
import re

from .utils.text_utils import (
    strip_thinking_tags,
    strip_markdown_fences,
    clean_unicode,
    normalize_whitespace,
)

logger = logging.getLogger(__name__)


def _sanitize_text(text: str) -> str:
    """Apply full sanitization pipeline to LLM text output."""
    text = strip_thinking_tags(text)
    text = strip_markdown_fences(text)
    text = clean_unicode(text)
    text = normalize_whitespace(text)
    return text


class AnalysisEngine:
    """Generates Observations, Recommendations, and KPI Impact via gpt-oss:20b."""

    def __init__(self, config: dict, ollama_client, knowledge_engine):
        self.config = config
        self.ollama = ollama_client
        self.knowledge = knowledge_engine

        ollama_cfg = config.get("ollama", {})
        self.model = ollama_cfg.get("analysis_model", "gpt-oss:20b")
        self.temperature = ollama_cfg.get("analysis_temperature", 0.3)
        self.max_retries = ollama_cfg.get("max_retries", 3)

        # Resolve prompt template directory
        self.prompts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "prompts"
        )

        # Cache loaded templates
        self._template_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_cell(
        self, cell_data: dict, ciq_config: dict, threshold_result: dict
    ) -> dict:
        """Full analysis pipeline for one cell.

        Args:
            cell_data: Extracted RF measurements (rsrp, sinr, rsrq, tx_power,
                       dl_throughput, ul_throughput, conn_mode, tech, etc.)
            ciq_config: CIQ parameters for this cell (bandwidth, PCI, EARFCN, etc.)
            threshold_result: Pass/fail result from threshold_engine with
                              dl_pass, ul_pass, service_mode results, etc.

        Returns:
            Dict with observations, recommendations, kpi_impact strings.
        """
        # 1. Build context from knowledge engine
        context = self.knowledge.build_analysis_context(cell_data)

        # Enrich context with CIQ config and threshold results
        context["ciq_config"] = ciq_config
        context["threshold_result"] = threshold_result

        # 2. Generate all three analysis outputs
        observations = self._retry_on_failure(
            lambda: self.generate_observations(context)
        )
        recommendations = self._retry_on_failure(
            lambda: self.generate_recommendations(context)
        )
        kpi_impact = self._retry_on_failure(
            lambda: self.generate_kpi_impact(context)
        )

        return {
            "observations": observations or "",
            "recommendations": recommendations or "",
            "kpi_impact": kpi_impact or "",
        }

    def generate_observations(self, context: dict) -> str:
        """Generate observation paragraph via gpt-oss:20b."""
        template_path = os.path.join(self.prompts_dir, "observation_generation.md")
        prompt = self._build_prompt(template_path, context)
        raw = self.ollama.chat_text(prompt, model=self.model, temperature=self.temperature)
        result = _sanitize_text(raw)
        if not result:
            logger.warning("Empty observation output from LLM")
        return result

    def generate_recommendations(self, context: dict) -> str:
        """Generate recommendations via gpt-oss:20b."""
        template_path = os.path.join(self.prompts_dir, "recommendation_generation.md")
        prompt = self._build_prompt(template_path, context)
        raw = self.ollama.chat_text(prompt, model=self.model, temperature=self.temperature)
        result = _sanitize_text(raw)
        if not result:
            logger.warning("Empty recommendation output from LLM")
        return result

    def generate_kpi_impact(self, context: dict) -> str:
        """Generate KPI impact assessment via gpt-oss:20b."""
        template_path = os.path.join(self.prompts_dir, "kpi_impact_generation.md")
        prompt = self._build_prompt(template_path, context)
        raw = self.ollama.chat_text(prompt, model=self.model, temperature=self.temperature)
        result = _sanitize_text(raw)
        if not result:
            logger.warning("Empty KPI impact output from LLM")
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, template_path: str, context: dict) -> str:
        """Load a .md template and inject context values as placeholder replacements.

        Placeholders use {PLACEHOLDER} format. Values are drawn from the
        flattened context dict.
        """
        # Load template (with caching), stripping YAML front matter if present
        if template_path not in self._template_cache:
            with open(template_path, "r", encoding="utf-8") as f:
                raw = f.read()
            # Strip YAML front matter (---\n...\n---)
            raw = re.sub(r"\A---\n.*?\n---\n*", "", raw, count=1, flags=re.DOTALL)
            self._template_cache[template_path] = raw
        template = self._template_cache[template_path]

        # Build flat replacement map from nested context
        replacements = self._flatten_context(context)

        # Append structured data section to the template
        data_section = self._format_data_section(context)
        prompt = template + "\n\n## Cell Data\n\n" + data_section

        # Replace any {PLACEHOLDER} tokens in template
        for key, value in replacements.items():
            placeholder = "{" + key.upper() + "}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(value))

        return prompt

    def _flatten_context(self, context: dict) -> dict:
        """Flatten nested context dict into key-value pairs for placeholder replacement."""
        flat = {}
        cell = context.get("cell_data", {})
        for key, val in cell.items():
            flat[key] = val if val is not None else "N/A"

        # Threshold values
        thresholds = context.get("thresholds")
        if thresholds:
            for key in ("dl_min", "dl_max", "ul_min", "ul_max"):
                flat[f"threshold_{key}"] = thresholds.get(key, "N/A")
            flat["conn_mode"] = thresholds.get("conn_mode", "N/A")
            flat["mimo_config"] = thresholds.get("mimo_config", "N/A")

        # Efficiency
        flat["dl_efficiency"] = context.get("dl_efficiency", "N/A")
        flat["ul_efficiency"] = context.get("ul_efficiency", "N/A")

        return flat

    def _format_data_section(self, context: dict) -> str:
        """Format context into a structured text block for the LLM prompt."""
        lines = []
        cell = context.get("cell_data", {})

        # RF Parameters
        lines.append("### RF Parameters")
        for param in ("rsrp", "sinr", "rsrq", "tx_power"):
            val = cell.get(param)
            lines.append(f"- {param.upper()}: {val if val is not None else 'N/A'}")

        # Throughput
        lines.append("\n### Throughput")
        dl = cell.get("dl_throughput")
        ul = cell.get("ul_throughput")
        lines.append(f"- DL Throughput: {dl if dl is not None else 'N/A'} Mbps")
        lines.append(f"- UL Throughput: {ul if ul is not None else 'N/A'} Mbps")

        dl_eff = context.get("dl_efficiency")
        ul_eff = context.get("ul_efficiency")
        if dl_eff is not None:
            lines.append(f"- DL Efficiency: {dl_eff}%")
        if ul_eff is not None:
            lines.append(f"- UL Efficiency: {ul_eff}%")

        # Connection info
        lines.append("\n### Configuration")
        lines.append(f"- Connection Mode: {cell.get('conn_mode', 'N/A')}")
        lines.append(f"- Technology: {cell.get('tech', 'N/A')}")
        lines.append(f"- MIMO Config: {cell.get('mimo_config', 'N/A')}")
        lines.append(f"- BW LTE: {cell.get('bw_lte_mhz', 'N/A')} MHz")
        lines.append(f"- BW NR C1: {cell.get('bw_nr_c1_mhz', 'N/A')} MHz")
        lines.append(f"- BW NR C2: {cell.get('bw_nr_c2_mhz', 'N/A')} MHz")

        # Thresholds
        thresholds = context.get("thresholds")
        if thresholds:
            lines.append("\n### Thresholds")
            lines.append(f"- DL Min: {thresholds.get('dl_min', 'N/A')} Mbps")
            lines.append(f"- DL Max: {thresholds.get('dl_max', 'N/A')} Mbps")
            lines.append(f"- UL Min: {thresholds.get('ul_min', 'N/A')} Mbps")
            lines.append(f"- UL Max: {thresholds.get('ul_max', 'N/A')} Mbps")

        # Threshold result (pass/fail)
        tr = context.get("threshold_result")
        if tr:
            lines.append("\n### Pass/Fail Status")
            lines.append(f"- DL Pass: {tr.get('dl_pass', 'N/A')}")
            lines.append(f"- UL Pass: {tr.get('ul_pass', 'N/A')}")
            sm_results = tr.get("service_mode", {})
            if isinstance(sm_results, dict):
                for param, result in sm_results.items():
                    if isinstance(result, dict):
                        lines.append(
                            f"- {param.upper()}: {result.get('pass_fail', '?')} "
                            f"(measured={result.get('value')}, "
                            f"range={result.get('min')}~{result.get('max')})"
                        )

        # RF observations from knowledge engine
        obs = context.get("rf_observations", [])
        if obs:
            lines.append("\n### RF Observations (Knowledge Base)")
            for o in obs:
                lines.append(f"- {o}")

        # Throughput context (theoretical peaks)
        tp = context.get("throughput_context", {})
        for direction in ("dl", "ul"):
            peak_info = tp.get(direction)
            if peak_info:
                lines.append(f"- {direction.upper()} Theoretical Peak: {peak_info.get('peak', 'N/A')} Mbps")
                lines.append(f"- {direction.upper()} Typical DAS: {peak_info.get('typical_das', 'N/A')} Mbps")

        # KPI impacts from knowledge engine
        kpi_text = context.get("kpi_impact_text")
        if kpi_text:
            lines.append(f"\n### KPI Impact Context\n{kpi_text}")

        # CIQ config
        ciq = context.get("ciq_config")
        if ciq:
            lines.append("\n### CIQ Configuration")
            for key, val in ciq.items():
                lines.append(f"- {key}: {val}")

        return "\n".join(lines)

    def _retry_on_failure(self, func, max_retries: int | None = None) -> str | None:
        """Call func(); if result is empty/None, retry up to max_retries times.

        On retry, the underlying generate_* method will be called again,
        producing a fresh LLM call.

        Returns:
            Non-empty result string, or None if all retries exhausted.
        """
        retries = max_retries if max_retries is not None else self.max_retries

        for attempt in range(1, retries + 1):
            try:
                result = func()
                if result and result.strip():
                    if attempt > 1:
                        logger.info("Retry succeeded on attempt %d", attempt)
                    return result
                logger.warning("Empty LLM result (attempt %d/%d)", attempt, retries)
            except Exception:
                logger.exception("LLM call failed (attempt %d/%d)", attempt, retries)

        logger.error("All %d retry attempts exhausted", retries)
        return None
