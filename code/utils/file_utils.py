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

# Fallback: infer technology from the tech token in the filename
# (used when screenshot is in sector root, not a tech subfolder)
FILENAME_TECH_MAP = {
    "LTE": {"tech": "LTE", "band": "LTE"},
    "NR": {"tech": "NR", "band": "NR"},
    "N41": {"tech": "NR", "band": "n41"},
    "N25": {"tech": "NR", "band": "n25"},
    "N2500": {"tech": "NR", "band": "n25"},
    "B2": {"tech": "LTE", "band": "B2"},
    "B4": {"tech": "LTE", "band": "B4"},
    "B12": {"tech": "LTE", "band": "B12"},
    "B66": {"tech": "LTE", "band": "B66"},
    "B19": {"tech": "LTE", "band": "B19"},
    "B21": {"tech": "LTE", "band": "B21"},
    # Short band codes from subfolders / filenames (e.g. LAY2301A_Alpha_L19_...)
    "L19": {"tech": "LTE", "band": "B19"},
    "L21": {"tech": "LTE", "band": "B21"},
    "N19": {"tech": "NR", "band": "n19"},
    # Freq-based naming from filenames (e.g. 07_L1900_...)
    "L1900": {"tech": "LTE", "band": "L19"},
    "L2100": {"tech": "LTE", "band": "L21"},
    "N1900": {"tech": "NR", "band": "N19"},
    # Multi-part tech from filenames — underscore variants (e.g. 13_N2500_C1_NSA_...)
    "N2500_C1_NSA": {"tech": "NR", "band": "n25_C1", "mode": "NSA"},
    "N2500_C1_SA": {"tech": "NR", "band": "n25_C1", "mode": "SA"},
    "N2500_C2_NSA": {"tech": "NR", "band": "n25_C2", "mode": "NSA"},
    "N2500_C2_SA": {"tech": "NR", "band": "n25_C2", "mode": "SA"},
    # Multi-part tech — hyphen variants (e.g. LAY2301A_Alpha_N25-C1_NSA_...)
    "N25-C1_NSA": {"tech": "NR", "band": "n25_C1", "mode": "NSA"},
    "N25-C1_SA": {"tech": "NR", "band": "n25_C1", "mode": "SA"},
    "N25-C2_NSA": {"tech": "NR", "band": "n25_C2", "mode": "NSA"},
    "N25-C2_SA": {"tech": "NR", "band": "n25_C2", "mode": "SA"},
}

# Named sector aliases (e.g. Alpha→1, Beta→2, Gamma→3)
_SECTOR_NAME_MAP = {
    "alpha": 1,
    "beta": 2,
    "gamma": 3,
    "delta": 4,
    "epsilon": 5,
    "zeta": 6,
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
    elif lower.endswith("service mode"):
        screenshot_type = "service_mode"
        remainder = stem[: -len("Service mode")].rstrip("_")
    elif lower.endswith("service"):
        screenshot_type = "service_mode"
        remainder = stem[: -len("Service")].rstrip("_")
    elif lower.endswith("speedtest"):
        screenshot_type = "speedtest"
        remainder = stem[: -len("Speedtest")].rstrip("_")
    elif lower.endswith("speed"):
        screenshot_type = "speedtest"
        remainder = stem[: -len("Speed")].rstrip("_")
    elif lower.endswith("gallery"):
        screenshot_type = "service_mode"
        remainder = stem[: -len("Gallery")].rstrip("_")
    else:
        logger.debug("Unrecognized screenshot type in filename: %s", filename)
        return None

    # Split remaining: cell_id_tech_YYYYMMDD_HHMMSS
    # cell_id is always the leading numeric part(s), tech is everything between
    # cell_id and the date/time suffix.
    parts = remainder.split("_")
    if len(parts) < 2:
        logger.debug("Not enough parts in filename: %s", filename)
        return None

    # Try to find date_time at the end of parts.
    # Look for a YYYYMMDD pattern to locate the date position.
    date_idx = None
    for idx in range(len(parts) - 1, 0, -1):
        if re.fullmatch(r'\d{8}', parts[idx - 1]) and re.fullmatch(r'\d{6}', parts[idx]):
            date_idx = idx - 1
            break

    if date_idx is not None:
        date_str = parts[date_idx]
        time_str = parts[date_idx + 1]
        prefix_parts = parts[:date_idx]
    else:
        # No date/time in filename — use a synthetic timestamp based on filename hash
        # to enable pairing (screenshots without timestamps pair by group proximity)
        date_str = None
        time_str = None
        prefix_parts = parts

    sector_name = None
    if prefix_parts[0].isdigit():
        # e.g. ['13', 'N2500', 'C1', 'NSA'] → cell_id='13', tech='N2500_C1_NSA'
        # e.g. ['07', 'L1900'] → cell_id='07', tech='L1900'
        cell_id = prefix_parts[0]
        tech = "_".join(prefix_parts[1:]) if len(prefix_parts) > 1 else ""
    elif len(prefix_parts) >= 3 and prefix_parts[1].lower() in _SECTOR_NAME_MAP:
        # Named-sector format: ['LAY2301A', 'Alpha', 'L19'] or
        # ['LAY2301A', 'Alpha', 'N25-C1', 'NSA']
        cell_id = prefix_parts[0]
        sector_name = prefix_parts[1]
        tech = "_".join(prefix_parts[2:]) if len(prefix_parts) > 2 else ""
    else:
        # e.g. ['CELL01', 'LTE'] → cell_id='CELL01', tech='LTE'
        tech = prefix_parts[-1] if len(prefix_parts) > 1 else ""
        cell_id = "_".join(prefix_parts[:-1]) if len(prefix_parts) > 1 else prefix_parts[0]

    if date_str and time_str:
        try:
            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
        except ValueError:
            logger.debug("Could not parse date/time from filename: %s", filename)
            return None
    else:
        # No timestamp — use hash to give a stable but unique time for pairing
        _h = abs(hash(stem)) % 86400
        dt = datetime(2000, 1, 1, _h // 3600, (_h % 3600) // 60, _h % 60)
        logger.debug("No timestamp in filename, using synthetic datetime: %s", filename)

    return {
        "cell_id": cell_id,
        "tech": tech,
        "date": date_str,
        "time": time_str,
        "screenshot_type": screenshot_type,
        "datetime": dt,
        "sector_name": sector_name,
    }


def discover_screenshots(
    site_folder: str | Path,
    extensions: list[str] | None = None,
) -> list[dict]:
    """Recursively discover all screenshot image files in a site folder.

    Args:
        site_folder: Root path to the site folder (e.g., ./SFY0803A)
        extensions: List of file extensions to scan (e.g., [".jpg", ".jpeg", ".png"]).
                    Defaults to [".jpg", ".jpeg", ".png"].

    Returns:
        List of dicts: [{path, sector, tech_subfolder, tech_info, filename,
                         screenshot_type, parsed}, ...]
        sorted by (sector, tech_subfolder, datetime)
    """
    if extensions is None:
        extensions = [".jpg", ".jpeg", ".png"]

    site_folder = Path(site_folder)
    if not site_folder.is_dir():
        raise FileNotFoundError(f"Site folder not found: {site_folder}")

    results = []
    for ext in extensions:
        pattern = f"*{ext}"
        for jpg in site_folder.rglob(pattern):
            # Skip Windows Zone.Identifier alternate data stream files
            if ":Zone.Identifier" in str(jpg) or jpg.name.endswith(":Zone.Identifier"):
                continue
            parsed = parse_screenshot_filename(jpg.name)
            if parsed is None:
                logger.debug("Skipping non-screenshot file: %s", jpg)
                continue

            sector = resolve_sector_number(jpg)

            # Fallback: infer sector from filename (e.g. "Alpha" → 1)
            if sector is None and parsed.get("sector_name"):
                sector = _SECTOR_NAME_MAP.get(parsed["sector_name"].lower())
                if sector:
                    logger.debug("Inferred sector %d from filename token '%s'",
                                 sector, parsed["sector_name"])

            # Determine tech subfolder: check if immediate parent matches a known pattern
            tech_subfolder = None
            tech_info = None
            parent_name = jpg.parent.name
            if parent_name in TECH_SUBFOLDER_PATTERNS:
                tech_subfolder = parent_name
                tech_info = TECH_SUBFOLDER_PATTERNS[parent_name]
            elif parsed.get("tech"):
                # Fallback: infer tech from filename token when not in a tech subfolder
                tech_token = parsed["tech"]
                fallback = FILENAME_TECH_MAP.get(tech_token) or FILENAME_TECH_MAP.get(tech_token.upper())
                if fallback:
                    tech_info = fallback
                    # Use filename tech as subfolder display name (e.g. "L1900", "N2500_C1_NSA")
                    tech_subfolder = tech_token
                    logger.debug("Inferred tech from filename token '%s': %s", tech_token, fallback)

            results.append({
                "path": jpg,
                "sector": sector,
                "sector_name": parsed.get("sector_name"),
                "tech_subfolder": tech_subfolder,
                "tech_info": tech_info,
                "filename": jpg.name,
                "screenshot_type": parsed["screenshot_type"],
                "parsed": parsed,
            })

    # Deduplicate: if same filename exists in a tech subfolder AND sector root,
    # keep the subfolder version (has proper tech_subfolder from TECH_SUBFOLDER_PATTERNS)
    seen: dict[tuple, int] = {}  # (sector, filename) → index in results
    deduped = []
    for r in results:
        key = (r["sector"], r["filename"])
        in_subfolder = r["path"].parent.name in TECH_SUBFOLDER_PATTERNS
        if key in seen:
            prev_idx = seen[key]
            prev_in_subfolder = deduped[prev_idx]["path"].parent.name in TECH_SUBFOLDER_PATTERNS
            if in_subfolder and not prev_in_subfolder:
                # Replace root version with subfolder version
                deduped[prev_idx] = r
                logger.debug("Dedup: kept subfolder version of %s", r["filename"])
            else:
                logger.debug("Dedup: skipped duplicate %s", r["path"])
        else:
            seen[key] = len(deduped)
            deduped.append(r)
    if len(deduped) < len(results):
        logger.info("Deduplicated %d screenshots (same file in root + subfolder)", len(results) - len(deduped))
    results = deduped

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
        group_unmatched_sm = []

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
                duration = abs((st["parsed"]["datetime"] - sm_dt).total_seconds())
                if (st["parsed"]["datetime"] - sm_dt).total_seconds() < 0:
                    logger.debug("Negative SM-ST duration for %s — screenshots may be in reverse order", sm["parsed"]["cell_id"])
                pairs.append({
                    "service_mode": sm,
                    "speedtest": st,
                    "duration_sec": int(duration),
                    "sector": sector,
                    "sector_name": sm.get("sector_name"),
                    "tech_subfolder": tech_sub,
                    "tech_info": sm.get("tech_info"),
                    "cell_id": sm["parsed"]["cell_id"],
                })
            else:
                group_unmatched_sm.append(sm)

        group_unmatched_st = [st_list[i] for i in range(len(st_list)) if i not in used_st]

        # Second pass: force-pair remaining SM/ST in the same group.
        # The (sector, tech_subfolder) grouping already guarantees they belong to
        # the same cell test — timestamps may be missing or synthetic.
        used_force_st = set()
        for sm in group_unmatched_sm:
            if not group_unmatched_st:
                break
            # Pick closest available ST (or just the first if timestamps are synthetic)
            sm_dt = sm["parsed"]["datetime"]
            best_idx, best_st_item, best_gap = None, None, float("inf")
            for j, st in enumerate(group_unmatched_st):
                if j in used_force_st:
                    continue
                gap = abs((st["parsed"]["datetime"] - sm_dt).total_seconds())
                if gap < best_gap:
                    best_gap = gap
                    best_idx = j
                    best_st_item = st
            if best_st_item is not None:
                used_force_st.add(best_idx)
                logger.info("Force-paired by group (%s/%s): %s + %s (gap=%.0fs)",
                            sector, tech_sub, sm["filename"], best_st_item["filename"], best_gap)
                pairs.append({
                    "service_mode": sm,
                    "speedtest": best_st_item,
                    "duration_sec": "",  # unknown — timestamps missing or unreliable
                    "sector": sector,
                    "sector_name": sm.get("sector_name"),
                    "tech_subfolder": tech_sub,
                    "tech_info": sm.get("tech_info"),
                    "cell_id": sm["parsed"]["cell_id"],
                })
            else:
                unmatched_sm.append(sm)

        for j, st in enumerate(group_unmatched_st):
            if j not in used_force_st:
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
