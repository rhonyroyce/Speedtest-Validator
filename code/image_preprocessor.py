"""Image preprocessor — deterministic panel splitting for Samsung screenshots.

Splits Samsung Service Mode and Speedtest screenshots into focused panels,
upscales 2x for better VLM OCR, and returns base64-encoded JPEG panels.

This is deterministic preprocessing, not agentic — no tool calling, no multi-turn.
"""
import base64
import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Samsung screenshot panel layouts (fractional coordinates: x1, y1, x2, y2)
# Coordinates are fractions of image width/height (0.0–1.0).
# Derived from Samsung Galaxy S23 Service Mode RIL layout.
# ---------------------------------------------------------------------------

SM_LAYOUT: dict[str, tuple[float, float, float, float]] = {
    # LTE parameters panel (upper portion)
    "lte_params": (0.0, 0.0, 1.0, 0.45),
    # NR parameters panel (lower portion)
    "nr_params": (0.0, 0.40, 1.0, 0.85),
    # Connection status bar (very top)
    "status_bar": (0.0, 0.0, 1.0, 0.08),
    # Full image fallback (always included)
    "full": (0.0, 0.0, 1.0, 1.0),
}

ST_LAYOUT: dict[str, tuple[float, float, float, float]] = {
    # Speed gauge / result area (upper half)
    "results": (0.0, 0.05, 1.0, 0.55),
    # Detail metrics: ping, jitter, packet loss (lower half)
    "details": (0.0, 0.50, 1.0, 0.90),
    # Server info / ISP line (bottom)
    "server_info": (0.0, 0.85, 1.0, 1.0),
    # Full image fallback
    "full": (0.0, 0.0, 1.0, 1.0),
}


def split_panels(
    image_path: str | Path,
    layout: dict[str, tuple[float, float, float, float]],
    upscale_factor: int = 2,
    max_dimension: int = 1024,
    jpeg_quality: int = 90,
) -> dict[str, str]:
    """Split an image into panels and return base64-encoded JPEGs.

    Args:
        image_path: Path to the screenshot image file.
        layout: Panel layout dict mapping panel names to fractional (x1, y1, x2, y2).
        upscale_factor: Upscale multiplier for cropped panels (default 2x).
        max_dimension: Cap longest edge after upscale (default 1024px, matches VLM input).
        jpeg_quality: JPEG compression quality (default 90).

    Returns:
        Dict mapping panel_name → base64-encoded JPEG string.

    Raises:
        FileNotFoundError: If image_path does not exist.
        ValueError: If image cannot be opened.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")

    try:
        img = Image.open(path)
    except Exception as exc:
        raise ValueError(f"Cannot open image {path}: {exc}") from exc

    # Convert to RGB if needed
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    width, height = img.size
    panels: dict[str, str] = {}

    for panel_name, (x1_frac, y1_frac, x2_frac, y2_frac) in layout.items():
        # Convert fractional coords to pixel coords
        x1 = int(x1_frac * width)
        y1 = int(y1_frac * height)
        x2 = int(x2_frac * width)
        y2 = int(y2_frac * height)

        # Clamp to image bounds
        x1 = max(0, min(x1, width))
        y1 = max(0, min(y1, height))
        x2 = max(0, min(x2, width))
        y2 = max(0, min(y2, height))

        if x2 <= x1 or y2 <= y1:
            logger.warning("Skipping degenerate panel %s: (%d,%d,%d,%d)", panel_name, x1, y1, x2, y2)
            continue

        cropped = img.crop((x1, y1, x2, y2))

        # Upscale for better OCR, then cap to max_dimension for VLM
        if upscale_factor > 1:
            new_w = cropped.width * upscale_factor
            new_h = cropped.height * upscale_factor
            cropped = cropped.resize((new_w, new_h), Image.LANCZOS)

        if max_dimension and max(cropped.size) > max_dimension:
            cropped.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        # Encode to base64 JPEG
        buffer = io.BytesIO()
        cropped.save(buffer, format="JPEG", quality=jpeg_quality)
        buffer.seek(0)
        panels[panel_name] = base64.b64encode(buffer.read()).decode("utf-8")

    logger.debug("Split %s into %d panels: %s", path.name, len(panels), list(panels.keys()))
    return panels
