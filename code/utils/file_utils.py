"""File utilities — path resolution, screenshot discovery, filename parsing.

Handles the site folder structure:
  SITE_FOLDER/SECTOR X/{tech_subfolder}/
  ├── L19/   ├── L21/   ├── N19/   ├── N2500_C1 NSA/   ├── N2500_C1 SA/   ├── N2500_C2 NSA/

Screenshot naming convention:
  {cell_id}_{tech}_{date}_{time}_{type}.jpg
  Types: "Service mode RIL" or "Speedtest"

Implementation: Claude Code Prompt 3 (Screenshot Parser) — shared utility
"""
from pathlib import Path
from datetime import datetime


# Technology subfolder patterns
TECH_SUBFOLDER_PATTERNS = {
    "L19": {"tech": "LTE", "band": "B19"},
    "L21": {"tech": "LTE", "band": "B21"},
    "N19": {"tech": "NR", "band": "n19"},
    "N2500_C1 NSA": {"tech": "NR", "band": "n41_C1", "mode": "NSA"},
    "N2500_C1 SA": {"tech": "NR", "band": "n41_C1", "mode": "SA"},
    "N2500_C2 NSA": {"tech": "NR", "band": "n41_C2", "mode": "NSA"},
    "N2500_C2 SA": {"tech": "NR", "band": "n41_C2", "mode": "SA"},
}


def discover_screenshots(site_folder: str | Path) -> list[dict]:
    """Recursively discover all screenshot .jpg files in a site folder.

    Args:
        site_folder: Root path to the site folder (e.g., ./SFY0803A)

    Returns:
        List of dicts: [{path, sector, tech_subfolder, filename, type}, ...]
        where type is "service_mode" or "speedtest"
    """
    # TODO: Implement recursive discovery
    # - Walk site_folder recursively for .jpg files
    # - Parse parent directories → sector number, tech subfolder
    # - Check if file is in sector root (no tech subfolder) or tech subfolder
    # - Determine screenshot type from filename ("Service mode RIL" vs "Speedtest")
    # - Return sorted list by (sector, tech, timestamp)
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def parse_screenshot_filename(filename: str) -> dict | None:
    """Parse a screenshot filename into structured components.

    Expected format: {cell_id}_{tech}_{date}_{time}_{type}.jpg

    Args:
        filename: Screenshot filename (without path)

    Returns:
        Dict with keys: cell_id, tech, date, time, type, datetime
        or None if filename doesn't match expected pattern
    """
    # TODO: Implement filename parsing
    # - Split by '_'
    # - Extract cell_id, tech, date (YYYYMMDD), time (HHMMSS), type
    # - Parse date+time into datetime object
    # - Return structured dict
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def pair_screenshots(screenshots: list[dict], max_gap_seconds: int = 240) -> list[dict]:
    """Pair Service Mode and Speedtest screenshots by timestamp proximity.

    Args:
        screenshots: List of screenshot dicts from discover_screenshots()
        max_gap_seconds: Maximum time gap for pairing (default: 4 minutes = 240s)

    Returns:
        List of pair dicts: [{service_mode: path, speedtest: path, duration_sec: int, ...}, ...]
    """
    # TODO: Implement timestamp-based pairing
    # - Group by (sector, tech_subfolder)
    # - Within each group, sort by datetime
    # - Match each service_mode with nearest speedtest within max_gap_seconds
    # - Calculate SM-ST Duration = speedtest_time - service_mode_time
    # - Warn on unmatched screenshots
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def resolve_sector_number(path: Path) -> int | None:
    """Extract sector number from a path containing 'SECTOR X' or 'Sector X'."""
    # TODO: Implement regex extraction of sector number from path
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def resolve_tech_from_subfolder(subfolder_name: str) -> dict | None:
    """Map a tech subfolder name to technology/band/mode info.

    Args:
        subfolder_name: e.g., "N2500_C1 NSA"

    Returns:
        Dict with tech, band, mode keys, or None if unrecognized
    """
    return TECH_SUBFOLDER_PATTERNS.get(subfolder_name)
