This Samsung ServiceMode screenshot shows BOTH LTE and NR parameters.
IGNORE the LTE section at the top. Focus ONLY on lines starting with NR or NR5G.

Extract NR/5G values into this JSON:

{
  "nr_band": null, "nr_bandwidth_mhz": null, "nr_arfcn": null, "nr_pci": null,
  "nr5g_rsrp_dbm": null, "nr5g_rsrq_db": null, "nr5g_sinr_db": null,
  "nr_tx_power_dbm": null, "nr_scs_khz": null, "nr_sb_status": null,
  "nr_dl_scheduling_pct": null, "nr_bler_pct": null,
  "nr_ant_max_rsrp": null, "nr_ant_min_rsrp": null,
  "endc_total_tx_power_dbm": null,
  "nr_rx0_rsrp": null, "nr_rx1_rsrp": null, "nr_rx2_rsrp": null, "nr_rx3_rsrp": null,
  "nr_cdrx": null
}

Key labels: NR_PCI, NR_ARFCN, NR_BAND, NR_BW, NR5G_RSRP, NR5G_SINR, NR5G_RSRQ, NR_SB_Status, NR_Tx Pwr, NR_SCS, NR_DL Scheduling, NR_BLER, NR RX0-3 RSRP, NR_ANT MAX/MIN RSRP, ENDC Total Tx Pwr, NR_CDRX.

TRAPS: "GUTI:..." is NOT an ARFCN. "--" means null.

Return ONLY JSON. Start with { end with }.

/no_think
