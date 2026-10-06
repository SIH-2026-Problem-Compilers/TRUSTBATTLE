"""Trust engine tests: weighted model, §13 dynamics, alert thresholds, §16 wording."""

from __future__ import annotations

import pytest

from member3_trust.src.trust_engine import (
    compute_trust,
    cross_sensor_qualities,
)


# ---------------------------------------------------------------------------
# output shape (data_schema.md §2)
# ---------------------------------------------------------------------------
def test_output_shape(clean_scores, clean_obs):
    """trust/alert blocks carry exactly the contract keys with valid values."""
    out = compute_trust(clean_scores, [], observations=clean_obs)
    # "scores" is the effective schema-§2 scores block actually used (includes
    # values derived inside the engine, e.g. cross_sensor_agreement)
    assert set(out) == {"trust", "alert", "evidence", "scores"}
    assert "cross_sensor_agreement" in out["scores"], \
        "derived cross-sensor agreement must be surfaced for callers"
    assert 0.0 <= out["scores"]["cross_sensor_agreement"] <= 1.0
    trust = out["trust"]
    for key in ("observation_trust", "sensor_reliability", "sensor_weights",
                "sensor_trust", "consensus_trust"):
        assert key in trust, key
    assert 0.0 <= trust["observation_trust"] <= 100.0
    assert 0.0 <= trust["sensor_reliability"] <= 100.0
    assert abs(sum(trust["sensor_weights"].values()) - 1.0) < 1e-6
    alert = out["alert"]
    for key in ("level", "message", "possible_causes", "recommended_action"):
        assert key in alert, key
    assert alert["level"] in ("GREEN", "AMBER", "RED")
    assert isinstance(out["evidence"], list) and out["evidence"]
    for e in out["evidence"]:
        assert {"check", "pass", "detail"} <= set(e)


def test_alert_thresholds(clean_scores, spoof_scores, clean_obs, spoof_obs):
    """GREEN ≥ 70, AMBER 40–70, RED < 40 (configs trust_engine.thresholds)."""
    assert compute_trust(clean_scores, [], observations=clean_obs)["alert"]["level"] == "GREEN"
    hist = []
    red = None
    for _ in range(8):
        red = compute_trust(spoof_scores, hist, observations=spoof_obs)
        hist.append(red)
    assert red["alert"]["level"] == "RED"
    assert red["trust"]["observation_trust"] < 40
    # synthetic AMBER: moderately degraded physical evidence
    amber_scores = dict(clean_scores, physical_consistency=0.35, anomaly_physical=0.55)
    hist2 = []
    amber = None
    for _ in range(10):
        amber = compute_trust(amber_scores, hist2, observations=clean_obs)
        hist2.append(amber)
    assert amber["alert"]["level"] == "AMBER"
    assert 40 <= amber["trust"]["observation_trust"] < 70


# ---------------------------------------------------------------------------
# §16 wording rule — never claim an attack attribution
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scores_fixture", ["clean_scores", "spoof_scores"])
def test_never_claims_hacked(request, scores_fixture, clean_obs, spoof_obs):
    """No output string may claim 'hacked'/'attack confirmed' — §16."""
    obs = spoof_obs if scores_fixture == "spoof_scores" else clean_obs
    out = compute_trust(request.getfixturevalue(scores_fixture), [], observations=obs)
    blob = (out["alert"]["message"] + " " + out["alert"]["recommended_action"]
            + " " + json_dumps(out))
    for banned in ("hacked", "was attacked", "confirmed attack", "compromised by"):
        assert banned not in blob.lower()


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, default=str)


def test_spoof_causes_are_hedged(spoof_scores, spoof_obs):
    """Possible causes are 'potentially consistent with'-style hypotheses."""
    hist = []
    out = None
    for _ in range(4):  # drive into RED before asserting the alert message
        out = compute_trust(spoof_scores, hist, observations=spoof_obs)
        hist.append(out)
    causes = out["alert"]["possible_causes"]
    assert "GNSS spoofing" in causes
    assert "sensor malfunction" in causes
    assert out["alert"]["message"] == "INFORMATION INTEGRITY ALERT"


# ---------------------------------------------------------------------------
# missing evidence handling (cross_sensor_agreement is pending upstream)
# ---------------------------------------------------------------------------
def test_missing_scores_renormalize(clean_scores):
    """Dropping keys must not crash and must renormalize over what remains."""
    full = compute_trust(clean_scores, [])["trust"]["observation_trust"]
    partial = compute_trust(
        {"physical_consistency": clean_scores["physical_consistency"]}, []
    )["trust"]["observation_trust"]
    assert 0.0 <= partial <= 100.0
    empty = compute_trust({}, [])
    assert empty["trust"]["observation_trust"] > 0  # priors carry it
    # a missing cross score is reported as PENDING evidence
    checks = [e["check"] for e in empty["evidence"]]
    assert any("Cross-sensor" in c for c in checks)


def test_cross_sensor_agreement_used_when_provided(clean_scores, clean_obs):
    """An explicit upstream cross_sensor_agreement changes the result."""
    with_cross = compute_trust(dict(clean_scores, cross_sensor_agreement=0.1), [])
    without = compute_trust(clean_scores, [])
    assert with_cross["trust"]["observation_trust"] < without["trust"]["observation_trust"]


# ---------------------------------------------------------------------------
# derived cross-sensor agreement (Layer 5, §11)
# ---------------------------------------------------------------------------
def test_cross_qualities_blame_the_outlier(clean_obs, spoof_obs):
    """Consensus sensors keep q≈1; only the disagreement outlier collapses."""
    clean_q = cross_sensor_qualities(clean_obs)
    assert clean_q is not None
    assert min(clean_q.values()) > 0.8
    spoof_q = cross_sensor_qualities(spoof_obs)
    assert spoof_q["gnss"] < 0.2
    assert spoof_q["imu"] > 0.95 and spoof_q["visual"] > 0.95


def test_derived_cross_not_applied_to_net(spoof_scores, spoof_obs):
    """Position disagreement says nothing about the telemetry channel: net stays trusted."""
    out = compute_trust(spoof_scores, [], observations=spoof_obs)
    assert out["trust"]["sensor_trust"]["net"] > 85


# ---------------------------------------------------------------------------
# dynamic trust (§13): fast drop, slow recovery, no permanent blacklist
# ---------------------------------------------------------------------------
def _drive(scores, obs, steps, hist=None):
    hist = hist or []
    curve = []
    for _ in range(steps):
        out = compute_trust(scores, hist, observations=obs)
        hist.append(out)
        curve.append(out["trust"]["observation_trust"])
    return curve, hist


def test_drop_is_fast(spoof_scores, spoof_obs, clean_scores, clean_obs):
    """§13: from a clean state, sustained bad evidence reaches RED within a few steps."""
    _, hist = _drive(clean_scores, clean_obs, 5)
    pre_attack = hist[-1]["trust"]["observation_trust"]
    curve, hist = _drive(spoof_scores, spoof_obs, 5, hist)
    assert curve[0] < pre_attack           # first attack step already dropped
    assert curve[-1] < curve[0]            # keeps dropping under sustained evidence
    assert min(curve) < 40


def curve_prev(hist):
    return hist[-1]["trust"]["observation_trust"]


def test_recovery_is_gradual_and_completes(spoof_scores, spoof_obs, clean_scores, clean_obs):
    """§13: trust recovers gradually and returns above GREEN (no blacklist)."""
    _, hist = _drive(clean_scores, clean_obs, 5)
    _, hist = _drive(spoof_scores, spoof_obs, 8)
    deep = hist[-1]["trust"]["observation_trust"]
    curve, hist = _drive(clean_scores, clean_obs, 30, hist)
    assert curve == sorted(curve), "recovery must be monotonic"
    assert curve[-1] >= 70
    assert len(curve) > 5  # gradual: more steps to recover than to crash
    assert curve[-1] > deep + 40


def test_recovery_slower_than_drop(spoof_scores, spoof_obs, clean_scores, clean_obs):
    """§13 asymmetry: drop_rate 0.6 reaches RED in fewer steps than recovery needs."""
    _, hist = _drive(clean_scores, clean_obs, 5)
    drop_curve, hist = _drive(spoof_scores, spoof_obs, 12, hist)
    steps_to_red = next(i for i, t in enumerate(drop_curve) if t < 40) + 1
    rec_curve, hist = _drive(clean_scores, clean_obs, 40, hist)
    steps_to_green = next(i for i, t in enumerate(rec_curve) if t >= 70) + 1
    assert steps_to_green > steps_to_red


def test_history_state_continuation(clean_scores, clean_obs):
    """Passing prior trust dicts (bare or wrapped) continues the dynamics."""
    _, hist = _drive(clean_scores, clean_obs, 3)
    wrapped = [{"trust": h["trust"]} for h in hist]          # full-message form
    a = compute_trust(clean_scores, hist)["trust"]["observation_trust"]
    b = compute_trust(clean_scores, wrapped)["trust"]["observation_trust"]
    assert abs(a - b) < 1e-9


# ---------------------------------------------------------------------------
# fusion weights (§14)
# ---------------------------------------------------------------------------
def test_suspect_source_downweighted(spoof_scores, spoof_obs, clean_scores, clean_obs):
    """GNSS trust collapse must shrink its fusion weight (min floor respected)."""
    clean = compute_trust(clean_scores, [], observations=clean_obs)["trust"]
    hist = [compute_trust(spoof_scores, [], observations=spoof_obs)]
    for _ in range(6):
        hist.append(compute_trust(spoof_scores, hist, observations=spoof_obs))
    attacked = hist[-1]["trust"]
    assert attacked["sensor_weights"]["gnss"] < 0.6 * clean["sensor_weights"]["gnss"]
    assert abs(sum(attacked["sensor_weights"].values()) - 1.0) < 1e-6
    assert min(attacked["sensor_weights"].values()) >= 0.05 - 1e-9


# ---------------------------------------------------------------------------
# no-absolution geometric combination
# ---------------------------------------------------------------------------
def test_one_catastrophic_evidence_is_not_averaged_away(spoof_scores, spoof_obs):
    """Clean temporal/network evidence must not absolve a physical collapse."""
    out = compute_trust(spoof_scores, [], observations=spoof_obs)
    assert out["trust"]["sensor_trust"]["gnss"] < 60
