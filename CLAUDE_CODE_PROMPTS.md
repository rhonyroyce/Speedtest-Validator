# DAS Speed Test Validator — 10 Claude Code Prompts

Execute these prompts in order (1→10) in Claude Code. Each builds on the previous.
Prompt 1 is already done (folder structure exists). Start from Prompt 2.

---

## Prompt 1: Project Scaffold ✅ COMPLETE
Already implemented — folder structure, config.yaml, requirements.txt, CLAUDE.md, all __init__.py files, prompt templates, and placeholder modules are in place.

---

## Prompt 2: Ollama Client

```
Implement code/ollama_client.py — the unified Ollama API client for both qwen3-vl:8b (vision) and gpt-oss:20b (analysis).

CRITICAL CONSTRAINT: 16 GB total VRAM. Cannot run both models simultaneously.

Read CLAUDE.md first for the GPU/Model Management rules.

Class: OllamaClient
  __init__(self, config): Load base_url, model names, timeout, max_retries from config.yaml

Methods:
  - ensure_model_loaded(model_name): POST /api/generate with empty prompt to trigger load. Wait until GET /api/ps shows the model running.
  - unload_model(model_name): POST /api/generate {"model": model_name, "keep_alive": 0}. Verify via GET /api/ps showing 0 models loaded.
  - chat_with_vision(image_base64, prompt, model="qwen3-vl:8b"): POST /api/chat with messages containing image. Return raw response text.
  - chat_text(prompt, model="gpt-oss:20b", temperature=0.3): POST /api/chat for text-only. Return raw response text.
  - extract_json(raw_response): Sanitize LLM output (strip thinking tags, markdown fences, unicode artifacts), then parse JSON. Use code/utils/text_utils.py sanitization functions.
  - health_check(): GET /api/tags to verify Ollama is running.
  - get_loaded_models(): GET /api/ps, return list of currently loaded models.

Retry logic:
  - On connection error or timeout: retry up to max_retries with exponential backoff (1s, 2s, 4s)
  - On JSON parse failure: retry the LLM call with a stricter prompt suffix: "Output ONLY valid JSON. No markdown, no explanation."
  - Track attempt count for confidence scoring (attempt 1 = high confidence, attempt 3 = low)

Use only Python stdlib (urllib.request, json) for HTTP — no requests library needed for Ollama calls.
Also implement the text_utils.py sanitization functions that this module depends on:
  - strip_thinking_tags(text): Remove <think>...</think> blocks (re.DOTALL)
  - strip_markdown_fences(text): Remove ```json ... ``` and ``` ... ```
  - clean_unicode(text): Remove BOM, zero-width chars, replace smart quotes with ASCII
  - extract_json(text): Pipeline: strip thinking → strip fences → clean unicode → json.loads. Fallback: find first {/[ to last }/].
  - normalize_whitespace(text): Collapse multiple spaces, strip edges.

Test: Run python -c "from code.ollama_client import OllamaClient; print('OK')"
```

---

## Prompt 3: Screenshot Parser + File Utils

```
Implement code/screenshot_parser.py and code/utils/file_utils.py — screenshot discovery, filename parsing, timestamp pairing, and VLM extraction.

Read CLAUDE.md for Screenshot Convention and Site Folder Structure.

=== code/utils/file_utils.py ===

Functions:
  - discover_screenshots(site_folder): Recursively find all .jpg files. Parse parent dirs to get sector number and tech subfolder. Return list of dicts: [{path, sector, tech_subfolder, filename, screenshot_type}, ...]
  - parse_screenshot_filename(filename): Split by '_'. Extract cell_id, tech, date (YYYYMMDD), time (HHMMSS), type ("Service mode RIL" or "Speedtest"). Parse into datetime. Return dict or None.
  - pair_screenshots(screenshots, max_gap_seconds=240): Group by (sector, tech_subfolder). Within each group, match service_mode with nearest speedtest within 4 minutes. Calculate SM-ST Duration in seconds. Warn on unmatched.
  - resolve_sector_number(path): Regex to extract number from "SECTOR X" or "Sector X" in path.
  - resolve_tech_from_subfolder(subfolder_name): Map subfolder name to tech/band/mode dict using TECH_SUBFOLDER_PATTERNS.

Tech subfolder mappings:
  "L19" → LTE B19, "L21" → LTE B21, "N19" → NR n19
  "N2500_C1 NSA" → NR n41 C1 NSA, "N2500_C1 SA" → NR n41 C1 SA
  "N2500_C2 NSA" → NR n41 C2 NSA, "N2500_C2 SA" → NR n41 C2 SA

Note: Screenshots may be in sector root OR tech subfolders — check both.

=== code/screenshot_parser.py ===

Class: ScreenshotParser
  __init__(self, config, ollama_client): Store config and client reference.

Methods:
  - extract_service_mode(image_path): Read image, base64 encode with Pillow, load prompt from code/prompts/service_mode_extraction.md, call ollama_client.chat_with_vision(). Validate JSON output against schema. Retry up to 3 times. Return structured dict.
  - extract_speedtest(image_path): Same flow using speedtest_extraction.md prompt.
  - detect_connection_mode(service_mode_data): Determine LTE Only / NR SA / EN-DC / NR-DC from extracted fields:
      * LTE Only: No NR fields, NR_SB_Status absent/empty
      * NR SA: NR_SB_Status = "NR only" or NR_BAND without ENDC
      * EN-DC (NSA): NR_SB_Status = "LTE+NR", both LTE and NR params present
      * NR-DC: Two NR ARFCNs or NR C1+C2 active without LTE anchor
  - process_all_pairs(screenshot_pairs): Iterate pairs, extract both screenshots, detect connection mode, return list of cell_data dicts.

Image encoding: Always use base64 for Ollama API — never pass file paths.
JSON validation: Define Pydantic models for ServiceModeData and SpeedtestData schemas.

Test: python -c "from code.screenshot_parser import ScreenshotParser; print('OK')"
```

---

## Prompt 4: CIQ Reader + Excel Utils

```
Implement code/ciq_reader.py and code/utils/excel_utils.py — CIQ Excel parsing with cell matching.

Read CLAUDE.md for CIQ Excel Structure section.

=== code/utils/excel_utils.py ===

Functions:
  - read_sheet_as_dicts(workbook_path, sheet_name, header_row=1): Open with openpyxl (read_only=True, data_only=True). Read header row for keys. Return list of row dicts.
  - find_column_index(sheet, column_name, header_row=1): Case-insensitive header search. Return 0-based index or None.
  - convert_bw_khz_to_mhz(bw_khz): Divide by 1000, round to 1 decimal.
  - safe_float(value, default=0.0): Safe type conversion.
  - safe_int(value, default=0): Safe type conversion.

=== code/ciq_reader.py ===

Class: CIQReader
  __init__(self, config): Store config, initialize empty cell lists.

Methods:
  - load(ciq_path): Open CIQ Excel. Read "eUtran Parameters" sheet → LTE cells. Read "gUtranCell info" sheet → NR cells. Store both as lists of dicts.
  - get_lte_cells(): Return list of LTE cell dicts with keys: eNBId, cellId, earfcnDl, dlChannelBandwidth (convert kHz→MHz), noOfTxAntennas, PCI, radioType
  - get_nr_cells(): Return list of NR cell dicts with keys: gNBID, gUtranCell, arfcnDl, channelBandwidth (convert kHz→MHz), PCI, radioType, configuredMaxTxPower
  - match_cell(earfcn=None, arfcn=None, pci=None): Find matching CIQ entry by EARFCN (LTE) or ARFCN (NR) or PCI. Return cell dict or None.
  - get_mimo_config(cell): Determine from noOfTxAntennas: 1 = SISO, 2+ = MIMO. Return "SISO" or "MIMO".
  - get_bandwidth_mhz(cell): Return bandwidth in MHz (already converted from kHz).
  - get_site_config_summary(): Return dict summarizing all cells by sector — used for Output.xlsx and docx.

CRITICAL: Bandwidth in CIQ is stored in kHz (20000 = 20 MHz, 100000 = 100 MHz). Always convert for display.

Test with the actual CIQ file:
  python -c "
  from code.ciq_reader import CIQReader
  from code.config import load_config
  cfg = load_config()
  reader = CIQReader(cfg)
  reader.load('input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx')
  print(f'LTE cells: {len(reader.get_lte_cells())}')
  print(f'NR cells: {len(reader.get_nr_cells())}')
  "
Expected: LTE cells: 6, NR cells: 16
```

---

## Prompt 5: Knowledge Engine + Knowledge Modules

```
Implement code/knowledge_engine.py and fill in the TODO methods in code/knowledge/ modules.

Read CLAUDE.md for the Knowledge Base Design rationale (direct dicts, NOT RAG).

=== Complete the 4 knowledge modules ===

code/knowledge/rf_parameters.py — already has dicts. Implement:
  - classify_rsrp(value_dbm): Check RSRP_QUALITY ranges, return {quality, label, color}
  - classify_sinr(value_db): Check SINR_QUALITY ranges
  - classify_rsrq(value_db): Check RSRQ_QUALITY ranges
  - generate_observation(param, value, **kwargs): Classify value, select template from OBSERVATION_TEMPLATES, format and return string

code/knowledge/throughput_benchmarks.py — already has peak tables. Implement:
  - get_theoretical_peak(tech, mimo_config, bw_mhz, direction): Navigate DL or UL table → tech → mimo → bw_mhz. Return {peak, typical_das} or None.
  - compute_throughput_efficiency(measured, peak): Return percentage.

code/knowledge/kpi_mappings.py — already has mapping dicts. Implement:
  - get_kpi_impacts(rf_data): Iterate RF_TO_KPI_MAPPINGS, check each trigger lambda against rf_data values. Collect matching impacts. Deduplicate by (domain, kpi). Sort by domain priority (AVL > ACC > RET > CAP > MOB > PWR). Return list of impact dicts.
  - format_kpi_impact_text(impacts): Group by domain. Format as "[DOMAIN] KPI_NAME: description". Join with newlines.

code/knowledge/mop_thresholds.py — already has schema. Implement:
  - load_threshold_excel(excel_path): Open DAS_Validation_Thresholds.xlsx with openpyxl. Load Service Mode, SISO, MIMO sheets. Return structured dict.
  - find_threshold_row(rows, bw_lte, bw_nr_c1, bw_nr_c2): Exact match on 3 BW dimensions. Return row dict or None.
  - get_progressive_ul_threshold(row, sinr_db): Find nearest lower SINR from [15,19,20,22,24,26,28,30]. Return UL threshold.

=== code/knowledge_engine.py ===

Class: KnowledgeEngine
  __init__(self, config): Store config reference.

Methods:
  - load_all(): Load thresholds from Excel, verify all knowledge dicts accessible.
  - get_rf_observation(param, value, **context): Delegate to rf_parameters.generate_observation()
  - get_throughput_context(tech, mimo, bw_mhz, direction): Delegate to throughput_benchmarks.get_theoretical_peak()
  - get_kpi_impacts(rf_data): Delegate to kpi_mappings.get_kpi_impacts()
  - get_threshold(mimo_config, bw_lte, bw_nr_c1, bw_nr_c2, conn_mode): Load from mop_thresholds, find row, return threshold for the specific DL/UL column based on connection mode.
  - build_analysis_context(cell_data): Assemble full context dict combining RF observations, throughput benchmarks, KPI impacts, and threshold results. This dict gets injected into analysis prompts.

Test: Load the threshold Excel and verify 16 SISO rows and 16 MIMO rows load correctly.
```

---

## Prompt 6: Threshold Engine

```
Implement code/threshold_engine.py — the multi-dimensional pass/fail engine.

Read CLAUDE.md section "DAS Validation Thresholds" and "Connection Mode Detection" carefully.

Class: ThresholdEngine
  __init__(self, config, knowledge_engine): Wire to knowledge engine for threshold data.

Methods:
  - load_thresholds(): Call knowledge_engine to load DAS_Validation_Thresholds.xlsx. Store service_mode, siso, mimo data.

  - check_service_mode(rsrp, sinr, rsrq, tx_power, end_type="radio_end"):
      Check against Service Mode thresholds:
        Radio End: RSRP -60 to -40, SINR >25, RSRQ -12 to -3, TX always negative
        Antenna End: RSRP -75 to -50, SINR >25, RSRQ -12 to -3, TX always negative
      Return: {param: {value, min, max, pass_fail, delta}, ...}

  - check_speed_test(dl_mbps, ul_mbps, mimo_config, bw_lte_mhz, bw_nr_c1_mhz, bw_nr_c2_mhz, connection_mode, sinr_db=None):
      5-dimensional lookup:
        1. Select SISO or MIMO sheet based on mimo_config
        2. Find row matching (bw_lte, bw_nr_c1, bw_nr_c2)
        3. Select DL column based on connection_mode:
           LTE Only → lte_dl_min/max
           NR SA → nr_dl_min/max
           EN-DC → endc_dl_min/max
           NR-DC → nrdc_dl_min/max
        4. Select UL column similarly. For EN-DC UL, use progressive UL threshold based on sinr_db.
        5. PASS if measured >= min threshold
      Return: {dl: {value, threshold_min, threshold_max, pass_fail, delta}, ul: {...}, connection_mode, bw_combo}

  - get_comment(service_mode_result, speed_test_result):
      Generate the Comment column text. Examples:
        "PASS — DL 285 Mbps (min 200), UL 45 Mbps (min 30)"
        "FAIL — DL 85 Mbps below 200 Mbps min (delta: -115 Mbps)"
      Include both service mode and speed test results.

  - summarize_cell(all_results):
      Aggregate pass/fail across service mode + speed test for a single cell.

CRITICAL: Never hardcode speed test threshold values. Always load from DAS_Validation_Thresholds.xlsx at runtime.

Test with known values:
  - SISO, LTE 20 MHz, no NR, LTE Only → check that correct threshold row is found
  - MIMO, LTE 20 MHz + NR 100 MHz, EN-DC → check EN-DC DL column used
  - Verify PASS for a value above min, FAIL for a value below min
```

---

## Prompt 7: Analysis Engine

```
Implement code/analysis_engine.py — correlates RF data with knowledge base and calls gpt-oss:20b.

CRITICAL: This module runs during Phase 2 of the pipeline. qwen3-vl:8b MUST be unloaded before gpt-oss:20b loads.

Class: AnalysisEngine
  __init__(self, config, ollama_client, knowledge_engine): Wire dependencies.

Methods:
  - analyze_cell(cell_data, ciq_config, threshold_result):
      Full analysis pipeline for one cell:
      1. Build context from knowledge_engine.build_analysis_context(cell_data)
      2. Call generate_observations(context)
      3. Call generate_recommendations(context)
      4. Call generate_kpi_impact(context)
      Return: {observations: str, recommendations: str, kpi_impact: str}

  - generate_observations(context):
      Load code/prompts/observation_generation.md template.
      Replace placeholders with context values (RSRP, SINR, RSRQ, TX Power, DL, UL, thresholds, connection mode, BW, theoretical peaks).
      Call ollama_client.chat_text(prompt, model="gpt-oss:20b", temperature=0.3).
      Sanitize output. Validate non-empty.
      Return observation text string.

  - generate_recommendations(context):
      Load code/prompts/recommendation_generation.md template.
      Inject same context plus threshold deltas and pass/fail status.
      Call ollama_client.chat_text().
      Return recommendation text string.

  - generate_kpi_impact(context):
      Load code/prompts/kpi_impact_generation.md template.
      Inject RF data + KPI impacts from knowledge_engine.get_kpi_impacts().
      Call ollama_client.chat_text().
      Return KPI impact text string.

  - _build_prompt(template_path, context):
      Read .md template file. Replace {PLACEHOLDER} tokens with context values.
      Return formatted prompt string.

  - _retry_on_failure(func, max_retries=3):
      Wrapper: call func(), if empty/None result, retry with stricter prompt.
      Log retry attempts.

LLM settings for all analysis calls:
  - Model: gpt-oss:20b (from config.yaml, never hardcode)
  - Temperature: 0.3
  - Max retries: 3

Test: python -c "from code.analysis_engine import AnalysisEngine; print('OK')"
```

---

## Prompt 8: Output Generators

```
Implement code/output_xlsx.py and code/output_docx.py — the two final deliverables.

Read CLAUDE.md Output Formats section for column definitions.

=== code/output_xlsx.py ===

Class: OutputXlsxGenerator
  __init__(self, config)

Methods:
  - generate(results, threshold_data, output_path):
      Create workbook with 2 tabs.

  - _create_results_tab(ws, results):
      Tab 1: "Validation Results"
      16 columns with headers in row 1 (bold, filter enabled):
        A: BTS | B: Tech/Sector | C: Connection Mode | D: Bandwidth
        E: PCI | F: RSRP | G: RSRQ | H: SINR | I: UE TX Power
        J: SM-ST Duration | K: DL Throughput | L: UL Throughput
        M: Comment | N: Observations | O: Recommendations | P: Impact on KPIs
      Row count = len(results) — dynamic per site.
      Apply conditional formatting:
        - PASS cells → green fill
        - FAIL cells → red fill
        - RSRP/SINR/RSRQ → color gradient by quality (excellent=green, poor=red)
      Auto-size column widths. Wrap text on Observations/Recommendations/KPI Impact columns.

  - _create_threshold_tab(ws, threshold_data):
      Tab 2: "Thresholds Reference"
      Copy SISO Speed Test table (16 rows + header), then MIMO Speed Test table, then Service Mode thresholds.
      Include all columns from DAS_Validation_Thresholds.xlsx.
      Purpose: auditability — reviewer can see exactly which thresholds were used.

=== code/output_docx.py ===

Class: OutputDocxGenerator
  __init__(self, config)

Methods:
  - generate(results, site_config, analysis_data, output_path):
      Create full Word document matching SFY0803A_RF_Throughput_Analysis.docx structure.

  - _add_title_page(doc, site_id, date):
      Title: "RF Throughput Analysis — {site_id}"
      Subtitle: "DAS Validation Report"
      Date, analyst name from config.

  - _add_executive_summary(doc, results):
      Overall pass/fail counts. Key findings (worst RSRP, worst SINR, any throughput failures).
      3 paragraphs of prose.

  - _add_site_config_table(doc, ciq_data):
      Table with: Sector, Technology, Band, Bandwidth, MIMO Config, PCI, EARFCN/ARFCN.
      One row per cell from CIQ.

  - _add_rf_deep_dive(doc, sector_results):
      Per sector/technology heading. RF parameters with observations.
      Include throughput results and pass/fail commentary.

  - _add_summary_tables(doc, results):
      Band Config table, Full Results table, BLER Summary (if available),
      BW vs Throughput comparison, RX Chain analysis (if available).

  - _add_kpi_correlation(doc, analysis_data):
      Section linking RF findings to KPI impacts. Reference MS2 KPI framework domains.

  - _add_glossary(doc):
      RF/telecom terms: RSRP, SINR, RSRQ, PCI, EARFCN, ARFCN, EN-DC, NR-DC, MIMO, SISO, BLER, MCS, etc.

  - _apply_styles(doc):
      Heading 1/2/3 hierarchy, justified body text, alternating table row colors.

Test: Generate a minimal output with mock data to verify both files create without error.
```

---

## Prompt 9: Main Orchestrator + CLI

```
Implement code/main.py — the CLI entry point and pipeline orchestrator.

Read CLAUDE.md for Build & Run Commands and the full pipeline sequence.

=== CLI Arguments (argparse) ===
  --site-folder PATH    : Path to site screenshot folder (required)
  --ciq PATH            : Path to CIQ Excel file (required)
  --output-dir PATH     : Output directory (default: ./outputs)
  --config PATH         : Config file path (default: config.yaml)
  --dry-run             : Process only first 2 screenshot pairs
  --verbose             : Enable debug logging

=== class DASValidator ===
  __init__(self, config_path="config.yaml"):
      Load config. Initialize all modules:
        ollama_client, screenshot_parser, ciq_reader,
        knowledge_engine, threshold_engine, analysis_engine,
        output_xlsx, output_docx

  run(self, site_folder, ciq_path, output_dir, dry_run=False):
      Execute the 6-phase pipeline:

      Phase 1 — Screenshot Discovery:
        file_utils.discover_screenshots(site_folder)
        file_utils.pair_screenshots(all_screenshots)
        If dry_run: keep only first 2 pairs
        Print: "Found {N} screenshot pairs across {S} sectors"

      Phase 2 — VLM Extraction (qwen3-vl:8b):
        ollama_client.ensure_model_loaded("qwen3-vl:8b")
        For each pair:
          Extract service mode → structured dict
          Extract speedtest → structured dict
          Detect connection mode
        ollama_client.unload_model("qwen3-vl:8b")
        Verify unloaded via get_loaded_models() == []

      Phase 3 — CIQ Correlation:
        ciq_reader.load(ciq_path)
        For each extracted cell:
          Match to CIQ by EARFCN/ARFCN/PCI
          Get bandwidth, MIMO config, radio type

      Phase 4 — Threshold Check:
        threshold_engine.load_thresholds()
        For each cell:
          check_service_mode() for RF params
          check_speed_test() using 5-dimensional lookup
          Generate comment (PASS/FAIL with delta)

      Phase 5 — Knowledge Analysis (gpt-oss:20b):
        ollama_client.ensure_model_loaded("gpt-oss:20b")
        For each cell:
          analysis_engine.analyze_cell() → observations, recommendations, kpi_impact
        ollama_client.unload_model("gpt-oss:20b")

      Phase 6 — Output Generation:
        site_id = extract from site_folder name
        output_xlsx.generate(results, threshold_data, output_dir/f"{site_id}_Output.xlsx")
        output_docx.generate(results, site_config, analysis_data, output_dir/f"{site_id}_RF_Throughput_Analysis.docx")
        Print: "✅ Output saved to {output_dir}"
        Print: "   {site_id}_Output.xlsx ({N} rows)"
        Print: "   {site_id}_RF_Throughput_Analysis.docx"

=== def main() ===
  Parse args. Initialize DASValidator. Run pipeline.
  Wrap in try/except for clean error messages.
  Print timing summary at end.

Test: python code/main.py --help (should print usage without errors)
Test: python code/main.py --site-folder ./data/SFY0803A --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx --dry-run
```

---

## Prompt 10: Tests + Validation

```
Implement comprehensive tests in tests/ and run a full dry-run validation.

=== tests/test_screenshot_parser.py ===
  - test_parse_service_mode_valid_json: Mock VLM response, verify JSON extraction
  - test_detect_connection_mode_lte_only: No NR fields → "LTE Only"
  - test_detect_connection_mode_endc: NR_SB_Status="LTE+NR" → "EN-DC"
  - test_detect_connection_mode_nr_sa: NR_SB_Status="NR only" → "NR SA"
  - test_detect_connection_mode_nrdc: Dual NR carriers → "NR-DC"
  - test_sanitize_thinking_tags: "<think>stuff</think>{json}" → "{json}"
  - test_sanitize_markdown_fences: "```json\n{}\n```" → "{}"
  - test_base64_encoding: Verify image encoded as base64, not file path

=== tests/test_ciq_reader.py ===
  - test_load_eutran_parameters: Load actual CIQ, verify 6 LTE cells
  - test_load_gutran_cells: Load actual CIQ, verify 16 NR cells
  - test_bandwidth_conversion: 20000 kHz → 20.0 MHz, 100000 → 100.0 MHz
  - test_mimo_detection: noOfTxAntennas 1→SISO, 2→MIMO
  - test_match_by_earfcn: Find cell by EARFCN
  - test_match_by_pci: Find cell by PCI

=== tests/test_threshold_engine.py ===
  - test_load_siso_16_rows: Verify SISO sheet has 16 BW combos
  - test_load_mimo_16_rows: Verify MIMO sheet has 16 BW combos
  - test_service_mode_pass: RSRP=-50, SINR=28, RSRQ=-5 → PASS
  - test_service_mode_fail_rsrp: RSRP=-80 → FAIL
  - test_speed_test_siso_lte_20mhz: Correct row found
  - test_speed_test_mimo_endc: EN-DC DL column used
  - test_dl_pass_above_min: measured > min → PASS
  - test_dl_fail_below_min: measured < min → FAIL
  - test_progressive_ul_sinr: SINR=22 → correct UL threshold
  - test_connection_mode_column_mapping: Each mode maps to correct DL column

=== tests/test_knowledge_engine.py ===
  - test_classify_rsrp_excellent: RSRP=-45 → "Excellent"
  - test_classify_sinr_poor: SINR=3 → "Poor"
  - test_kpi_impacts_low_rsrp: RSRP=-80 → multiple KPI impacts
  - test_throughput_peak_lookup: LTE MIMO 20MHz → correct peak values
  - test_no_impacts_when_all_pass: Good values → minimal/empty impacts

=== Run everything ===
  pytest tests/ -v --tb=short

=== Dry run validation ===
  python code/main.py --site-folder ./data/SFY0803A --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx --dry-run --verbose

Verify:
  1. qwen3-vl:8b loads, processes 2 screenshot pairs, unloads
  2. CIQ reads 6 LTE + 16 NR cells
  3. Threshold lookup finds correct rows
  4. gpt-oss:20b loads, generates 2 sets of observations/recommendations/KPI, unloads
  5. Output.xlsx has 2 rows in Tab 1, threshold tables in Tab 2
  6. RF_Throughput_Analysis.docx generates with all sections
```
