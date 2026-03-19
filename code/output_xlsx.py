"""Output Excel generator — creates the 16-column Output.xlsx with threshold reference tab.

Tab 1: Validation Results
  BTS | Tech/Sector | Connection Mode | Bandwidth | PCI | RSRP | RSRQ | SINR |
  UE TX Power | SM-ST Duration | DL Throughput | UL Throughput | Comment (PASS/FAIL) |
  Observations | Recommendations | Impact on KPIs

Tab 2: Threshold Reference (copy of DAS_Validation_Thresholds.xlsx sheets)
  - SISO Speed Test (16 rows)
  - MIMO Speed Test (16 rows)
  - Service Mode Thresholds

Row count is DYNAMIC — depends on (sectors × technologies per sector).

Implementation: Claude Code Prompt 8 (Output Generation)
"""
# TODO: Implement OutputXlsxGenerator class with:
# - __init__(config) — load config, set output path
# - generate(results, threshold_data) — create complete workbook
# - _create_results_tab(ws, results) — write Tab 1 with 16 columns + formatting
# - _create_threshold_tab(ws, threshold_data) — write Tab 2 reference tables
# - _apply_conditional_formatting(ws) — color-code PASS/FAIL, RSRP/SINR ranges
# - _set_column_widths(ws) — auto-size columns for readability
# - _write_header_row(ws) — bold headers with filter
# - _write_data_row(ws, row_num, cell_result) — one row per cell tested
#
# Column definitions (16 columns):
#   A: BTS (site ID)
#   B: Tech/Sector (e.g., "L19/Sector 1")
#   C: Connection Mode (LTE Only / NR SA / EN-DC / NR-DC)
#   D: Bandwidth (e.g., "20 MHz LTE + 100 MHz NR")
#   E: PCI
#   F: RSRP (dBm)
#   G: RSRQ (dB)
#   H: SINR (dB)
#   I: UE TX Power (dBm)
#   J: SM-ST Duration (seconds between Service Mode and Speedtest screenshots)
#   K: DL Throughput (Mbps)
#   L: UL Throughput (Mbps)
#   M: Comment (PASS/FAIL with delta from threshold)
#   N: Observations (from analysis engine)
#   O: Recommendations (from analysis engine)
#   P: Impact on KPIs (from analysis engine)
#
# Dependencies:
#   - openpyxl
#   - code/config.py (for output path, column config)
