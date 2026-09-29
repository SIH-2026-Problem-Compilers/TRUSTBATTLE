"""Tests for the TASK 2 physics features (contract: extract_physical_features)."""

import numpy as np
import pandas as pd
import pytest

from member1_physical.src.features import FEATURE_COLUMNS, extract_physical_features, learned_limits


def test_signature_adds_only_m1_columns(normal_df):
    """Contract: df -> df, adds m1_* columns, never mutates the input."""
    before = normal_df.copy(deep=True)
    out = extract_physical_features(normal_df)
    pd.testing.assert_frame_equal(normal_df, before)  # input untouched
    assert set(out.columns) == set(before.columns) | set(FEATURE_COLUMNS)
    assert not (set(before.columns) & {c for c in out.columns if c.startswith("m1_")} - set(FEATURE_COLUMNS))


def test_feature_columns_present_and_finite(normal_df, spoof_df):
    for df in (normal_df, spoof_df):
        out = extract_physical_features(df)
        for col in FEATURE_COLUMNS:
            assert col in out.columns
            assert np.isfinite(out[col]).all(), f"{col} has non-finite values"


def test_clean_data_low_residuals(normal_df):
    out = extract_physical_features(normal_df)
    assert out["m1_velocity_residual_mps"].abs().max() < 3.0
    # stand-in GNSS noise is 3 m/axis -> step-to-step position noise ~8 m;
    # 25 m is the configured evidence limit (configs/settings.yaml)
    assert out["m1_position_residual_m"].max() < 25.0
    assert out["m1_heading_residual_deg"].max() < 5.0


def test_spoof_elevates_velocity_residual(normal_df, spoof_df):
    clean = extract_physical_features(normal_df)
    attack = extract_physical_features(spoof_df)
    att_rows = attack[attack["attack_start"] == 1]
    assert len(att_rows) > 0
    # attack rows disagree far more than clean rows ever do
    assert att_rows["m1_velocity_residual_mps"].mean() > 10.0
    assert clean["m1_velocity_residual_mps"].abs().mean() < 1.0


def test_works_on_tiny_frame(normal_df):
    out = extract_physical_features(normal_df.iloc[:3])
    assert len(out) == 3
    for col in FEATURE_COLUMNS:
        assert np.isfinite(out[col]).all()


def test_missing_required_column_raises(normal_df):
    with pytest.raises(ValueError, match="missing required columns"):
        extract_physical_features(normal_df.drop(columns=["gyro_z"]))


def test_learned_limits(normal_df):
    limits = learned_limits(extract_physical_features(normal_df), percentile=0.999)
    for col in FEATURE_COLUMNS:
        assert col in limits
        assert limits[col] >= 0.0
    assert limits["m1_velocity_residual_mps"] > 0
