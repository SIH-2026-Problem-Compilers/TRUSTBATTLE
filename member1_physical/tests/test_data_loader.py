"""Tests for the TASK 1 data loader (schema validation)."""

import pandas as pd
import pytest

from member1_physical.src.data_loader import (
    GROUND_TRUTH_COLUMNS,
    SchemaError,
    find_scenario_pairs,
    load_data,
    load_ground_truth,
    split_windows,
)


def test_load_valid_csv(normal_df, tmp_path):
    f = tmp_path / "valid.csv"
    normal_df.to_csv(f, index=False)
    df = load_data(f)
    assert len(df) == len(normal_df)
    assert df["label"].isin([0, 1, 2, 3, 4, 5, 6]).all()
    assert set(GROUND_TRUTH_COLUMNS).issubset(df.columns)


def test_load_valid_parquet(normal_df, tmp_path):
    f = tmp_path / "valid.parquet"
    normal_df.to_parquet(f, index=False)
    df = load_data(f)
    assert len(df) == len(normal_df)
    assert df["sequence_number"].dtype.kind == "i"


def test_missing_column_raises(normal_df, tmp_path):
    bad = normal_df.drop(columns=["altitude"])
    f = tmp_path / "missing.parquet"
    bad.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="altitude"):
        load_data(f)


def test_unknown_label_raises(normal_df, tmp_path):
    bad = normal_df.copy()
    bad.loc[bad.index[:3], "label"] = 9
    f = tmp_path / "badlabel.parquet"
    bad.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="label"):
        load_data(f)


def test_out_of_range_quality_raises(normal_df, tmp_path):
    bad = normal_df.copy()
    bad.loc[bad.index[0], "gnss_quality"] = 1.5
    f = tmp_path / "badquality.parquet"
    bad.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="gnss_quality"):
        load_data(f)


def test_wrong_dtype_raises(normal_df, tmp_path):
    bad = normal_df.copy()
    bad["label"] = bad["label"].astype(float)
    f = tmp_path / "baddtype.parquet"
    bad.to_parquet(f, index=False)
    with pytest.raises(SchemaError, match="integer"):
        load_data(f)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_data(tmp_path / "nope.parquet")


def test_ground_truth_validation(tmp_path, normal_df):
    f = tmp_path / "scenario_x_ground_truth.csv"
    pd.DataFrame({"timestamp": [1.0], "sensor_id": ["uav1_gnss"]}).to_csv(f, index=False)
    with pytest.raises(SchemaError, match="ground truth"):
        load_ground_truth(f)

    good = normal_df.loc[normal_df["attack_start"] == 1, list(GROUND_TRUTH_COLUMNS)].head(5)
    if good.empty:  # normal track has no attack rows — synthesize minimal GT
        good = pd.DataFrame({
            "timestamp": [1.0, 2.0], "sensor_id": ["uav1_gnss"] * 2,
            "label": [1, 1], "attack_start": [1, 1],
        })
    f2 = tmp_path / "scenario_ok_ground_truth.csv"
    good.to_csv(f2, index=False)
    out = load_ground_truth(f2)
    assert list(out.columns) == list(GROUND_TRUTH_COLUMNS)


def test_find_scenario_pairs(tmp_path, normal_df, spoof_df):
    normal_df.to_parquet(tmp_path / "scenario_a.parquet", index=False)
    spoof_df.to_parquet(tmp_path / "scenario_b.parquet", index=False)
    normal_df.head(1).to_csv(tmp_path / "scenario_a_ground_truth.csv", index=False)
    pairs = find_scenario_pairs(tmp_path)
    names = [p.name for p, _ in pairs]
    assert names == ["scenario_a.parquet"]  # scenario_b has no GT sibling


def test_split_windows(normal_df):
    windows = split_windows(normal_df.iloc[:25], window=10)
    assert [len(w) for w in windows] == [10, 10, 5]
    with pytest.raises(ValueError):
        split_windows(normal_df, window=0)
