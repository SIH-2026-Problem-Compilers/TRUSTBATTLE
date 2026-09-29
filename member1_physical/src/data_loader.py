"""TRUSTBATTLE — Member 1 data loader.

Loads telemetry datasets produced by Member 4 (data/synthetic/, data/attacks/)
and validates every column of the shared schema (docs/contracts/data_schema.md §1)
before anything touches the feature extraction or models.

Read-only for data folders. Raises SchemaError with a precise message on mismatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

# ---- docs/contracts/data_schema.md §1 (verbatim — do not edit here) ---------
REQUIRED_COLUMNS: Dict[str, str] = {
    "timestamp": "float",
    "sensor_id": "string",
    "latitude": "float",
    "longitude": "float",
    "altitude": "float",
    "velocity": "float",
    "vx": "float",
    "vy": "float",
    "vz": "float",
    "accel_x": "float",
    "accel_y": "float",
    "accel_z": "float",
    "gyro_x": "float",
    "gyro_y": "float",
    "gyro_z": "float",
    "heading": "float",
    "gnss_quality": "float",
    "packet_rate": "float",
    "packet_delay_ms": "float",
    "packet_loss": "float",
    "sequence_number": "int",
    "label": "int",
    "attack_start": "int",
}

VALID_LABELS = {0, 1, 2, 3, 4, 5, 6}
LABEL_NAMES = {
    0: "normal",
    1: "gnss_spoof",
    2: "replay",
    3: "telemetry_manip",
    4: "network_anomaly",
    5: "sensor_malfunction",
    6: "cross_sensor_conflict",
}
GROUND_TRUTH_COLUMNS = ("timestamp", "sensor_id", "label", "attack_start")


class SchemaError(ValueError):
    """Raised when a dataset does not conform to data_schema.md §1."""


def _coerce(value: Union[str, Path]) -> Path:
    """Resolve *value* against the repo root when it is a relative path."""
    p = Path(value)
    if p.is_absolute():
        return p
    return Path(__file__).resolve().parents[2] / p


def _check_types(df: pd.DataFrame, *, context: str) -> None:
    """Validate dtypes/ranges per schema; raise SchemaError with details."""
    problems: List[str] = []

    for col, kind in REQUIRED_COLUMNS.items():
        if col not in df.columns:
            problems.append(f"missing required column '{col}'")
            continue
        s = df[col]
        if kind == "float" and not pd.api.types.is_numeric_dtype(s):
            problems.append(f"'{col}' must be numeric, got dtype {s.dtype}")
        if kind == "int" and not pd.api.types.is_integer_dtype(s):
            problems.append(f"'{col}' must be integer dtype, got {s.dtype}")
        if kind == "string" and not (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
            problems.append(f"'{col}' must be string, got dtype {s.dtype}")

    if problems:
        # Missing-column report is complete; bail out before range checks.
        raise SchemaError(f"{context}: schema mismatch vs data_schema.md §1:\n  - " + "\n  - ".join(problems))

    bad_range: List[str] = []
    for col in ("gnss_quality", "packet_loss"):
        s = df[col]
        n_bad = int(((s < 0) | (s > 1)).sum())
        if n_bad:
            bad_range.append(f"'{col}' has {n_bad} value(s) outside [0, 1]")
    for col in ("label", "attack_start"):
        s = df[col]
        n_nan = int(s.isna().sum())
        if n_nan:
            bad_range.append(f"'{col}' has {n_nan} NaN value(s)")
    if "label" in df.columns:
        unknown = sorted(set(df["label"].dropna().unique()) - VALID_LABELS)
        if unknown:
            bad_range.append(f"'label' has unknown codes {unknown}; valid: {sorted(VALID_LABELS)}")
    if "timestamp" in df.columns and df["timestamp"].isna().any():
        bad_range.append("'timestamp' has NaN value(s)")

    if bad_range:
        raise SchemaError(f"{context}: value-range violations vs data_schema.md §1:\n  - " + "\n  - ".join(bad_range))


def load_data(path: Union[str, Path]) -> pd.DataFrame:
    """Load and schema-validate one telemetry file (parquet or csv).

    Args:
        path: File path, absolute or relative to the repository root.

    Returns:
        Validated DataFrame (one row = one observation, schema v1.0).

    Raises:
        FileNotFoundError: If *path* does not exist.
        SchemaError: On any schema/value violation (missing/renamed column,
            wrong dtype, unknown label code, out-of-range quality/loss, NaN).
    """
    f = _coerce(path)
    if not f.exists():
        raise FileNotFoundError(f"Dataset not found: {f}")
    if f.suffix.lower() == ".parquet":
        df = pd.read_parquet(f)
    elif f.suffix.lower() == ".csv":
        df = pd.read_csv(f)
    else:
        raise SchemaError(f"{f}: unsupported extension '{f.suffix}' (expected .parquet or .csv)")
    df = df.reset_index(drop=True)
    _check_types(df, context=str(f))
    return df


def load_ground_truth(path: Union[str, Path]) -> pd.DataFrame:
    """Load and validate one ``*_ground_truth.csv`` (data_schema.md §5).

    Returns:
        DataFrame with columns timestamp, sensor_id, label, attack_start.
    """
    f = _coerce(path)
    if not f.exists():
        raise FileNotFoundError(f"Ground truth not found: {f}")
    gt = pd.read_csv(f)
    missing = [c for c in GROUND_TRUTH_COLUMNS if c not in gt.columns]
    if missing:
        raise SchemaError(f"{f}: ground truth missing columns {missing} (data_schema.md §5)")
    return gt.reset_index(drop=True)


def find_scenario_pairs(directory: Union[str, Path]) -> List[tuple]:
    """List (scenario.parquet, scenario_ground_truth.csv) pairs in *directory*.

    A pair matches per data_schema.md §5. Parquet files without a ground-truth
    sibling are skipped with a warning printed to stderr.
    """
    d = _coerce(directory)
    if not d.exists():
        return []
    pairs: List[tuple] = []
    for f in sorted(d.glob("*.parquet")):
        if f.stem.endswith("_ground_truth"):
            continue
        gt = f.with_name(f.stem + "_ground_truth.csv")
        if gt.exists():
            pairs.append((f, gt))
        else:
            import sys
            print(f"[data_loader] warning: no ground truth for {f.name}, skipping", file=sys.stderr)
    return pairs


def load_synthetic_directory(directory: Union[str, Path] = "data/synthetic") -> pd.DataFrame:
    """Concatenate all validated telemetry files in a data/synthetic-like dir.

    The result carries a provenance column `source_file` (added here, not part
    of the contract — feature columns defined in features.py are prefixed m1_).
    """
    d = _coerce(directory)
    frames: List[pd.DataFrame] = []
    for f in sorted(list(d.glob("*.parquet")) + list(d.glob("*.csv"))) if d.exists() else []:
        df = load_data(f)
        df["source_file"] = f.name
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No parquet/csv datasets found in {d}")
    return pd.concat(frames, ignore_index=True)


def split_windows(df: pd.DataFrame, window: int = 50) -> List[pd.DataFrame]:
    """Split a validated DataFrame into consecutive windows of *window* rows.

    The last window may be shorter. Used for per-window scoring.
    """
    if window <= 0:
        raise ValueError("window must be a positive integer")
    return [df.iloc[i:i + window] for i in range(0, len(df), window)]


def summarize(df: pd.DataFrame) -> Dict[str, object]:
    """Quick sanity summary: row counts per label and per sensor."""
    out: Dict[str, object] = {
        "rows": int(len(df)),
        "sensors": sorted(df["sensor_id"].dropna().astype(str).unique().tolist()),
    }
    out["labels"] = {LABEL_NAMES.get(int(k), str(k)): int(v) for k, v in df["label"].value_counts().sort_index().items()}
    return out
