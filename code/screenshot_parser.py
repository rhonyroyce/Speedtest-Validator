"""Screenshot discovery and VLM extraction.

Discovers screenshot pairs (Service Mode + Speedtest) in site folders,
calls qwen3-vl:8b for extraction, validates JSON schema, builds manifest.

Implementation: Claude Code Prompt 3 (Screenshot Parser)
"""
# TODO: Implement ScreenshotParser class with:
# - discover_screenshots(site_folder) — walk SECTOR X/{tech}/ subfolders
# - pair_screenshots(screenshots) — match SM + ST by timestamp proximity (≤4 min)
# - extract_service_mode(image_path) — call VLM, return validated JSON
# - extract_speedtest(image_path) — call VLM, return validated JSON
# - detect_connection_mode(sm_data) — LTE_ONLY/NR_SA/ENDC/NRDC from SM fields
# - build_manifest(site_folder) — complete extraction manifest
