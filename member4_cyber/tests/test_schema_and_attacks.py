"""M4 generator/attack tests: schema validity, window injection, §5 alignment."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from member4_cyber.src.attack_simulator import ATTACKS, attack_mixed
from member4_cyber.src.generate_data import make_clean_dataset
from member4_cyber.src.schema import COLUMNS, VALID_LABELS
from member4_cyber.src.validate_dataset import validate_dataframe


# ---------------------------------------------------------------------------
# clean generator (TASK 1)
# ---------------------------------------------------------------------------
def test_clean_dataset_schema_valid(clean):
    failures, _ = validate_dataframe(clean, "test")
    assert not failures, failures


def test_clean_dataset_shape_and_fields(clean):
    assert list(clean.columns) == COLUMNS
    assert len(clean) == 1200
    assert (clean["label"] == 0).all() and (clean["attack_start"] == 0).all()
    assert (clean["sequence_number"].diff().dropna() == 1).all()
    assert (np.diff(clean["timestamp"]) > 0).all()
    assert clean["gnss_quality"].between(0, 1).all()
    assert clean["packet_loss"].between(0, 1).all()


def test_kinematic_consistency(clean):
    """Reported IMU accel must match reported velocity changes (M1's physics)."""
    dt = 0.1
    dv = np.gradient(clean["vx"].to_numpy(), dt)
    resid = np.abs(dv - clean["accel_x"].to_numpy())
    assert np.quantile(resid, 0.99) < 0.5  # sensor noise only (~0.05 σ)


def test_reproducible_same_seed(full_clean):
    again = make_clean_dataset()
    pd.testing.assert_frame_equal(full_clean, again)


# ---------------------------------------------------------------------------
# attack engine (TASK 2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(ATTACKS))
def test_attack_injects_window(clean, name):
    """Each attack: attacked rows exist, window carries attack_start + label."""
    df, info = ATTACKS[name](clean, seed=42)
    assert info["rows_attacked"] > 0
    assert df is not clean  # no mutation of the input
    for s, e in info["windows"]:
        win = df.iloc[s:e]
        assert (win["attack_start"] == 1).all()
        assert (win["label"] == info["label"]).all()
    # pre-attack rows stay clean
    first_s = info["windows"][0][0]
    assert (df.iloc[:first_s]["label"] == 0).all()
    failures, _ = validate_dataframe(df, name)
    assert not failures, failures


def test_spoof_diverges_from_truth(clean):
    """Spoofed GNSS must move off the truth reference; IMU fields must not."""
    df, info = ATTACKS["gnss_spoof"](clean, seed=42)
    s, e = info["windows"][0]
    lat0 = float(clean["latitude"].iloc[0])
    mlat, mlon = 111_320.0, 111_320.0 * np.cos(np.radians(lat0))
    tlon = clean.attrs["truth_longitude"]
    d = (df["longitude"].to_numpy() - tlon) * mlon
    assert np.abs(d[s:e]).max() > 400            # strong divergence late-ramp
    assert np.abs(d[:s]).max() < 10              # pre-attack: GNSS noise only
    imu_cols = ["accel_x", "accel_y", "gyro_z"]
    assert np.allclose(df[imu_cols], clean[imu_cols])  # IMU untouched


def test_replay_rebroadcasts_old_content(clean):
    df, info = ATTACKS["replay"](clean, seed=42)
    s, e = info["windows"][0]
    win = df.iloc[s:e]
    # rewinds appear at live→stale row transitions (stale rows copy a message
    # from 121 ticks ago), not within the stale subsequence itself
    assert (np.diff(win["timestamp"].to_numpy()) < 0).any()    # clock rewinds
    seq = win["sequence_number"].to_numpy()
    assert (np.diff(seq) < 0).any()              # sequence steps backward
    assert (np.diff(seq) == 0).sum() >= 0        # duplicates allowed


def test_mixed_exact_percentages(full_clean):
    """§19: mixed datasets realize the exact requested corruption rate."""
    for pct in (5, 10, 20, 30):
        df, info = attack_mixed(full_clean, float(pct), seed=42)
        assert info["params"]["realized_pct"] == pytest.approx(pct, abs=0.01)
        assert info["rows_attacked"] == int(round(len(full_clean) * pct / 100))
        # all six families present, blocks contiguous
        by_type = info["params"]["rows_by_type"]
        assert len(by_type) == 6 and min(by_type.values()) > 0
        failures, _ = validate_dataframe(df, f"mixed{pct}")
        assert not failures, failures


# ---------------------------------------------------------------------------
# ground truth alignment (TASK 3 / §5)
# ---------------------------------------------------------------------------
def test_ground_truth_frame_aligns_rowwise(clean):
    df, info = ATTACKS["network_anomaly"](clean, seed=42)
    gt = df[["timestamp", "sensor_id", "label", "attack_start"]].copy()
    assert len(gt) == len(df)
    assert (gt["label"].to_numpy() == df["label"].to_numpy()).all()
    assert (gt["attack_start"].to_numpy() == df["attack_start"].to_numpy()).all()
    assert set(df["label"].unique()) <= VALID_LABELS


def test_validator_catches_broken_data(clean):
    """Self-explanatory failures: wrong dtype, bad label, misaligned truth."""
    bad = clean.copy()
    bad["sequence_number"] = bad["sequence_number"].astype(float)
    failures, _ = validate_dataframe(bad, "bad")
    assert any("integer dtype" in f for f in failures)

    bad2 = clean.copy()
    bad2.loc[0, "label"] = 9
    failures2, _ = validate_dataframe(bad2, "bad2")
    assert any("unknown label codes" in f for f in failures2)
