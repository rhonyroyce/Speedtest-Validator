"""Tests for gpu_utils.py — RAPIDS/pandas fallback and utility functions."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_gpu_utils_fallback_to_pandas():
    """When RAPIDS (cudf) is unavailable, gpu_utils should fall back to pandas."""
    from code.utils import gpu_utils

    # In CI / environments without RAPIDS, cudf is absent → pandas fallback
    assert hasattr(gpu_utils, "RAPIDS_AVAILABLE")
    assert hasattr(gpu_utils, "GPU_BACKEND")

    if not gpu_utils.RAPIDS_AVAILABLE:
        import pandas

        engine = gpu_utils.get_dataframe_engine()
        assert engine is pandas
        assert gpu_utils.GPU_BACKEND == "pandas (CPU)"


def test_gpu_info_returns_dict():
    """gpu_info() always returns a dict with required keys."""
    from code.utils.gpu_utils import gpu_info

    info = gpu_info()
    assert isinstance(info, dict)
    assert "rapids_available" in info
    assert "backend" in info


def test_to_pandas_passthrough():
    """to_pandas() returns a pandas DataFrame unchanged when RAPIDS unavailable."""
    import pandas as pd

    from code.utils.gpu_utils import to_pandas

    df = pd.DataFrame({"a": [1, 2, 3]})
    result = to_pandas(df)
    assert result is df
