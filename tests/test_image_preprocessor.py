"""Tests for image_preprocessor.py — panel splitting and upscaling.

Tests:
1. test_split_panels_returns_expected_keys — SM layout produces correct panel names
2. test_split_panels_upscale — upscaled panels are larger than original crop
"""
import base64
import io
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.image_preprocessor import SM_LAYOUT, ST_LAYOUT, split_panels


@pytest.fixture
def dummy_image_path():
    """Create a temporary 1080x2400 test image (Samsung phone resolution)."""
    img = Image.new("RGB", (1080, 2400), color=(128, 128, 128))
    # Draw some variation so panels aren't identical
    for y in range(0, 2400, 100):
        for x in range(0, 1080, 100):
            img.putpixel((x, y), (y % 256, x % 256, 50))

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        img.save(f, format="JPEG")
        return Path(f.name)


class TestSplitPanels:
    def test_split_panels_returns_expected_keys(self, dummy_image_path):
        """SM layout should produce lte_params, nr_params, status_bar, full panels."""
        panels = split_panels(dummy_image_path, SM_LAYOUT)
        assert "lte_params" in panels
        assert "nr_params" in panels
        assert "status_bar" in panels
        assert "full" in panels

        # Each panel should be a valid base64 string decodable to JPEG
        for name, b64 in panels.items():
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            assert img.format == "JPEG", f"Panel {name} is not JPEG"
            assert img.width > 0 and img.height > 0

    def test_split_panels_upscale(self, dummy_image_path):
        """2x upscaled panels should be larger than 1x panels (when max_dimension is uncapped)."""
        # Disable max_dimension cap to test pure upscale behavior
        panels_1x = split_panels(dummy_image_path, SM_LAYOUT, upscale_factor=1, max_dimension=0)
        panels_2x = split_panels(dummy_image_path, SM_LAYOUT, upscale_factor=2, max_dimension=0)

        # Compare the lte_params panel sizes
        img_1x = Image.open(io.BytesIO(base64.b64decode(panels_1x["lte_params"])))
        img_2x = Image.open(io.BytesIO(base64.b64decode(panels_2x["lte_params"])))

        assert img_2x.width == img_1x.width * 2
        assert img_2x.height == img_1x.height * 2

    def test_split_panels_respects_max_dimension(self, dummy_image_path):
        """Panels should be capped at max_dimension after upscale."""
        panels = split_panels(dummy_image_path, SM_LAYOUT, upscale_factor=2, max_dimension=512)
        img = Image.open(io.BytesIO(base64.b64decode(panels["lte_params"])))
        assert max(img.size) <= 512
