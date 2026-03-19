# Speedtest-Validator

Automated DAS Speed Test Validation for T-Mobile sites. Processes Samsung Service Mode and Speedtest screenshots using Ollama vision-language models, correlates with CIQ engineering parameters, checks against MOP thresholds, and produces validation deliverables.

## Quick Start

1. Install [Ollama](https://ollama.com)
2. Pull the required models:
   ```bash
   ollama pull qwen3-vl:8b     # Vision-language model for screenshot extraction
   ollama pull gpt-oss:20b     # Analysis model for observations/recommendations
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run:
   ```bash
   python code/main.py --site-folder ./SFY0803A \
       --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx \
       --output-dir ./outputs
   ```

## Dry Run (2 screenshots only)

```bash
python code/main.py --site-folder ./SFY0803A \
    --ciq ./input/SFY0803A_MMBB_CIQ_EXPORT_20251118_173752.xlsx \
    --dry-run
```

## Configuration

Edit `config.yaml` to customize:
- Ollama connection and model settings
- VRAM constraint (16 GB single-GPU pipeline)
- Service mode RF thresholds
- Output column definitions

## Pipeline

1. **Screenshot Discovery** — scan site folder for .jpg files, pair Service Mode + Speedtest by timestamp
2. **VLM Extraction** — load qwen3-vl:8b, extract RF parameters from all screenshots, unload
3. **CIQ Correlation** — match extracted cells to CIQ by EARFCN/ARFCN/PCI
4. **Threshold Check** — 5-dimensional lookup (SISO/MIMO × BW LTE × BW NR C1 × BW NR C2 × Connection Mode)
5. **Knowledge Analysis** — load gpt-oss:20b, generate Observations/Recommendations/KPI Impact, unload
6. **Output Generation** — produce Output.xlsx (16 columns + threshold reference tab) and RF_Throughput_Analysis.docx

## Output Deliverables

- **Output.xlsx** — 16-column validation results + Tab 2 threshold reference tables
- **RF_Throughput_Analysis.docx** — comprehensive RF analysis document with executive summary, deep dives, and KPI correlation

## NVIDIA AI Workbench

This project is AI Workbench-compatible. Open it directly in Workbench — the `.project/spec.yaml` configures the container environment automatically.

## Project Structure

```
code/               Source code (git tracked)
code/knowledge/     Structured knowledge base (Python dicts, not RAG)
code/prompts/       LLM prompt templates (.md)
code/utils/         Shared utilities
models/             ML models (Git LFS)
data/               Input data (Git LFS)
data/sample/        Reference sample outputs
data/scratch/       Temporary data (git-ignored)
input/              Reference files — CIQ, MOP, thresholds, knowledge base
outputs/            Generated reports (git-ignored)
tests/              Test suite
docs/               Documentation
```

## GPU / VRAM Constraint

Total VRAM: 16 GB — cannot run qwen3-vl:8b and gpt-oss:20b simultaneously. Pipeline runs in 2 phases with model unloading between them.

## Tests

```bash
pytest tests/ -v
```
