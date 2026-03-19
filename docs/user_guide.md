# User Guide

## Prerequisites

- Python 3.10+
- Ollama installed and running (`ollama serve`)
- Models pulled: `qwen3-vl:8b` (5 GB), `gpt-oss:20b` (12 GB)
- NVIDIA GPU with 16+ GB VRAM

## Input Requirements

### Site Folder Structure
```
SFY0803A/
├── SECTOR 1/
│   ├── L19/          (LTE Band 19)
│   ├── L21/          (LTE Band 21)
│   ├── N19/          (NR Band n19)
│   ├── N2500_C1 NSA/ (NR n41 Carrier 1, NSA mode)
│   ├── N2500_C1 SA/  (NR n41 Carrier 1, SA mode)
│   └── N2500_C2 NSA/ (NR n41 Carrier 2, NSA mode)
├── SECTOR 2/
│   └── ...
└── SECTOR 6/
    └── ...
```

### Screenshot Naming Convention
```
{cell_id}_{tech}_{date}_{time}_{type}.jpg
```
- Types: "Service mode RIL" or "Speedtest"
- Date format: YYYYMMDD
- Time format: HHMMSS

### Reference Files (in input/ directory)
- **CIQ Excel**: Site engineering parameters (eUtran Parameters + gUtranCell sheets)
- **DAS Validation MOP 2.pdf**: Pass/fail criteria reference
- **DAS_Validation_Thresholds.xlsx**: Machine-readable thresholds (SISO + MIMO, 16 BW combos each)
- **RF_Throughput_Analysis_Universal_RAG.docx**: RF knowledge base
- **MS2_KPI_and_Counters.xlsx**: KPI reference (48 NR + 40 LTE KPIs)

## Running the Validator

### Full Site Processing
```bash
python code/main.py \
    --site-folder ./SFY0803A \
    --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx \
    --output-dir ./outputs
```

### Dry Run (first 2 screenshot pairs only)
```bash
python code/main.py \
    --site-folder ./SFY0803A \
    --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx \
    --dry-run
```

### Verbose Mode
```bash
python code/main.py \
    --site-folder ./SFY0803A \
    --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx \
    --output-dir ./outputs \
    --verbose
```

## Output Files

### Output.xlsx (16 columns)
| Column | Description |
|--------|-------------|
| BTS | Site ID |
| Tech/Sector | Technology and sector (e.g., L19/Sector 1) |
| Connection Mode | LTE Only / NR SA / EN-DC / NR-DC |
| Bandwidth | Configured BW from CIQ |
| PCI | Physical Cell Identity |
| RSRP | Reference Signal Received Power (dBm) |
| RSRQ | Reference Signal Received Quality (dB) |
| SINR | Signal-to-Interference-plus-Noise Ratio (dB) |
| UE TX Power | User Equipment transmit power (dBm) |
| SM-ST Duration | Time between Service Mode and Speedtest screenshots (seconds) |
| DL Throughput | Downlink speed (Mbps) |
| UL Throughput | Uplink speed (Mbps) |
| Comment | PASS/FAIL with threshold delta |
| Observations | RF analysis observations |
| Recommendations | Actionable recommendations |
| Impact on KPIs | Affected KPI domains and metrics |

Tab 2 contains the threshold reference tables (SISO + MIMO + Service Mode).

### RF_Throughput_Analysis.docx
Comprehensive analysis document with title page, executive summary, site configuration, RF deep dives, summary tables, and glossary.

## Troubleshooting

- **"Model not found"**: Run `ollama pull qwen3-vl:8b` and `ollama pull gpt-oss:20b`
- **VRAM overflow**: Ensure only one model is loaded at a time. Check with `ollama ps`
- **No screenshots found**: Verify site folder structure matches expected pattern
- **JSON parse errors**: The pipeline retries up to 3 times with progressively stricter prompts
