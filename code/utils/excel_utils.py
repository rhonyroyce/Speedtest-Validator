"""Excel utilities — openpyxl helper functions for reading and writing.

Shared utilities for CIQ reading, threshold loading, and output generation.

Implementation: Claude Code Prompt 4 (CIQ Reader) — shared utility
"""
from pathlib import Path
# TODO: import openpyxl when implementing


def read_sheet_as_dicts(
    workbook_path: str | Path,
    sheet_name: str,
    header_row: int = 1,
) -> list[dict]:
    """Read an Excel sheet into a list of dicts (one per row).

    Args:
        workbook_path: Path to .xlsx file
        sheet_name: Sheet name to read
        header_row: Row number containing column headers (1-indexed)

    Returns:
        List of dicts keyed by header names
    """
    # TODO: Implement with openpyxl
    # - Open workbook (read_only=True, data_only=True)
    # - Select sheet by name
    # - Read header row for column names
    # - Read subsequent rows into dicts
    # - Close workbook
    raise NotImplementedError("Implement in Claude Code Prompt 4")


def find_column_index(sheet, column_name: str, header_row: int = 1) -> int | None:
    """Find the column index (0-based) for a given header name.

    Case-insensitive, strips whitespace.

    Args:
        sheet: openpyxl worksheet
        column_name: Column header to find
        header_row: Row number containing headers (1-indexed)

    Returns:
        0-based column index, or None if not found
    """
    # TODO: Implement column lookup
    raise NotImplementedError("Implement in Claude Code Prompt 4")


def convert_bw_khz_to_mhz(bw_khz: int | float) -> float:
    """Convert bandwidth from kHz (CIQ format) to MHz (display format).

    CIQ stores bandwidth in kHz: 20000 = 20 MHz, 100000 = 100 MHz.

    Args:
        bw_khz: Bandwidth in kHz

    Returns:
        Bandwidth in MHz
    """
    return round(bw_khz / 1000, 1)


def safe_float(value, default: float = 0.0) -> float:
    """Safely convert a cell value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default: int = 0) -> int:
    """Safely convert a cell value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default
