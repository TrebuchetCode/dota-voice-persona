"""Downsample a WAV file into N normalized amplitude bars for visualization.

Cached by path so we don't reread the file every time the user switches
heroes. Returns a list of floats in [0, 1].
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import numpy as np
    import soundfile as sf
    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


_cache: dict[tuple[str, int], list[float]] = {}


def compute_bars(path: Path, n_bars: int = 64) -> list[float]:
    """Return `n_bars` amplitude values in [0, 1] for the given wav.

    Reads the file with soundfile, splits into `n_bars` equal chunks, takes
    peak abs in each chunk, normalizes to the file's loudest point. Falls
    back to a flat shape if numpy/soundfile aren't available.
    """
    key = (str(path), n_bars)
    if key in _cache:
        return _cache[key]

    if not _AVAILABLE or not path.exists():
        result = [0.35] * n_bars  # flat placeholder
        _cache[key] = result
        return result

    try:
        data, _sr = sf.read(str(path), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if data.size == 0:
            result = [0.0] * n_bars
            _cache[key] = result
            return result

        # Split into chunks, peak-abs per chunk.
        chunk = max(1, data.size // n_bars)
        values: list[float] = []
        for i in range(n_bars):
            slice_ = data[i * chunk : (i + 1) * chunk]
            values.append(float(np.abs(slice_).max()) if slice_.size else 0.0)

        peak = max(values) or 1.0
        result = [max(0.06, v / peak) for v in values]  # 0.06 floor so bars are visible
    except Exception:
        result = [0.35] * n_bars

    _cache[key] = result
    return result
