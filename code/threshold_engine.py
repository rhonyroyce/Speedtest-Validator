"""Threshold engine — multi-dimensional pass/fail logic from DAS_Validation_Thresholds.xlsx.

Speed test thresholds are a 5-dimensional lookup:
  (1) SISO vs MIMO  (2) BW LTE MHz  (3) BW NR C1 MHz  (4) BW NR C2 MHz  (5) Connection Mode

Loads thresholds from Excel at runtime — NEVER hardcode speed test values.
Service mode thresholds are simple (from config.yaml).

Implementation: Claude Code Prompt 6 (Threshold Engine)
"""
# TODO: Implement ThresholdEngine class with:
# - load_thresholds(excel_path) — load SISO + MIMO sheets into lookup dicts
# - check_service_mode(rsrp, sinr, rsrq, tx_power) — simple pass/fail
# - check_speed_test(dl_mbps, ul_mbps, config, bw_combo, conn_mode, sinr) — multi-dim lookup
# - get_threshold_row(mimo_config, bw_lte, bw_nrc1, bw_nrc2) — find matching row
# - get_dl_threshold(row, conn_mode) — return (min, max) for LTE DL/NR DL/ENDC DL/NRDC DL
# - get_ul_threshold(row, conn_mode, sinr_db) — return min; for ENDC use progressive UL by SINR
# - compute_delta(measured, threshold_min) — measured - min (positive = margin, negative = fail)
