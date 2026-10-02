"""TRUSTBATTLE — Member 2 shared numeric helpers.

Small, dependency-light utilities used by the feature extractors, the
anomaly models and the scorer. Pure functions only — no side effects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def finite(x, fill: float = 0.0) -> np.ndarray:
    """Convert input to a float array with NaN/inf replaced by *fill*.

    Args:
        x: Array-like numeric input.
        fill: Replacement value for NaN/±inf.

    Returns:
        np.ndarray of float64 with no NaN/inf.
    """
    return np.nan_to_num(np.asarray(x, dtype=float), nan=fill, posinf=fill, neginf=fill)


def safe_diff(x) -> np.ndarray:
    """First difference with 0 for the first element (length preserved)."""
    a = np.asarray(x, dtype=float)
    if len(a) == 0:
        return a.copy()
    return np.diff(a, prepend=a[:1])


def col(df: pd.DataFrame, name: str, fill: float = 0.0, default=None) -> np.ndarray:
    """Numeric column as a finite float array; constant *default* when missing.

    Args:
        df: Input DataFrame.
        name: Column name.
        fill: Replacement for NaN/inf inside the column.
        default: Value used for every row when the column does not exist.
            Defaults to *fill* when not given.
    """
    if name in df.columns:
        return finite(df[name].to_numpy(dtype=float), fill=fill)
    return np.full(len(df), default if default is not None else fill, dtype=float)


def rolling_stat(values, window: int, stat: str = "mean") -> np.ndarray:
    """Rolling statistic over a 1-D array (centered, min_periods=1, NaN→0).

    Args:
        values: 1-D array-like.
        window: Rolling window size in samples (clamped to >= 1).
        stat: Any pandas rolling method name: mean, std, max, min, median, skew.

    Returns:
        Finite float array of the same length.
    """
    s = pd.Series(np.asarray(values, dtype=float))
    roller = s.rolling(max(int(window), 1), center=True, min_periods=1)
    out = getattr(roller, stat)().to_numpy(dtype=float)
    return finite(out)


def wrap_deg(x) -> np.ndarray:
    """Wrap angles in degrees to (-180, 180]."""
    return (np.asarray(x, dtype=float) + 180.0) % 360.0 - 180.0
