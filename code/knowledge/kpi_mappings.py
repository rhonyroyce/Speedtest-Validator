"""KPI impact knowledge base — RF issue to KPI impact mappings.

Maps observed RF conditions to affected KPIs from the MS2 KPI and Counters framework.
Used to populate the "Impact on KPIs" column in Output.xlsx.

Reference: MS2 KPI and Counters.xlsx (48 NR + 40 LTE KPIs across 6 domains)
Implementation: Claude Code Prompt 5 (Knowledge Engine)
"""

# 6 KPI domains from MS2 framework
KPI_DOMAINS = {
    "AVL": "Availability",
    "ACC": "Accessibility",
    "RET": "Retainability",
    "CAP": "Capacity / Throughput",
    "MOB": "Mobility / Handover",
    "PWR": "Power Control",
}

# RF condition → KPI impact mappings
# Each entry: condition triggers → list of (domain, kpi_name, impact_description)
RF_TO_KPI_MAPPINGS = {
    # === RSRP-related impacts ===
    "low_rsrp": {
        "condition": "RSRP below DAS threshold",
        "trigger": lambda rsrp: rsrp < -75,
        "impacts": [
            ("ACC", "RRC Setup Success Rate", "Weak RSRP reduces RRC connection success, increasing access failures."),
            ("RET", "E-RAB Drop Rate", "Low signal increases risk of bearer drops during active sessions."),
            ("MOB", "Handover Success Rate", "Weak serving cell RSRP triggers premature handovers with lower success rates."),
            ("CAP", "DL User Throughput", "Low RSRP forces lower MCS selection, directly reducing throughput."),
            ("PWR", "UE TX Power", "UE increases TX power to compensate for weak DL, draining battery faster."),
        ],
    },
    # === SINR-related impacts ===
    "low_sinr": {
        "condition": "SINR below 25 dB (DAS target)",
        "trigger": lambda sinr: sinr < 25,
        "impacts": [
            ("CAP", "DL User Throughput", "Low SINR forces conservative MCS, reducing spectral efficiency and throughput."),
            ("CAP", "DL Cell Throughput", "Aggregate cell capacity drops as scheduler assigns fewer PRBs at lower MCS."),
            ("RET", "E-RAB Drop Rate", "SINR degradation during sessions increases BLER, triggering RLC failures."),
            ("CAP", "DL BLER", "Direct correlation: every 3dB SINR drop roughly doubles BLER."),
        ],
    },
    "sinr_interference": {
        "condition": "SINR < 15 dB — likely interference",
        "trigger": lambda sinr: sinr < 15,
        "impacts": [
            ("CAP", "DL BLER", "Severe interference causes persistent high BLER, requiring HARQ retransmissions."),
            ("ACC", "RACH Success Rate", "Interference on PRACH channels reduces random access success."),
            ("RET", "RLF Rate", "Sustained low SINR triggers Radio Link Failure (T310 timer expiry)."),
            ("MOB", "Unnecessary Handovers", "Fluctuating SINR causes ping-pong handovers between DAS and macro."),
        ],
    },
    # === RSRQ-related impacts ===
    "poor_rsrq": {
        "condition": "RSRQ below -12 dB",
        "trigger": lambda rsrq: rsrq < -12,
        "impacts": [
            ("CAP", "PRB Utilization", "High RSRQ degradation indicates heavy cell loading or neighbor interference."),
            ("ACC", "RRC Setup Success Rate", "Poor RSRQ during connection setup may cause RRC rejection."),
            ("CAP", "DL User Throughput", "RSRQ reflects interference-to-signal ratio, correlates with throughput loss."),
        ],
    },
    # === TX Power-related impacts ===
    "high_tx_power": {
        "condition": "UE TX Power is positive (power ramping)",
        "trigger": lambda tx: tx > 0,
        "impacts": [
            ("PWR", "UE Power Headroom", "Positive TX power means UE approaching max transmit power — no headroom."),
            ("CAP", "UL User Throughput", "UL throughput degrades when UE cannot increase power further."),
            ("RET", "UL BLER", "At max power, UL BLER increases as PUSCH quality degrades."),
            ("ACC", "RACH Success Rate", "PRACH at max power in weak coverage → random access failures."),
        ],
    },
    # === Throughput-related impacts ===
    "dl_fail": {
        "condition": "DL throughput below threshold minimum",
        "trigger": lambda delta: delta < 0,  # negative delta = fail
        "impacts": [
            ("CAP", "DL User Throughput", "Direct KPI impact: measured DL below validation threshold."),
            ("CAP", "DL Cell Throughput", "If one UE underperforms, cell-level throughput KPI also affected."),
            ("CAP", "DL Spectral Efficiency", "Low throughput relative to BW indicates poor spectral efficiency."),
        ],
    },
    "ul_fail": {
        "condition": "UL throughput below threshold minimum",
        "trigger": lambda delta: delta < 0,
        "impacts": [
            ("CAP", "UL User Throughput", "Direct KPI impact: measured UL below validation threshold."),
            ("PWR", "UE TX Power Distribution", "UL underperformance often correlates with UE at max TX power."),
            ("RET", "UL BLER", "UL throughput failure may indicate high UL BLER from path loss."),
        ],
    },
    # === BLER-related impacts ===
    "high_bler": {
        "condition": "BLER > 10%",
        "trigger": lambda bler: bler > 10,
        "impacts": [
            ("CAP", "DL User Throughput", "High BLER triggers HARQ retransmissions, reducing effective throughput by ~BLER%."),
            ("CAP", "DL Spectral Efficiency", "Retransmissions waste PRBs, degrading spectral efficiency."),
            ("RET", "RLC Retransmission Rate", "Persistent BLER escalates to RLC retransmissions and potential drops."),
        ],
    },
    # === Connection mode-specific impacts ===
    "endc_imbalance": {
        "condition": "EN-DC with significant LTE/NR throughput imbalance",
        "trigger": None,  # Complex — evaluated by analysis engine
        "impacts": [
            ("CAP", "EN-DC Throughput", "Imbalanced LTE+NR legs reduce aggregation efficiency below 85% theoretical."),
            ("MOB", "SgNB Addition Success", "Poor NR leg SINR prevents stable SgNB addition for EN-DC."),
            ("RET", "SgNB Release Rate", "Frequent NR leg drops if secondary carrier SINR unstable."),
        ],
    },
}

# NR-specific KPI mappings (from MS2 — 48 NR KPIs)
NR_SPECIFIC_KPIS = {
    "beam_management": {
        "kpis": ["SSB Beam Failure Rate", "Beam Switch Success Rate"],
        "trigger": "NR RSRP variance > 6dB across RX chains",
        "impact": "Beam management inefficiency in FR1 DAS (fewer beam options than macro).",
    },
    "ca_efficiency": {
        "kpis": ["CA Activation Rate", "CA Deactivation Rate"],
        "trigger": "NR-DC or EN-DC with one weak carrier",
        "impact": "Frequent SCell activation/deactivation wastes signaling resources.",
    },
}


def get_kpi_impacts(rf_data: dict) -> list[dict]:
    """Evaluate RF measurements against KPI impact rules.

    Args:
        rf_data: Dict with keys like rsrp, sinr, rsrq, tx_power, dl_delta, ul_delta, bler

    Returns:
        List of impact dicts: [{domain, kpi, description}, ...]
    """
    domain_priority = ["AVL", "ACC", "RET", "CAP", "MOB", "PWR"]

    # Map condition keys to rf_data keys
    param_for_condition = {
        "low_rsrp": "rsrp",
        "low_sinr": "sinr",
        "sinr_interference": "sinr",
        "poor_rsrq": "rsrq",
        "high_tx_power": "tx_power",
        "dl_fail": "dl_delta",
        "ul_fail": "ul_delta",
        "high_bler": "bler",
    }

    seen = set()
    impacts = []

    for condition_key, mapping in RF_TO_KPI_MAPPINGS.items():
        trigger = mapping.get("trigger")
        if trigger is None:
            continue

        data_key = param_for_condition.get(condition_key)
        if data_key is None or data_key not in rf_data:
            continue

        value = rf_data[data_key]
        if value is None:
            continue

        try:
            if not trigger(value):
                continue
        except (TypeError, ValueError):
            continue

        for domain, kpi, description in mapping["impacts"]:
            dedup_key = (domain, kpi)
            if dedup_key not in seen:
                seen.add(dedup_key)
                impacts.append({
                    "domain": domain,
                    "kpi": kpi,
                    "description": description,
                })

    impacts.sort(key=lambda x: domain_priority.index(x["domain"])
                 if x["domain"] in domain_priority else 99)
    return impacts


def format_kpi_impact_text(impacts: list[dict]) -> str:
    """Format KPI impacts into a single text string for the Output.xlsx column.

    Args:
        impacts: List of impact dicts from get_kpi_impacts()

    Returns:
        Formatted multi-line string for the 'Impact on KPIs' cell
    """
    if not impacts:
        return ""

    # Group by domain preserving order
    from collections import OrderedDict
    grouped = OrderedDict()
    for imp in impacts:
        domain = imp["domain"]
        if domain not in grouped:
            grouped[domain] = []
        grouped[domain].append(imp)

    lines = []
    for domain, items in grouped.items():
        for item in items:
            lines.append(f"[{domain}] {item['kpi']}: {item['description']}")

    return "\n".join(lines)
