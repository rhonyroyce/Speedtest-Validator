"""Throughput benchmark knowledge base — theoretical max/expected by tech, BW, MIMO.

Provides reference throughput expectations for contextualizing measured values.
Used by the analysis engine to generate meaningful Observations and Recommendations.

Implementation: Claude Code Prompt 5 (Knowledge Engine)
"""

# Theoretical peak DL throughput by technology and bandwidth (Mbps)
# Based on 3GPP specifications and T-Mobile DAS deployment experience
THEORETICAL_DL_PEAKS = {
    "LTE": {
        "SISO": {
            5: {"peak": 37.5, "typical_das": 25},     # 5 MHz
            10: {"peak": 75, "typical_das": 55},       # 10 MHz
            15: {"peak": 112.5, "typical_das": 80},    # 15 MHz
            20: {"peak": 150, "typical_das": 110},     # 20 MHz
        },
        "MIMO": {
            5: {"peak": 75, "typical_das": 50},
            10: {"peak": 150, "typical_das": 110},
            15: {"peak": 225, "typical_das": 160},
            20: {"peak": 300, "typical_das": 220},
        },
    },
    "NR": {
        "SISO": {
            5: {"peak": 50, "typical_das": 35},
            10: {"peak": 100, "typical_das": 70},
            15: {"peak": 150, "typical_das": 100},
            20: {"peak": 200, "typical_das": 140},
            30: {"peak": 300, "typical_das": 210},
            40: {"peak": 400, "typical_das": 280},
            50: {"peak": 500, "typical_das": 350},
            60: {"peak": 600, "typical_das": 400},
            80: {"peak": 800, "typical_das": 550},
            90: {"peak": 900, "typical_das": 620},
            100: {"peak": 1000, "typical_das": 700},
        },
        "MIMO": {
            5: {"peak": 100, "typical_das": 70},
            10: {"peak": 200, "typical_das": 140},
            15: {"peak": 300, "typical_das": 200},
            20: {"peak": 400, "typical_das": 280},
            30: {"peak": 600, "typical_das": 420},
            40: {"peak": 800, "typical_das": 560},
            50: {"peak": 1000, "typical_das": 700},
            60: {"peak": 1200, "typical_das": 820},
            80: {"peak": 1600, "typical_das": 1100},
            90: {"peak": 1800, "typical_das": 1250},
            100: {"peak": 2000, "typical_das": 1400},
        },
    },
}

# Theoretical peak UL throughput by technology and bandwidth (Mbps)
THEORETICAL_UL_PEAKS = {
    "LTE": {
        "SISO": {
            5: {"peak": 12.5, "typical_das": 8},
            10: {"peak": 25, "typical_das": 18},
            15: {"peak": 37.5, "typical_das": 25},
            20: {"peak": 50, "typical_das": 35},
        },
        "MIMO": {
            5: {"peak": 12.5, "typical_das": 8},
            10: {"peak": 25, "typical_das": 18},
            15: {"peak": 37.5, "typical_das": 25},
            20: {"peak": 50, "typical_das": 35},
        },
    },
    "NR": {
        "SISO": {
            5: {"peak": 15, "typical_das": 10},
            10: {"peak": 30, "typical_das": 20},
            20: {"peak": 60, "typical_das": 40},
            40: {"peak": 120, "typical_das": 80},
            100: {"peak": 300, "typical_das": 200},
        },
        "MIMO": {
            5: {"peak": 15, "typical_das": 10},
            10: {"peak": 30, "typical_das": 20},
            20: {"peak": 60, "typical_das": 40},
            40: {"peak": 120, "typical_das": 80},
            100: {"peak": 300, "typical_das": 200},
        },
    },
}

# EN-DC aggregated throughput expectations (LTE + NR combined)
ENDC_AGGREGATION_NOTES = {
    "description": "EN-DC DL = LTE DL + NR DL (aggregated at PDCP layer)",
    "typical_efficiency": 0.85,  # ~85% of sum of individual peaks
    "ul_note": "EN-DC UL depends on SINR — use Progressive UL thresholds from DAS_Validation_Thresholds.xlsx",
}

# NR-DC aggregated throughput expectations
NRDC_AGGREGATION_NOTES = {
    "description": "NR-DC DL = NR C1 DL + NR C2 DL (dual NR carrier aggregation)",
    "typical_efficiency": 0.80,  # ~80% of sum of individual peaks
}

# Throughput degradation factors for DAS environments
DAS_DEGRADATION_FACTORS = {
    "splitter_loss": {
        "description": "Signal split across multiple antennas reduces per-antenna power",
        "impact_pct": 3,  # ~3% throughput reduction per 3dB split
    },
    "feeder_loss": {
        "description": "Coaxial cable attenuation increases with frequency and length",
        "impact_pct": 5,  # ~5% for typical 50m run at 2.5 GHz
    },
    "interference": {
        "description": "PCI collision or macro bleed degrades SINR → lower MCS → lower throughput",
        "impact_pct": 15,  # ~15% for moderate interference (SINR drop 5dB)
    },
    "bler": {
        "description": "Block Error Rate > 10% triggers MCS fallback and retransmissions",
        "impact_pct": 20,  # ~20% for BLER ~15%
    },
}


def get_theoretical_peak(tech: str, mimo_config: str, bw_mhz: int, direction: str = "dl") -> dict:
    """Look up theoretical peak and typical DAS throughput.

    Args:
        tech: "LTE" or "NR"
        mimo_config: "SISO" or "MIMO"
        bw_mhz: Bandwidth in MHz
        direction: "dl" or "ul"

    Returns:
        Dict with peak and typical_das values, or None if not found
    """
    # TODO: Implement lookup logic
    # - Select DL or UL table
    # - Navigate tech → mimo_config → bw_mhz
    # - Return {"peak": x, "typical_das": y} or None
    raise NotImplementedError("Implement in Claude Code Prompt 5")


def compute_throughput_efficiency(measured_mbps: float, theoretical_peak: float) -> float:
    """Calculate throughput efficiency as percentage of theoretical peak.

    Args:
        measured_mbps: Measured throughput in Mbps
        theoretical_peak: Theoretical peak for this config

    Returns:
        Efficiency percentage (0-100+)
    """
    if theoretical_peak <= 0:
        return 0.0
    return round((measured_mbps / theoretical_peak) * 100, 1)
