"""Tests for TASK 2/3 feature extraction (contract: extract_temporal_features)."""

import numpy as np
import pandas as pd
import pytest

from member2_temporal.src.fallback_data import (
    make_network_anomaly,
    make_normal,
    make_replay,
    make_telemetry_manip,
)
from member2_temporal.src.features import (
    FEATURE_COLUMNS,
    NETWORK_FEATURE_COLUMNS,
    TEMPORAL_FEATURE_COLUMNS,
    extract_temporal_features,
)
from member2_temporal.src.network_features import extract_network_features


def test_output_has_all_feature_columns(normal_df):
    out = extract_temporal_features(normal_df)
    for c in FEATURE_COLUMNS:
        assert c in out.columns, f"missing feature column {c}"


def test_input_not_mutated(normal_df):
    before = normal_df.copy()
    extract_temporal_features(normal_df)
    pd.testing.assert_frame_equal(normal_df, before)


def test_features_finite(normal_df):
    out = extract_temporal_features(normal_df)
    vals = out[FEATURE_COLUMNS].to_numpy(dtype=float)
    assert np.isfinite(vals).all(), "NaN/inf leaked into feature columns"


def test_missing_timestamp_raises():
    with pytest.raises(ValueError):
        extract_temporal_features(pd.DataFrame({"velocity": [1.0]}))


def test_m2_prefix_no_collision(normal_df):
    out = extract_temporal_features(normal_df)
    m2_cols = [c for c in out.columns if c.startswith("m2_")]
    assert len(m2_cols) == len(FEATURE_COLUMNS)
    # no original schema column was overwritten
    for c in normal_df.columns:
        assert c in out.columns


def test_clean_track_is_quiet(normal_df):
    """On clean data staleness/duplication flags must be ~all zero."""
    out = extract_temporal_features(normal_df)
    assert out["m2_seq_dup"].sum() == 0
    assert out["m2_seq_seen_before"].sum() == 0
    assert out["m2_ts_rewind_s"].max() == 0.0
    assert out["m2_ts_nonmono"].sum() == 0
    assert out["m2_stale_score"].max() < 0.1
    assert out["m2_stale_active"].sum() == 0


def test_replay_signature_lights_up(replay_df):
    """Replay: re-delivered rows repeat earlier timestamps/sequence numbers."""
    out = extract_temporal_features(replay_df)
    atk = out.index[out["attack_start"] == 1]
    n_atk = len(atk)
    assert out.loc[atk, "m2_seq_seen_before"].sum() > 0.4 * n_atk
    assert out["m2_ts_rewind_s"].max() > 5.0
    assert out.loc[atk, "m2_stale_score"].mean() > 0.5
    assert out.loc[atk, "m2_stale_active"].mean() > 0.9  # sticky within the attack


def test_telemetry_manip_signature(manip_df):
    """Telemetry manipulation: sequence irregularity + timestamp jitter."""
    out = extract_temporal_features(manip_df)
    atk = out["attack_start"] == 1
    assert out.loc[atk, "m2_seq_gap"].max() > 1.5
    assert out.loc[atk, "m2_dt_ratio"].max() > 1.5
    assert out.loc[atk, "m2_seq_expected_err"].max() > 0


def test_network_anomaly_signature(netanom_df):
    """Network anomaly: IAT spikes ~1 s vs ~20 ms normal + loss + rate drop."""
    out = extract_temporal_features(netanom_df)
    atk = out["attack_start"] == 1
    assert out.loc[atk, "m2_pkt_iat_excess_ms"].max() > 500.0
    assert out.loc[atk, "m2_pkt_loss"].max() > 0.1
    assert out.loc[atk, "m2_net_disruption"].max() > 0.9
    clean = out["attack_start"] == 0
    assert out.loc[clean, "m2_net_disruption"].max() < 0.5


def test_network_extractor_standalone(normal_df, netanom_df):
    clean = extract_network_features(normal_df)
    attack = extract_network_features(netanom_df)
    for c in NETWORK_FEATURE_COLUMNS:
        assert c in clean.columns
    assert attack["m2_pkt_iat_ms"].max() > clean["m2_pkt_iat_ms"].max()


def test_feature_subsets_partition():
    assert set(NETWORK_FEATURE_COLUMNS) | set(TEMPORAL_FEATURE_COLUMNS) == set(FEATURE_COLUMNS)
    assert not set(NETWORK_FEATURE_COLUMNS) & set(TEMPORAL_FEATURE_COLUMNS)


def test_small_window_works(normal_df):
    out = extract_temporal_features(normal_df.head(5))
    assert np.isfinite(out[FEATURE_COLUMNS].to_numpy(dtype=float)).all()
