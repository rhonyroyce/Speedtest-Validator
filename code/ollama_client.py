"""Ollama API client — vision + text model support with VRAM-aware model switching.

CRITICAL: 16GB VRAM constraint. Cannot run qwen3-vl:8b and gpt-oss:20b simultaneously.
Must unload one model before loading the other via keep_alive: 0.

Implementation: Claude Code Prompt 2 (Ollama Client)
"""
# TODO: Implement OllamaClient class with:
# - ensure_model_loaded(model_name) — loads model, verifies via GET /api/ps
# - unload_model(model_name) — POST /api/generate with keep_alive: 0
# - extract_from_image(image_base64, prompt, schema) — vision model call
# - generate_text(system_prompt, user_prompt) — text model call
# - validate_json_output(raw_output, schema) — parse + validate + retry
# - clean_llm_output(raw) — strip thinking tags, markdown fences, Unicode
