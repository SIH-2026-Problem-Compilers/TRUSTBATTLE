"""Fusion tests: contract signature, weight semantics (§14), Kalman baseline (§20)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from member3_trust.src.fusion import (
    KalmanTracker,
    compute_weights,
    fuse,
    fuse_normal,
    latlon_to_xy,
    xy_to_latlon,
)


OBS = {
    "gnss": {"lat": 28.6100, "lon": 77.2100, "velocity": 6.0},
    "imu": {"lat": 28.6102, "lon": 77.2101, "velocity": 6.2},
    "visual": {"lat": 28.6101, "lon": 77.2098, "velocity": 5.8},
}


# ---------------------------------------------------------------------------
# contract shape
# ---------------------------------------------------------------------------
def test_fuse_returns_state_estimate():
    """fuse(observations, trust_scores) -> {lat, lon, velocity} (+ diagnostics)."""
    est = fuse(OBS, {"gnss": 90, "imu": 90, "visual": 90})
    for key in ("lat", "lon", "velocity"):
        assert isinstance(est[key], float)
    assert 28.60 < est["lat"] < 28.62
    assert 77.20 < est["lon"] < 77.22
    assert 5.0 < est["velocity"] < 7.0
    assert est["mode"] == "trust_aware"  # default from fusion_config.json
    assert abs(sum(est["weights_used"].values()) - 1.0) < 1e-4  # display-rounded


def test_fuse_accepts_list_observations_and_trust_message():
    """Both observation styles and compute_trust results are accepted."""
    obs_list = [dict(v, sensor_id=k) for k, v in OBS.items()]
    trust_msg = {"trust": {"sensor_trust": {"gnss": 90, "imu": 90, "visual": 90}}}
    est = fuse(obs_list, trust_msg)
    assert abs(sum(est["weights_used"].values()) - 1.0) < 1e-4  # display-rounded


def test_fuse_requires_position():
    """No lat/lon at all → clear error."""
    with pytest.raises(ValueError):
        fuse({"net": {"velocity": 5.0}}, {})


# ---------------------------------------------------------------------------
# weight semantics (§14)
# ---------------------------------------------------------------------------
def test_normal_mode_equal_weights():
    """Baseline fusion ignores trust: equal static weights."""
    est = fuse_normal(OBS)
    assert all(abs(w - 1.0 / 3) < 1e-4 for w in est["weights_used"].values())
    w = compute_weights({"gnss": 5, "imu": 95, "visual": 95}, "normal", 0.05)
    assert all(abs(v - 1.0 / 3) < 1e-9 for v in w.values())


def test_trust_aware_weights_proportional():
    """Higher trust → more influence; weights normalized to Σ=1."""
    w = compute_weights({"a": 90.0, "b": 30.0}, "trust_aware", 0.05)
    assert w["a"] > w["b"]
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_min_sensor_weight_floor():
    """A zero-trust sensor is floored at fusion.min_sensor_weight, not zero."""
    w = compute_weights({"a": 0.0, "b": 100.0, "c": 100.0}, "trust_aware", 0.05)
    assert w["a"] >= 0.05 / 2.05 - 1e-9
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_high_trust_sensor_pulls_estimate():
    """The estimate must move toward the trusted sensor (§14 influence)."""
    spread_obs = {
        "gnss": {"lat": 28.600, "lon": 77.200, "velocity": 6.0},   # 11 m south-west
        "imu": {"lat": 28.601, "lon": 77.201, "velocity": 6.0},
    }
    toward_gnss = fuse(spread_obs, {"gnss": 100, "imu": 10})
    toward_imu = fuse(spread_obs, {"gnss": 10, "imu": 100})
    assert toward_gnss["lat"] < toward_imu["lat"]
    assert toward_gnss["lon"] < toward_imu["lon"]


# ---------------------------------------------------------------------------
# Kalman baseline (§20)
# ---------------------------------------------------------------------------
def test_kalman_reduces_noise():
    """Filtered positions beat the raw measurements on a noisy straight track."""
    rng = np.random.default_rng(0)
    lat0, lon0 = 28.61, 77.21
    tracker = KalmanTracker(lat0, lon0)
    raw_err, filt_err = [], []
    for i in range(200):
        east, north = 6.0 * i / 10.0, 1.0 * i / 10.0       # true motion
        el, en = east + rng.normal(0, 5.0), north + rng.normal(0, 5.0)
        lat, lon = xy_to_latlon(el, en, lat0, lon0)
        fx, fy = tracker.step(lat, lon, 0.1)
        if i >= 40:  # after convergence
            raw_err.append(math.hypot(el - east, en - north))
            filt_err.append(math.hypot(fx - east, fy - north))
    assert np.mean(filt_err) < np.mean(raw_err)


def test_latlon_roundtrip():
    """Local metre conversion round-trips to sub-millimetre precision."""
    lat0, lon0 = 28.61, 77.21
    e, n = latlon_to_xy(28.62, 77.22, lat0, lon0)
    lat, lon = xy_to_latlon(e, n, lat0, lon0)
    assert abs(lat - 28.62) < 1e-9
    assert abs(lon - 77.22) < 1e-9
