"""Integration tests: M3 in the shared pipeline + scenario schema compliance."""

from __future__ import annotations

import numpy as np

from integration import interfaces
from integration.pipeline import register_available_implementations, run_observation
from member3_trust.src import eval_scenarios


def test_m3_registered_in_pipeline():
    """After registration, compute_trust/fuse are no longer MISSING stubs."""
    register_available_implementations()
    assert "compute_trust" not in interfaces.MISSING
    assert "fuse" not in interfaces.MISSING


def test_run_observation_produces_trust():
    """End-to-end: pipeline window → M1+M2 scores → M3 trust (no module_not_ready)."""
    register_available_implementations()
    df, _ = eval_scenarios.make_spoof_scenario(n=300)
    window = df.iloc[0:50].reset_index(drop=True)
    msg = run_observation(window)
    assert "trust_status" not in msg, "M3 must be wired into the pipeline"
    trust = msg["trust"]
    assert 0.0 <= trust["observation_trust"] <= 100.0
    assert abs(sum(trust["sensor_weights"].values()) - 1.0) < 1e-6
    assert msg["alert"]["level"] in ("GREEN", "AMBER", "RED")


def test_scenarios_follow_shared_schema():
    """Generated frames carry exactly the data_schema.md §1 columns."""
    df, truth = eval_scenarios.make_spoof_scenario(n=200)
    assert list(df.columns) == eval_scenarios.SCHEMA_COLUMNS
    assert {"timestamp", "sensor_id", "label", "attack_start"} <= set(truth.columns)
    assert set(df["label"].unique()) <= {0, 1, 2, 3, 4, 5, 6}
    assert set(df["attack_start"].unique()) <= {0, 1}
    assert "truth_latitude" in df.attrs and "truth_longitude" in df.attrs


def test_spoof_injection_flags_truthfully():
    """Attacked rows are labelled 1/attack_start=1; truth position untouched."""
    df, _ = eval_scenarios.make_spoof_scenario(n=800, attack_start=300, attack_end=500)
    attacked = df["attack_start"] == 1
    assert attacked.sum() == 200
    assert (df.loc[attacked, "label"] == 1).all()
    assert (df.loc[~attacked, "label"] == 0).all()
    offset_m = (df.loc[attacked, "longitude"].to_numpy()
                - df.attrs["truth_longitude"][attacked.to_numpy()]) * 97830.0
    assert np.abs(offset_m).max() > 100  # real divergence, not noise
    clean_offset = (df.loc[~attacked, "longitude"].to_numpy()
                    - df.attrs["truth_longitude"][(~attacked).to_numpy()]) * 97830.0
    assert np.abs(clean_offset).max() < 15  # clean GNSS noise only


def test_corruption_blocks_are_contiguous():
    """§19 sweep: corruption forms contiguous block(s) of the requested size."""
    df, _ = eval_scenarios.make_corruption_scenario(10, n=1600)
    attacked = np.flatnonzero((df["attack_start"] == 1).to_numpy())
    assert len(attacked) == 80  # 10% of the 800-row region
    assert attacked.max() - attacked.min() + 1 == len(attacked)  # contiguous
    assert (df["label"] == 1).sum() == len(attacked)
