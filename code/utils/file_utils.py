"""File utilities — path resolution, screenshot discovery, filename parsing.

Handles the site folder structure:
  SITE_FOLDER/SECTOR X/{tech_subfolder}/
  ├── L19/   ├── L21/   ├── N19/   ├── N2500_C1 NSA/   ├── N2500_C1 SA/   ├── N2500_C2 NSA/

Screenshot naming convention:
  {cell_id}_{tech}_{date}_{time}_{type}.jpg
  Types: "Service mode RIL" or "Speedtest"

Implementation: Claude Code Prompt 3 (Screenshot Parser) — shared utility
"""
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

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

_SECTOR_RE = re.compile(r"[Ss][Ee][Cc][Tt][Oo][Rr]\s*(\d+)", re.IGNORECASE)


def resolve_sector_number(path: Path) -> int | None:
    """Extract sector number from a path containing 'SECTOR X' or 'Sector X'."""
    for part in path.parts:
        m = _SECTOR_RE.search(part)
        if m:
            return int(m.group(1))
    return None


def resolve_tech_from_subfolder(subfolder_name: str) -> dict | None:
    """Map a tech subfolder name to technology/band/mode info.

    Args:
        subfolder_name: e.g., "N2500_C1 NSA"

    Returns:
        Dict with tech, band, mode keys, or None if unrecognized
    """
    return TECH_SUBFOLDER_PATTERNS.get(subfolder_name)


def parse_screenshot_filename(filename: str) -> dict | None:
    """Parse a screenshot filename into structured components.

    Expected format: {cell_id}_{tech}_{date}_{time}_{type}.jpg
    Type portion may contain spaces: "Service mode RIL" or "Speedtest"

    Args:
        filename: Screenshot filename (without path)

    Returns:
        Dict with keys: cell_id, tech, date, time, screenshot_type, datetime
        or None if filename doesn't match expected pattern
    """
    stem = Path(filename).stem  # strip .jpg

    # Determine screenshot type from the end of the filename
    screenshot_type = None
    remainder = stem
    lower = stem.lower()
    if lower.endswith("service mode ril"):
        screenshot_type = "service_mode"
        remainder = stem[: -len("Service mode RIL")].rstrip("_")
    elif lower.endswith("speedtest"):
        screenshot_type = "speedtest"
        remainder = stem[: -len("Speedtest")].rstrip("_")
    elif lower.endswith("gallery"):
        screenshot_type = "service_mode"
        remainder = stem[: -len("Gallery")].rstrip("_")
    else:
        logger.debug("Unrecognized screenshot type in filename: %s", filename)
        return None

    # Split remaining: cell_id_tech_YYYYMMDD_HHMMSS
    parts = remainder.split("_")
    if len(parts) < 4:
        logger.debug("Not enough parts in filename: %s", filename)
        return None

    time_str = parts[-1]
    date_str = parts[-2]
    tech = parts[-3]
    cell_id = "_".join(parts[:-3])

    try:
        dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
    except ValueError:
        logger.debug("Could not parse date/time from filename: %s", filename)
        return None

    return {
        "cell_id": cell_id,
        "tech": tech,
        "date": date_str,
        "time": time_str,
        "screenshot_type": screenshot_type,
        "datetime": dt,
    }


def discover_screenshots(site_folder: str | Path) -> list[dict]:
    """Recursively discover all screenshot .jpg files in a site folder.

    Args:
        site_folder: Root path to the site folder (e.g., ./SFY0803A)

    Returns:
        List of dicts: [{path, sector, tech_subfolder, tech_info, filename,
                         screenshot_type, parsed}, ...]
        sorted by (sector, tech_subfolder, datetime)
    """
    site_folder = Path(site_folder)
    if not site_folder.is_dir():
        raise FileNotFoundError(f"Site folder not found: {site_folder}")

    results = []
    for jpg in site_folder.rglob("*.jpg"):
        parsed = parse_screenshot_filename(jpg.name)
        if parsed is None:
            logger.debug("Skipping non-screenshot file: %s", jpg)
            continue

        sector = resolve_sector_number(jpg)

        # Determine tech subfolder: check if immediate parent matches a known pattern
        tech_subfolder = None
        tech_info = None
        parent_name = jpg.parent.name
        if parent_name in TECH_SUBFOLDER_PATTERNS:
            tech_subfolder = parent_name
            tech_info = TECH_SUBFOLDER_PATTERNS[parent_name]

        results.append({
            "path": jpg,
            "sector": sector,
            "tech_subfolder": tech_subfolder,
            "tech_info": tech_info,
            "filename": jpg.name,
            "screenshot_type": parsed["screenshot_type"],
            "parsed": parsed,
        })

    # Sort by sector, tech subfolder, then timestamp
    results.sort(key=lambda r: (
        r["sector"] or 0,
        r["tech_subfolder"] or "",
        r["parsed"]["datetime"],
    ))

    logger.info("Discovered %d screenshots in %s", len(results), site_folder)
    return results


def pair_screenshots(screenshots: list[dict], max_gap_seconds: int = 240) -> list[dict]:
    """Pair Service Mode and Speedtest screenshots by timestamp proximity.

    Args:
        screenshots: List of screenshot dicts from discover_screenshots()
        max_gap_seconds: Maximum time gap for pairing (default: 4 minutes = 240s)

    Returns:
        List of pair dicts: [{service_mode, speedtest, duration_sec, sector,
                              tech_subfolder, tech_info, cell_id}, ...]
    """
    # Group by (sector, tech_subfolder)
    groups: dict[tuple, dict[str, list]] = defaultdict(lambda: {"service_mode": [], "speedtest": []})
    for s in screenshots:
        key = (s["sector"], s["tech_subfolder"])
        groups[key][s["screenshot_type"]].append(s)

    pairs = []
    unmatched_sm = []
    unmatched_st = []

    for (sector, tech_sub), group in groups.items():
        sm_list = sorted(group["service_mode"], key=lambda x: x["parsed"]["datetime"])
        st_list = sorted(group["speedtest"], key=lambda x: x["parsed"]["datetime"])
        used_st = set()

        for sm in sm_list:
            sm_dt = sm["parsed"]["datetime"]
            best_st = None
            best_gap = float("inf")

            for i, st in enumerate(st_list):
                if i in used_st:
                    continue
                gap = abs((st["parsed"]["datetime"] - sm_dt).total_seconds())
                if gap < best_gap:
                    best_gap = gap
                    best_st = (i, st)

            if best_st is not None and best_gap <= max_gap_seconds:
                idx, st = best_st
                used_st.add(idx)
                duration = (st["parsed"]["datetime"] - sm_dt).total_seconds()
                pairs.append({
                    "service_mode": sm,
                    "speedtest": st,
                    "duration_sec": int(duration),
                    "sector": sector,
                    "tech_subfolder": tech_sub,
                    "tech_info": sm.get("tech_info"),
                    "cell_id": sm["parsed"]["cell_id"],
                })
            else:
                unmatched_sm.append(sm)

        for i, st in enumerate(st_list):
            if i not in used_st:
                unmatched_st.append(st)

    if unmatched_sm:
        logger.warning("%d service mode screenshots without matching speedtest: %s",
                       len(unmatched_sm),
                       [s["filename"] for s in unmatched_sm])
    if unmatched_st:
        logger.warning("%d speedtest screenshots without matching service mode: %s",
                       len(unmatched_st),
                       [s["filename"] for s in unmatched_st])

    logger.info("Paired %d screenshot sets (%d unmatched SM, %d unmatched ST)",
                len(pairs), len(unmatched_sm), len(unmatched_st))
    return pairs
