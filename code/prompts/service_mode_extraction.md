---
version: "2.0"
model: qwen2.5vl:7b
temperature: 0.15
output_format: json
accuracy_target: 0.85
---

Extract RF parameters from this Samsung ServiceMode screenshot. Read each label and its value carefully.

## Samsung ServiceMode Label → JSON Field Mapping

LTE labels (appear in upper section):
- "LTE RRC:CONN BAND:" → band (integer, e.g. 2, 4, 66)
- "BW:" on same line as BAND → bandwidth_mhz (integer: 5, 10, 15, or 20)
- "Earfcn:" → earfcn (integer, e.g. 650, 2050, 5230. NEVER read from the GUTI line)
- "PCI:" on same line as Earfcn → pci (integer 0-503)
- "RSRP:" → rsrp_dbm (negative number like -55, -72. Range: -140 to -30)
- "RSRQ:" → rsrq_db (negative number like -9, -12. Range: -20 to -3)
- "SNR:" → sinr_db (number like 28.6, 15.2. Range: -20 to 50)
- "Tx Pwr :" → tx_power_dbm (negative number like -25)
- "PCC MIMO Configured:" → mimo_configured
- "UPPERLAYER_IND_R15:" → upperlayer_ind_r15
- "DCNR_RESTRICTION:" → dcnr_restriction

NR labels (appear in lower section, all prefixed "NR" or "NR5G"):
- "NR5G_RSRP :" or "NR-RSRP:" → nr5g_rsrp_dbm (range: -140 to -30)
- "NR5G_SINR :" → nr5g_sinr_db (range: -20 to 50)
- "NR5G_RSRQ:" → nr5g_rsrq_db (range: -20 to -3)
- "NR_ARFCN:" → nr_arfcn (integer like 501390, 386230)
- "NR_PCI:" → nr_pci (integer 0-1007)
- "NR_BAND:" → nr_band (string like "n41", "n25", "n71")
- "NR_BW:" → nr_bandwidth_mhz (integer: 20, 30, 40, 50, 100)
- "NR_SB_Status:" → nr_sb_status (string: "LTE+NR", "NR only", or "--")
- "NR_Tx Pwr:" → nr_tx_power_dbm
- "NR_SCS:" → nr_scs_khz (integer: 15, 30, or 60. NOT "15kHz" or "30kHz")
- "NR_DL Scheduling:" → nr_dl_scheduling_pct
- "NR_BLER:" → nr_bler_pct
- "NR_ANT MAX RSRP:" → nr_ant_max_rsrp
- "NR_ANT MIN RSRP:" → nr_ant_min_rsrp
- "ENDC Total Tx Pwr:" → endc_total_tx_power_dbm
- "NR RX0 RSRP:" → nr_rx0_rsrp
- "NR RX1 RSRP:" → nr_rx1_rsrp
- "NR RX2 RSRP:" → nr_rx2_rsrp
- "NR RX3 RSRP:" → nr_rx3_rsrp
- "NR_CDRX:" → nr_cdrx

## TRAPS — Do NOT extract from these lines

- "GUTI:310-260-1480-94-334da7cd" — This is a GUTI identifier, NOT earfcn/pci/arfcn
- "DEBUG INFO : 0 0 9 121 650" — This is debug data, NOT RF parameters
- "HPLMN(310-260)" — This is a PLMN ID, NOT a band number
- "--" or blank values → return null

## Connection Mode — IMPORTANT

Look at "Serving PLMN" line AND which params have actual numeric values:

- **LTE_ONLY**: "Serving PLMN(...)-LTE" and NO NR fields have numeric values (all NR lines show "--")
- **NR_SA**: "Serving PLMN(...)-NR5G" and NR fields have values but LTE RSRP/RSRQ/SNR are absent or "--". Also: if NR_BAND, NR_ARFCN, NR_PCI all have values but there is no "LTE RRC:CONN BAND" line → NR_SA
- **ENDC**: Both LTE and NR params have numeric values. NR_SB_Status="LTE+NR". "Serving PLMN(...)-LTE" but NR section also populated
- **NRDC**: Two separate NR carriers active without LTE anchor

## Output JSON

{
  "screenshot_type": "service_mode",
  "connection_mode": "LTE_ONLY|NR_SA|ENDC|NRDC",
  "lte_params": {
    "band": null, "bandwidth_mhz": null, "earfcn": null, "pci": null,
    "rsrp_dbm": null, "rsrq_db": null, "sinr_db": null, "tx_power_dbm": null,
    "mimo_configured": null, "upperlayer_ind_r15": null, "dcnr_restriction": null
  },
  "nr_params": {
    "nr_band": null, "nr_bandwidth_mhz": null, "nr_arfcn": null, "nr_pci": null,
    "nr5g_rsrp_dbm": null, "nr5g_rsrq_db": null, "nr5g_sinr_db": null,
    "nr_tx_power_dbm": null, "nr_scs_khz": null, "nr_sb_status": null,
    "nr_dl_scheduling_pct": null, "nr_bler_pct": null,
    "nr_ant_max_rsrp": null, "nr_ant_min_rsrp": null,
    "endc_total_tx_power_dbm": null,
    "nr_rx0_rsrp": null, "nr_rx1_rsrp": null, "nr_rx2_rsrp": null, "nr_rx3_rsrp": null,
    "nr_cdrx": null
  },
  "timestamp": null,
  "confidence": 0.8
}

Return ONLY the JSON. No explanation. Start with { and end with }.

/no_think
