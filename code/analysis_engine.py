"""Analysis engine — correlates RF data with knowledge base, calls gpt-oss:20b.

Orchestrates the analysis phase of the pipeline:
1. Receives extracted RF data (from VLM) + CIQ config + threshold results
2. Builds rich context from knowledge engine
3. Sends structured prompts to gpt-oss:20b for Observations, Recommendations, KPI Impact
4. Validates and sanitizes LLM output (JSON schema + retry)

CRITICAL: This runs during the ANALYSIS phase — qwen3-vl:8b must be unloaded first.

Implementation: Claude Code Prompt 7 (Analysis Engine)
"""
# TODO: Implement AnalysisEngine class with:
# - __init__(config, ollama_client, knowledge_engine) — wire dependencies
# - analyze_cell(cell_data, ciq_config, threshold_result) — full analysis for one cell
# - generate_observations(context) — call gpt-oss:20b with observation prompt
# - generate_recommendations(context) — call gpt-oss:20b with recommendation prompt
# - generate_kpi_impact(context) — call gpt-oss:20b with KPI impact prompt
# - _build_prompt(template_path, context) — load .md template, inject context vars
# - _validate_analysis_output(raw_text) — validate structure, sanitize
# - _retry_on_failure(func, max_retries=3) — retry wrapper for LLM calls
#
# LLM Settings:
#   - Model: gpt-oss:20b (from config.yaml)
#   - Temperature: 0.3
#   - Max tokens: 1024 per call
#   - JSON validation with schema + retry (max 3 attempts)
#
# Dependencies:
#   - code/ollama_client.py (for LLM API calls)
#   - code/knowledge_engine.py (for context building)
#   - code/prompts/observation_generation.md
#   - code/prompts/recommendation_generation.md
#   - code/prompts/kpi_impact_generation.md
#   - code/utils/text_utils.py (for sanitization)
