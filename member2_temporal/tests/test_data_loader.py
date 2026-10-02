"""Tests for TASK 1 data loader (schema v1.0 validation)."""

import pandas as pd
import pytest

from member2_temporal.src.data_loader import (
    GROUND_TRUTH_COLUMNS,
    SchemaError,
    load_data,
    load_ground_truth,
    split_windows,
    summarize,
)
from member2_temporal.src.fallback_data import (
    generated_ground_truth,
    make_normal,
    write_generated,
)


def test_load_valid_parquet(tmp_path):
    f = tmp_path / "ok.parquet"
    make_normal(100).to_parquet(f, index=False)
    df = load_data(f)
    assert len(df) == 100
    assert "timestamp" in df.columns


def test_load_valid_csv(tmp_path):
    f = tmp_path / "ok.csv"
    make_normal(50).to_csv(f, index=False)
    df = load_data(f)
    assert len(df) == 50


def test_missing_column_raises(tmp_path):
    f = tmp_path / "bad.parquet"
    make_normal(50).drop(columns=["gnss_quality"]).to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="gnss_quality"):
        load_data(f)


def test_wrong_dtype_raises(tmp_path):
    df = make_normal(50)
    df["sequence_number"] = df["sequence_number"].astype(float)  # schema says int64
    f = tmp_path / "bad.parquet"
    df.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="sequence_number"):
        load_data(f)


def test_unknown_label_raises(tmp_path):
    df = make_normal(50)
    df.loc[df.index[3], "label"] = 9  # not a valid code
    f = tmp_path / "bad.parquet"
    df.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="unknown codes"):
        load_data(f)


def test_out_of_range_raises(tmp_path):
    df = make_normal(50)
    df.loc[df.index[2], "packet_loss"] = 1.5  # outside [0, 1]
    f = tmp_path / "bad.parquet"
    df.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="packet_loss"):
        load_data(f)


def test_nan_timestamp_raises(tmp_path):
    df = make_normal(50)
    df.loc[df.index[1], "timestamp"] = float("nan")
    f = tmp_path / "bad.parquet"
    df.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="timestamp"):
        load_data(f)


def test_unsupported_extension(tmp_path):
    f = tmp_path / "data.xlsx"
    f.write_bytes(b"x")
    with pytest.raises(SchemaError, match="unsupported extension"):
        load_data(f)


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_data("does/not/exist.parquet")


def test_ground_truth_roundtrip(tmp_path):
    df = make_normal(100, seed=1)
    gt = generated_ground_truth(df)
    f = tmp_path / "gt.csv"
    gt.to_csv(f, index=False)
    loaded = load_ground_truth(f)
    assert list(loaded.columns) == list(GROUND_TRUTH_COLUMNS)


def test_split_windows(normal_df):
    windows = split_windows(normal_df, window=50)
    assert len(windows) == 12
    assert len(windows[0]) == 50
    assert len(windows[-1]) == 600 - 11 * 50


def test_summarize(normal_df):
    s = summarize(normal_df)
    assert s["rows"] == 600
    assert s["labels"] == {"normal": 600}
