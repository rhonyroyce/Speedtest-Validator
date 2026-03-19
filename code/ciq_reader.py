"""CIQ Excel parser — extracts per-cell configuration from eUtran Parameters and gUtranCell sheets.

Key fields: dlChannelBandwidth (kHz→MHz), noOfTxAntennas (SISO/MIMO), earfcnDl, PCI, radioType.

Implementation: Claude Code Prompt 4 (CIQ Reader)
"""
# TODO: Implement CIQReader class with:
# - load_ciq(excel_path) — parse both sheets
# - get_lte_cells() — list of LTE cell configs from eUtran Parameters
# - get_nr_cells() — list of NR cell configs from gUtranCell info
# - get_cell_config(cell_id) — lookup by cell ID or PCI
# - determine_mimo_config(cell) — 1 TX = SISO, 2+ = MIMO
# - get_bw_mhz(cell) — convert kHz to MHz (divide by 1000)
