"""RF parameter knowledge base — quality labels, observation rules, threshold context.

Maps RF measurements to human-readable quality assessments and generates
observation text for the Observations column in Output.xlsx.

Implementation: Claude Code Prompt 5 (Knowledge Engine)
"""

# RSRP quality labels and observation rules
RSRP_QUALITY = {
    "excellent": {"range": (-40, 0), "label": "Excellent", "color": "green"},
    "good": {"range": (-75, -40), "label": "Good", "color": "green"},
    "fair": {"range": (-90, -75), "label": "Fair", "color": "yellow"},
    "poor": {"range": (-110, -90), "label": "Poor", "color": "red"},
    "no_signal": {"range": (-140, -110), "label": "No Signal", "color": "red"},
}

# SINR quality labels
SINR_QUALITY = {
    "excellent": {"range": (25, 50), "label": "Excellent", "color": "green"},
    "good": {"range": (15, 25), "label": "Good", "color": "green"},
    "fair": {"range": (5, 15), "label": "Fair", "color": "yellow"},
    "poor": {"range": (-5, 5), "label": "Poor", "color": "red"},
    "very_poor": {"range": (-20, -5), "label": "Very Poor", "color": "red"},
}

# RSRQ quality labels
RSRQ_QUALITY = {
    "excellent": {"range": (-3, 0), "label": "Excellent", "color": "green"},
    "good": {"range": (-7, -3), "label": "Good", "color": "green"},
    "fair": {"range": (-12, -7), "label": "Fair", "color": "yellow"},
    "poor": {"range": (-20, -12), "label": "Poor", "color": "red"},
}

# TX Power observation rules
TX_POWER_RULES = {
    "normal": {"condition": "negative", "label": "Normal (negative TX power)"},
    "elevated": {"condition": "positive", "label": "ELEVATED — UE transmitting at high power, possible coverage issue"},
}

# DAS-specific thresholds (from MOP 2.pdf — Service Mode)
DAS_SERVICE_MODE_THRESHOLDS = {
    "radio_end": {
        "rsrp": {"min": -60, "max": -40, "unit": "dBm"},
        "sinr": {"min": 25, "unit": "dB"},
        "rsrq": {"min": -12, "max": -3, "unit": "dB"},
        "tx_power": {"condition": "always_negative"},
    },
    "antenna_end": {
        "rsrp": {"min": -75, "max": -50, "unit": "dBm"},
        "sinr": {"min": 25, "unit": "dB"},
        "rsrq": {"min": -12, "max": -3, "unit": "dB"},
        "tx_power": {"condition": "always_negative"},
    },
}

# Observation templates keyed by parameter + condition
OBSERVATION_TEMPLATES = {
    "rsrp_excellent": "RSRP {value} dBm — excellent signal strength, well within DAS proximity range.",
    "rsrp_good": "RSRP {value} dBm — good signal, within DAS validation thresholds.",
    "rsrp_fair": "RSRP {value} dBm — marginal signal for DAS environment. May indicate antenna feeder loss or suboptimal positioning.",
    "rsrp_poor": "RSRP {value} dBm — poor signal, below DAS thresholds. Investigate antenna, splitter, or coupler path loss.",
    "sinr_excellent": "SINR {value} dB — excellent radio quality, clean RF environment.",
    "sinr_good": "SINR {value} dB — good quality but below DAS target of 25 dB. Check for interference sources.",
    "sinr_fair": "SINR {value} dB — moderate interference detected. PCI collision or external macro leakage possible.",
    "sinr_poor": "SINR {value} dB — significant interference. Immediate investigation needed: PCI conflict, passive intermod, or macro bleed.",
    "rsrq_good": "RSRQ {value} dB — good resource quality, low cell loading.",
    "rsrq_fair": "RSRQ {value} dB — moderate resource utilization. Monitor during peak hours.",
    "rsrq_poor": "RSRQ {value} dB — poor resource quality. Possible congestion or neighbor cell overlap.",
    "tx_power_normal": "TX Power {value} dBm — negative value confirms adequate DL signal (UE not power-ramping).",
    "tx_power_elevated": "TX Power {value} dBm — POSITIVE TX power indicates UE compensating for weak DL. UL path loss issue.",
    "dl_pass": "DL throughput {value} Mbps — PASS (above {threshold} Mbps minimum for {mode}).",
    "dl_fail": "DL throughput {value} Mbps — FAIL (below {threshold} Mbps minimum for {mode}). Delta: {delta} Mbps.",
    "ul_pass": "UL throughput {value} Mbps — PASS (above {threshold} Mbps minimum).",
    "ul_fail": "UL throughput {value} Mbps — FAIL (below {threshold} Mbps minimum). Delta: {delta} Mbps.",
}

# Connection mode indicators for Samsung Service Mode screenshots
CONNECTION_MODE_INDICATORS = {
    "LTE Only": {
        "detection": "No NR fields present in screenshot",
        "indicators": ["Band", "BW", "EARFCN only", "NR_SB_Status absent or empty"],
    },
    "NR SA": {
        "detection": "NR fields present + no LTE anchor",
        "indicators": ["NR_SB_Status = 'NR only'", "NR_BAND present without ENDC"],
    },
    "EN-DC": {
        "detection": "LTE anchor + NR carrier(s)",
        "indicators": ["NR_SB_Status = 'LTE+NR'", "Both LTE and NR params present"],
    },
    "NR-DC": {
        "detection": "Dual NR carriers, SA mode",
        "indicators": ["Two NR ARFCNs", "NR C1+C2 active without LTE anchor"],
    },
}


def classify_rsrp(value_dbm: float) -> dict:
    """Return quality classification for an RSRP value."""
    for key, info in RSRP_QUALITY.items():
        low, high = info["range"]
        if low <= value_dbm < high:
            return {"quality": key, "label": info["label"], "color": info["color"]}
    return {"quality": "unknown", "label": "Unknown", "color": "gray"}


def classify_sinr(value_db: float) -> dict:
    """Return quality classification for a SINR value."""
    for key, info in SINR_QUALITY.items():
        low, high = info["range"]
        if low <= value_db < high:
            return {"quality": key, "label": info["label"], "color": info["color"]}
    return {"quality": "unknown", "label": "Unknown", "color": "gray"}


def classify_rsrq(value_db: float) -> dict:
    """Return quality classification for an RSRQ value."""
    for key, info in RSRQ_QUALITY.items():
        low, high = info["range"]
        if low <= value_db < high:
            return {"quality": key, "label": info["label"], "color": info["color"]}
    return {"quality": "unknown", "label": "Unknown", "color": "gray"}


def generate_observation(param: str, value: float, **kwargs) -> str:
    """Generate an observation string for a given parameter and value.

    Args:
        param: Parameter name (rsrp, sinr, rsrq, tx_power, dl, ul)
        value: Measured value
        **kwargs: Additional context (threshold, mode, delta)

    Returns:
        Formatted observation string
    """
    # TODO: Implement full observation generation logic
    # - Classify the parameter value
    # - Select appropriate template from OBSERVATION_TEMPLATES
    # - Format with value and any kwargs
    # - Return the formatted observation string
    raise NotImplementedError("Implement in Claude Code Prompt 5")
