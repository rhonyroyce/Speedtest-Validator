# Architecture

## System Overview

Speedtest-Validator is a 6-phase pipeline that processes DAS site validation screenshots through two Ollama LLMs under a 16 GB VRAM constraint.

## Pipeline Phases

### Phase 1: Screenshot Discovery
- Recursive scan of site folder for .jpg files
- Filename parsing: `{cell_id}_{tech}_{date}_{time}_{type}.jpg`
- Timestamp-based pairing of Service Mode + Speedtest (within 4 min)
- SM-ST Duration calculation

### Phase 2: VLM Extraction (qwen3-vl:8b, ~5 GB VRAM)
- Base64 encode each screenshot
- Ollama /api/chat with vision prompt templates
- JSON schema validation + retry (max 3 attempts)
- Connection mode auto-detection from Samsung Service Mode fields
- **Unload model after ALL screenshots processed**

### Phase 3: CIQ Correlation
- Load CIQ Excel (eUtran Parameters + gUtranCell sheets)
- Match by EARFCN/ARFCN/PCI
- Extract BW (kHz→MHz), MIMO config, radio type

### Phase 4: Threshold Check
- Load DAS_Validation_Thresholds.xlsx at runtime (never hardcoded)
- 5-dimensional lookup: SISO/MIMO × BW LTE × BW NR C1 × BW NR C2 × Connection Mode
- Service Mode: simple range check (RSRP, SINR, RSRQ, TX Power)
- Speed Test: multi-column DL/UL with Progressive UL at 8 SINR levels

### Phase 5: Knowledge Analysis (gpt-oss:20b, ~12 GB VRAM)
- Build context from 4 knowledge modules (rf_parameters, throughput_benchmarks, kpi_mappings, mop_thresholds)
- Generate Observations, Recommendations, KPI Impact via structured prompts
- **Unload model after ALL analysis complete**

### Phase 6: Output Generation
- Output.xlsx: 16 columns + Tab 2 threshold reference
- RF_Throughput_Analysis.docx: executive summary, deep dives, KPI correlation

## Module Dependency Graph

```
main.py
├── config.py (loads config.yaml)
├── ollama_client.py (Ollama API, model load/unload)
├── screenshot_parser.py (VLM extraction)
│   └── utils/file_utils.py (discovery, pairing)
│   └── utils/text_utils.py (LLM output sanitization)
├── ciq_reader.py (CIQ Excel parsing)
│   └── utils/excel_utils.py (openpyxl helpers)
├── threshold_engine.py (pass/fail determination)
│   └── knowledge/mop_thresholds.py (Excel loader)
├── knowledge_engine.py (unified query interface)
│   ├── knowledge/rf_parameters.py
│   ├── knowledge/throughput_benchmarks.py
│   ├── knowledge/kpi_mappings.py
│   └── knowledge/mop_thresholds.py
├── analysis_engine.py (gpt-oss:20b prompt orchestration)
├── output_xlsx.py (16-column Excel generation)
└── output_docx.py (Word document generation)
```

## VRAM Management

Sequential model loading is critical. The pipeline enforces:
1. Load qwen3-vl:8b → process ALL screenshots → unload via `POST /api/generate {"model": "qwen3-vl:8b", "keep_alive": 0}`
2. Verify unloaded via `GET /api/ps` (0 models running)
3. Load gpt-oss:20b → generate ALL analysis → unload

## Knowledge Base Design

Direct structured extraction via Python dicts — NOT RAG/vector DB:
- ~200 finite RF parameter-to-action mappings
- 1ms dict lookup vs ~260ms RAG retrieval
- Zero retrieval risk, no embedding drift
- No additional dependencies (no chromadb, faiss, etc.)
