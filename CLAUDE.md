# Speedtest-Validator — Project Memory

## Overview
Python CLI automating T-Mobile DAS site RF validation by processing Samsung Service Mode and Speedtest screenshots using Ollama vision-language models (see config.yaml). NVIDIA AI Workbench-compatible project.

## Tech Stack
- **Runtime**: Python 3.10+
- **Vision LLM**: see config.yaml `ollama.vision_model` (~5GB VRAM) — screenshot OCR/extraction
- **Analysis LLM**: see config.yaml `ollama.analysis_model` (~12GB VRAM) — observations, recommendations, KPI impact
- **GPU**: Single 16GB VRAM — MUST unload one model before loading the other
- **AI Workbench**: `.project/spec.yaml` v2 — ml-gpu environment (PyTorch base, CUDA 12.2, 1 GPU)
- **Acceleration**: RAPIDS cuDF/cuML optional (auto-detected via `code/utils/gpu_utils.py`)
- **Data**: openpyxl (Excel), python-docx (Word), PyYAML (config)
- **Image**: Pillow (preprocessing), base64 (Ollama API encoding)

## GPU / Model Management (CRITICAL)
- Total VRAM: 16 GB — cannot run both models simultaneously (see config.yaml for model names)
- Pipeline phases:
  1. **Extraction phase**: Load vision model, process ALL screenshots, unload
  2. **Analysis phase**: Load analysis model, generate ALL observations/recommendations/KPI impact, unload
- Unload via: `POST http://localhost:11434/api/generate {"model": "model_name", "keep_alive": 0}`
- Always verify model unloaded before loading next: `GET /api/ps` should show 0 models
- ollama_client.py must implement `unload_model()` and `ensure_model_loaded()` methods

## Architecture
- **Entry point**: `code/main.py`
- **Pipeline**: Screenshot Discovery → VLM Extraction → CIQ Correlation → Threshold Check → Knowledge Analysis → Output Generation
- **Core modules**: main.py, ollama_client.py, screenshot_parser.py, ciq_reader.py, threshold_engine.py, knowledge_engine.py, analysis_engine.py, output_xlsx.py, output_docx.py
- **Knowledge base**: Structured Python dicts (NOT vector DB/RAG) in `code/knowledge/`
- **Causal DAG**: `code/knowledge/causal_dag.json` — 5-tier knowledge graph (T1 Physical → T2 RF → T3 Parameter → T4 Counter → T5 KPI), 123 nodes, 159 edges, 20 mitigation playbooks. Source: `Causal_DAG_Knowledge_Graph_v3.json`. Config: `causal_dag` section in `config.yaml`.
- **Prompts**: Markdown templates in `code/prompts/` (separate for Service Mode vs Speedtest)

## Critical Reference Data

### DAS Validation Thresholds (from MOP 2.pdf)

#### Service Mode Thresholds (simple — same for all techs)
| Parameter | Radio End | Antenna End |
|-----------|-----------|-------------|
| RSRP (dBm) | -60 to -40 | -75 to -50 |
| SINR (dB) | >25 | >25 |
| RSRQ (dB) | -12 to -3 | -12 to -3 |
| TX Power | Always negative | Always negative |

#### Speed Test Thresholds (COMPLEX — multi-dimensional lookup)
- **Reference file**: `DAS_Validation_Thresholds.xlsx` (machine-readable, load with openpyxl)
- **5 lookup dimensions**: (1) SISO vs MIMO, (2) BW LTE MHz, (3) BW NR C1 MHz, (4) BW NR C2 MHz, (5) Connection Mode
- **DL columns**: LTE DL, NR DL, EN-DC DL, NR-DC DL — each has Min/Max range
- **UL columns**: LTE UL, NR UL, EN-DC UL — plus Progressive UL at 8 SINR levels (15/19/20/22/24/26/28/30)
- **16 BW combinations per config** (SISO sheet + MIMO sheet = 32 total rows)
- **PASS**: measured throughput ≥ Min threshold for the matching (config, BW combo, connection mode)
- **threshold_engine.py must load from Excel, NOT hardcode values**

#### Physical Layer Thresholds (from Passing Thresholds.xlsx — now appended to DAS_Validation_Thresholds.xlsx)
Market-specific passing criteria for physical layer / antenna system health:

| Parameter | Band / Equipment | Threshold | Unit |
|-----------|-----------------|-----------|------|
| RSSI Hot | PCS / AWS | > -106 | dBm |
| RSSI Cold | PCS / AWS | < -120 | dBm |
| RSSI Hot | N2500 (n25) | > -109 | dBm |
| RSSI Cold | N2500 (n25) | < -115 | dBm |
| RSSI Target | PCS / AWS (AILG ON) | -114 to -115 | dBm |
| RSSI Target | N2500 (AILG ON) | -110 to -112 | dBm |
| RSSI Imbalance | All bands | < 3 | dB (branch delta) |
| VSWR | RRU 4402 / 2203 | ≤ 2.1 (RL > 9 dB) | ratio |
| VSWR | RRU 8863 | ≤ 1.4 (RL > 16 dB) | ratio |
| Fiber Loss (UL/DL) | All RRUs | +3 to -3 | dB |
| Fiber Rx Power | All RRUs | RXdBm1/RXdBm2 > -5 | dBm |

- **Sheets in DAS_Validation_Thresholds.xlsx**: `Physical Layer Thresholds` (human-readable) + `Physical Thresholds Lookup` (machine-readable with min_value/max_value columns)
- **threshold_engine.py must load these from the `Physical Thresholds Lookup` sheet** — use parameter + band + equipment as composite key

### Connection Mode Detection (CRITICAL — new column in output)
Detect from Samsung Service Mode screenshot fields:
| Connection Mode | Detection Logic | Screenshot Indicators |
|----------------|----------------|----------------------|
| LTE Only | No NR fields present | Band, BW, EARFCN only; NR_SB_Status absent or empty |
| NR SA | NR fields + no LTE anchor | NR_SB_Status = "NR only" or NR_BAND present without ENDC |
| EN-DC (NSA) | LTE anchor + NR carrier(s) | NR_SB_Status = "LTE+NR"; both LTE and NR params present |
| NR-DC | Dual NR carriers, SA mode | Two NR ARFCNs or NR C1+C2 active without LTE anchor |
- **This determines which DL/UL column to use in the threshold lookup**
- VLM extraction prompt MUST ask for connection mode indicators

### CIQ Excel Structure
- **eUtran Parameters sheet**: LTE cells (dlChannelBandwidth, noOfTxAntennas, earfcnDl, PCI)
- **gUtranCell sheet**: NR cells (arfcnDl, noOfTxAntennas, radioType, channelBandwidth)
- **Key unit**: Bandwidth in kHz (20000 = 20 MHz, 100000 = 100 MHz) — convert to MHz for display
- **SISO vs MIMO**: Determined from CIQ `noOfTxAntennas` (1=SISO, 2+=MIMO)

### Site Folder Structure
```
SITE_FOLDER/SECTOR X/{tech_subfolder}/
├── L19/   ├── L21/   ├── N19/   ├── N2500_C1 NSA/   ├── N2500_C1 SA/   ├── N2500_C2 NSA/
```

## Screenshot Convention
- **Format**: `{cell_id}_{tech}_{date}_{time}_{type}.jpg`
- **Types**: "Service mode RIL" or "Speedtest"
- **Pairing**: Match Service Mode + Speedtest by timestamp proximity (within 4 min), calculate SM-ST Duration
- **Note**: Screenshots may be in sector root or tech subfolders

## Output Formats
### Output.xlsx (16 columns + Thresholds reference tab)
BTS | Tech/Sector | Connection Mode | Bandwidth | PCI | RSRP | RSRQ | SINR | UE TX Power | SM-ST Duration | DL Throughput | UL Throughput | Comment (PASS/FAIL) | Observations | Recommendations | Impact on KPIs

- **Tab 1**: Validation results (rows = number of cells tested, varies by site)
- **Tab 2**: Copy of threshold tables from DAS_Validation_Thresholds.xlsx (SISO + MIMO + Service Mode)
- **Connection Mode column**: LTE Only / NR SA / EN-DC / NR-DC (auto-detected from screenshots)
- **Row count is DYNAMIC** — depends on (sectors × technologies per sector), NOT a fixed number

### RF_Throughput_Analysis.docx
- Title page, Executive Summary, Site Configuration table, RF Parameter Deep Dive sections, Summary tables, Glossary
- References: MS2 KPI and Counters.xlsx (48 NR + 40 LTE KPIs across 6 domains)

## Code Conventions
- **Knowledge base**: Structured Python dicts only (not free text), injected directly into prompts
- **Configuration**: All paths, model names, thresholds in `config.yaml` (never hardcode)
- **Thresholds**: Load from `DAS_Validation_Thresholds.xlsx` at runtime — never hardcode speed test thresholds
- **LLM settings**: Temperature 0.1-0.2 for extraction, 0.3 for analysis
- **JSON validation**: Validate all LLM output with schema + retry (max 3 attempts)
- **Image encoding**: Always base64 encode for Ollama `/api/chat` endpoint (not file paths)
- **Sanitization**: Strip thinking tags, markdown fences, Unicode artifacts from LLM output
- **Bandwidth**: Always store/calculate in kHz internally; convert to MHz for display (divide by 1000)

## Build & Run Commands
```bash
# Install
pip install -r requirements.txt

# Process full site
python code/main.py --site-folder ./SFY0803A --ciq ./SFY0803A_MMBB_CIQ_EXPORT_*.xlsx --output-dir ./outputs

# Dry run (2 screenshots only)
python code/main.py --site-folder ./SFY0803A --ciq ./SFY0803A_MMBB_CIQ_EXPORT_*.xlsx --dry-run

# Test
pytest tests/ -v
```

## Common Mistakes to Avoid
- ❌ Don't use RAG/vector DB — knowledge base is finite and structured, use direct dict injection
- ❌ Don't hardcode model names or paths — use config.yaml
- ❌ Don't hardcode speed test thresholds — load from DAS_Validation_Thresholds.xlsx
- ❌ Don't skip JSON validation on LLM output (qwen3-vl:8b ~75% first-pass valid JSON)
- ❌ Don't forget BW conversion: CIQ kHz → divide by 1000 for MHz display
- ❌ Don't assume all sectors have all technologies (Sectors 4-6 may only have NR n41)
- ❌ Don't assume screenshots in fixed subfolders (check sector root too)
- ❌ Don't use same prompt for Service Mode and Speedtest (different layouts)
- ❌ Don't pass file paths to Ollama API — always use base64 encoding
- ❌ Don't hardcode SM-ST Duration calculation — extract from timestamp pairs
- ❌ Don't hardcode screenshot count or output row count — both are site-dependent
- ❌ Don't assume connection mode from folder name alone — detect from screenshot fields (NR_SB_Status, ENDC indicators)
- ❌ Don't use a single DL/UL threshold for all modes — match (SISO/MIMO × BW combo × LTE/NR/ENDC/NRDC)
