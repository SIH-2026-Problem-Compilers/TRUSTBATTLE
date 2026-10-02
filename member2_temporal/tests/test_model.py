"""Tests for TASK 4 anomaly models (training, scores, calibration)."""

import numpy as np
import pytest

from member2_temporal.src import model as m2_model
from member2_temporal.src.features import (
    NETWORK_FEATURE_COLUMNS,
    TEMPORAL_FEATURE_COLUMNS,
    extract_temporal_features,
)
from member2_temporal.src.fallback_data import make_normal, make_replay


@pytest.fixture(scope="module")
def clean_feat():
    feat = extract_temporal_features(make_normal(8000, seed=5))
    return feat.iloc[:6400].reset_index(drop=True), feat.iloc[6400:].reset_index(drop=True)


def test_train_temporal_model(clean_feat):
    train, _ = clean_feat
    iso, scaler = m2_model.train_temporal_model(train)
    assert hasattr(iso, "m2_score_floor_")
    assert hasattr(iso, "m2_score_ceiling_")
    assert iso.m2_columns_ == TEMPORAL_FEATURE_COLUMNS
    assert scaler.mean_.shape[0] == len(TEMPORAL_FEATURE_COLUMNS)


def test_train_network_model(clean_feat):
    train, _ = clean_feat
    iso, scaler = m2_model.train_network_model(train)
    assert iso.m2_columns_ == NETWORK_FEATURE_COLUMNS


def test_anomaly_score_01_bounds(clean_feat):
    train, holdout = clean_feat
    iso, scaler = m2_model.train_temporal_model(train)
    X = scaler.transform(holdout[TEMPORAL_FEATURE_COLUMNS].to_numpy(dtype=float))
    s = m2_model.anomaly_score_01(iso, X)
    assert (s >= 0).all() and (s <= 1).all()
    assert s.mean() < 0.15  # clean holdout should score low (q75 anchor = 0)
    assert np.median(s) < 0.05


def test_replay_scores_higher_than_clean(clean_feat):
    train, _ = clean_feat
    replay = extract_temporal_features(make_replay(600, start=300, seed=5))
    iso, scaler = m2_model.train_temporal_model(train)
    cols = iso.m2_columns_
    s_clean = m2_model.anomaly_score_01(
        iso, scaler.transform(train.iloc[-500:][cols].to_numpy(dtype=float)))
    s_replay = m2_model.anomaly_score_01(
        iso, scaler.transform(replay.iloc[320:520][cols].to_numpy(dtype=float)))
    assert s_replay.mean() > s_clean.mean() + 0.2


def test_calibrate_threshold_gives_target_fpr(clean_feat):
    train, holdout = clean_feat
    iso, scaler = m2_model.train_temporal_model(train)
    thr = m2_model.calibrate_threshold(iso, scaler, holdout, fpr_target=0.01)
    assert hasattr(iso, "m2_threshold_")
    # window-mean scores are the alert unit: ~1% of clean windows at/above
    means = m2_model.window_mean_scores(iso, scaler, holdout, window=50)
    assert (means >= thr).mean() <= 0.05


def test_ocsvm_baseline_and_score(clean_feat):
    train, holdout = clean_feat
    iso, scaler = m2_model.train_temporal_model(train)
    ocsvm = m2_model.train_ocsvm_baseline(train, scaler, TEMPORAL_FEATURE_COLUMNS)
    s = m2_model.ocsvm_score_01(ocsvm, scaler, holdout, TEMPORAL_FEATURE_COLUMNS,
                                train[TEMPORAL_FEATURE_COLUMNS].to_numpy(dtype=float))
    assert (s >= 0).all() and (s <= 1).all()


def test_load_artifacts_missing_returns_none(tmp_path):
    m, s = m2_model.load_artifacts("temporal", tmp_path / "no.pkl", tmp_path / "no2.pkl")
    assert m is None and s is None


def test_load_artifacts_bad_kind():
    with pytest.raises(ValueError):
        m2_model.load_artifacts("bogus")
