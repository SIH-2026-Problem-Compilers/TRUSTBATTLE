"""TRUSTBATTLE — cross-module end-to-end tests (root ``tests/``).

Verifies the full chain on REAL datasets (no mocked numbers):

    M4 dataset -> M1 (physical) -> M2 (temporal/network) -> M3 (trust + fusion)

Assertions are relational or contract-based (``docs/contracts/*`` and
``configs/settings.yaml`` thresholds) — never invented constants:

    trust_after_attack < trust_before_attack
    gnss_weight_after_attack < gnss_weight_before_attack
    trust_after_recovery > trust_during_attack
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import List

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integration import interfaces  # noqa: E402
from integration.pipeline import run_observation  # noqa: E402
from member3_trust.src.eval_scenarios import (  # noqa: E402
    _reset_imu_state,
    make_spoof_scenario,
    sensor_observations,
)
from member3_trust.src.settings import trust_settings  # noqa: E402
from member3_trust.src.trust_engine import compute_trust  # noqa: E402
from member3_trust.src.fusion import fuse  # noqa: E402

WINDOW = 50  # rows per observation window (10 Hz -> 5 s)
GREEN = float(trust_settings()["thresholds"]["green"])   # from settings.yaml
AMBER = float(trust_settings()["thresholds"]["amber"])

M1_EVIDENCE_CHECKS = {
    "GNSS/IMU position residual",
    "GNSS/IMU velocity disagreement",
    "Historical speed envelope",
    "Acceleration consistency",
}
M2_EVIDENCE_HINTS = ("Sequence", "Timestamp", "Sampling", "Packet", "Message freshness",
                     "Packet loss", "rate")


# --------------------------------------------------------------------------- helpers
def stream(df: pd.DataFrame, seed0: int = 1000, max_windows: int = None) -> List[dict]:
    """Run *df* through M1+M2 -> M3 -> fusion, one record per window."""
    history: List[dict] = []
    out: List[dict] = []
    for w0 in range(0, len(df) - WINDOW + 1, WINDOW):
        if max_windows is not None and (w0 // WINDOW) >= max_windows:
            break
        win = slice(w0, w0 + WINDOW)
        window = df.iloc[win].reset_index(drop=True)
        message = run_observation(window)
        obs = sensor_observations(df, win, rng_seed=seed0 + w0)
        trust_out = compute_trust(message.get("scores", {}), history, observations=obs)
        history.append(trust_out)
        if len(history) > 200:
            history = history[-200:]
        out.append({
            "w0": w0,
            "attack": bool((window["label"] > 0).any()),
            "message": message,
            "trust": trust_out,
            "estimate": fuse(obs, trust_out["trust"]),
            "reported": (float(window["latitude"].mean()),
                         float(window["longitude"].mean())),
        })
    return out


def trust_of(rec) -> float:
    return float(rec["trust"]["trust"]["observation_trust"])


def level_of(rec) -> str:
    return rec["trust"]["alert"]["level"]


def gnss_weight_of(rec) -> float:
    return float(rec["trust"]["trust"]["sensor_weights"].get("gnss", 0.0))


@pytest.fixture(scope="module")
def normal_stream() -> List[dict]:
    """M4 clean dataset (data/synthetic/uav_normal_v1.parquet)."""
    path = REPO_ROOT / "data" / "synthetic" / "uav_normal_v1.parquet"
    if not path.exists():
        pytest.skip("M4 clean dataset missing")
    _reset_imu_state()
    return stream(pd.read_parquet(path), seed0=3000, max_windows=40)


@pytest.fixture(scope="module")
def spoof_stream() -> List[dict]:
    """M4 GNSS-spoof dataset: clean prefix (rows 0-2999) then attack (3000-5999)."""
    path = REPO_ROOT / "data" / "attacks" / "scenario_gnss_spoof.parquet"
    if not path.exists():
        pytest.skip("M4 gnss_spoof dataset missing")
    _reset_imu_state()
    # 60 clean windows + 10 attack windows
    return stream(pd.read_parquet(path), seed0=1000, max_windows=70)


@pytest.fixture(scope="module")
def story_stream() -> List[dict]:
    """§22 demo story: clean -> spoof -> RECOVERY (M3 scenario generator)."""
    _reset_imu_state()
    df, _ = make_spoof_scenario(n=3200, attack_start=1000, attack_end=1800)
    return stream(df, seed0=7000)


# --------------------------------------------------------------------------- 1-2: scenarios run
def test_normal_scenario_runs(normal_stream):
    assert len(normal_stream) > 0
    for rec in normal_stream:
        assert not rec["attack"]          # clean dataset carries no attack rows
        assert 0.0 <= trust_of(rec) <= 100.0


def test_gnss_spoof_scenario_runs(spoof_stream):
    assert any(r["attack"] for r in spoof_stream)
    assert any(not r["attack"] for r in spoof_stream)   # clean prefix exists
    for rec in spoof_stream:
        assert 0.0 <= trust_of(rec) <= 100.0


# --------------------------------------------------------------------------- 3: M1 evidence
def test_m1_produces_physical_evidence(spoof_stream):
    rec = spoof_stream[0]
    checks = {e["check"] for e in rec["message"]["evidence"]}
    assert checks & M1_EVIDENCE_CHECKS, "M1 physics checks missing from evidence"
    scores = rec["message"]["scores"]
    for key in ("physical_consistency", "anomaly_physical"):
        assert key in scores, f"M1 score {key} missing"
        assert 0.0 <= scores[key] <= 1.0


def test_m1_trained_model_is_loaded_and_scores():
    """The IsolationForest artifact must actually be in the scoring path."""
    from member1_physical.src.physical_module import get_scorer
    scorer = get_scorer()
    assert scorer.model_available, "models/physical/isolation_forest.pkl not loaded"


def test_m1_model_prediction_influences_physical_consistency():
    """White-box proof that the trained model's prediction reaches downstream
    trust through physical_consistency (not just the anomaly_physical field):
    forcing a high model score must lower the consistency score."""
    import numpy as np
    from member1_physical.src.physical_module import get_scorer

    scorer = get_scorer()
    df, _ = make_spoof_scenario(n=200, attack_start=80, attack_end=140)
    window = df.iloc[:WINDOW].reset_index(drop=True)

    base = scorer.score(window)["scores"]["physical_consistency"]

    orig = scorer.model_anomaly_score
    try:
        scorer.model_anomaly_score = lambda feat: np.ones(len(feat))  # model: fully anomalous
        high = scorer.score(window)["scores"]["physical_consistency"]
        scorer.model_anomaly_score = lambda feat: np.zeros(len(feat))  # model: fully normal
        low = scorer.score(window)["scores"]["physical_consistency"]
    finally:
        scorer.model_anomaly_score = orig

    assert high < low, (
        "model output must influence physical_consistency: "
        f"high-anomaly={high} vs low-anomaly={low}")
    assert high < base <= low + 1e-9


# --------------------------------------------------------------------------- 4: M2 evidence
def test_m2_produces_temporal_network_evidence(spoof_stream):
    rec = spoof_stream[0]
    details = [e["check"] for e in rec["message"]["evidence"]]
    assert any(any(h in c for h in M2_EVIDENCE_HINTS) for c in details), \
        "M2 temporal/network checks missing from evidence"
    scores = rec["message"]["scores"]
    for key in ("temporal_consistency", "anomaly_temporal", "network_integrity"):
        assert key in scores, f"M2 score {key} missing"
        assert 0.0 <= scores[key] <= 1.0


def test_m2_trained_models_are_loaded():
    from member2_temporal.src import model as m2_model
    t_model, t_scaler = m2_model.load_artifacts("temporal")
    n_model, n_scaler = m2_model.load_artifacts("network")
    assert t_model is not None and t_scaler is not None, "temporal_model.pkl not loaded"
    assert n_model is not None and n_scaler is not None, "network_model.pkl not loaded"


# --------------------------------------------------------------------------- 5-7: M3 outputs
def test_m3_produces_observation_trust(normal_stream, spoof_stream):
    for rec in normal_stream + spoof_stream:
        t = rec["trust"]["trust"]
        assert 0.0 <= t["observation_trust"] <= 100.0
        assert t["sensor_reliability"] is not None


def test_sensor_weights_are_produced_and_normalized(normal_stream, spoof_stream):
    for rec in normal_stream + spoof_stream:
        w = rec["trust"]["trust"]["sensor_weights"]
        assert {"gnss", "imu", "visual"} <= set(w)
        assert math.isclose(sum(w.values()), 1.0, abs_tol=1e-3), \
            f"sensor weights must sum to 1, got {sum(w.values())}"
        assert all(v > 0 for v in w.values())


def test_fusion_output_is_produced(normal_stream, spoof_stream):
    for rec in normal_stream + spoof_stream:
        est = rec["estimate"]
        for key in ("lat", "lon", "velocity"):
            assert key in est and math.isfinite(float(est[key]))
        assert 0.0 <= float(est["lat"]) <= 90.0
        assert 0.0 <= float(est["lon"]) <= 180.0


# --------------------------------------------------------------------------- 8: trust drop
def test_spoofing_causes_trust_decrease(spoof_stream):
    clean = [trust_of(r) for r in spoof_stream if not r["attack"]]
    attack = [trust_of(r) for r in spoof_stream if r["attack"]]
    assert clean and attack
    assert min(attack) < min(clean), "trust must decrease when spoofing starts"
    # alert levels move out of GREEN during the attack (contract thresholds)
    assert any(level_of(r) != "GREEN" for r in spoof_stream if r["attack"])
    assert all(level_of(r) != "RED" for r in spoof_stream if not r["attack"])


# --------------------------------------------------------------------------- 9: GNSS influence
def test_spoofed_gnss_influence_decreases(spoof_stream):
    clean = [gnss_weight_of(r) for r in spoof_stream if not r["attack"]]
    attack = [gnss_weight_of(r) for r in spoof_stream if r["attack"]]
    assert min(attack) < min(clean), "GNSS fusion weight must fall during spoofing"
    # independent sources keep their influence (attribution sanity)
    imu = [float(r["trust"]["trust"]["sensor_trust"].get("imu", 0)) for r in spoof_stream if r["attack"]]
    vis = [float(r["trust"]["trust"]["sensor_trust"].get("visual", 0)) for r in spoof_stream if r["attack"]]
    assert min(imu) > GREEN, "IMU must stay trusted while GNSS is spoofed"
    assert min(vis) > GREEN, "visual must stay trusted while GNSS is spoofed"


def test_fusion_is_more_stable_than_reported(spoof_stream):
    """During the attack the fused estimate must stay closer to the true
    trajectory than the spoofed GNSS report (§14/§20 resilience claim)."""
    try:
        from member4_cyber.src.generate_data import make_clean_dataset
        base = make_clean_dataset()
        truth_lat = base.attrs["truth_latitude"]
        truth_lon = base.attrs["truth_longitude"]
    except Exception:
        pytest.skip("M4 truth reconstruction unavailable")

    def metres(a_lat, a_lon, b_lat, b_lon):
        return math.hypot((float(a_lat) - float(b_lat)) * 111_320.0,
                          (float(a_lon) - float(b_lon)) * 111_320.0
                          * math.cos(math.radians(float(a_lat))))

    reported_err, fused_err = [], []
    for rec in spoof_stream:
        if not rec["attack"]:
            continue
        w0 = rec["w0"]
        tlat = float(pd.Series(truth_lat[w0:w0 + WINDOW]).mean())
        tlon = float(pd.Series(truth_lon[w0:w0 + WINDOW]).mean())
        rlat, rlon = rec["reported"]
        est = rec["estimate"]
        reported_err.append(metres(rlat, rlon, tlat, tlon))
        fused_err.append(metres(est["lat"], est["lon"], tlat, tlon))
    assert reported_err and fused_err
    assert sum(fused_err) < sum(reported_err), (
        f"trust-aware fusion must beat the spoofed report: "
        f"fused={sum(fused_err):.1f} m vs reported={sum(reported_err):.1f} m")


# --------------------------------------------------------------------------- 10: recovery
def test_trust_recovers_after_attack_ends(story_stream):
    attack = [r for r in story_stream if r["attack"]]
    post = [r for r in story_stream if not r["attack"] and r["w0"] > attack[-1]["w0"]]
    assert attack, "story must contain an attack phase"
    assert post, "story must contain a post-attack recovery phase"

    min_trust = min(trust_of(r) for r in story_stream)
    attack_min = min(trust_of(r) for r in attack)
    final_trust = trust_of(story_stream[-1])

    assert min_trust < AMBER, "trust must fall below the amber threshold during attack"
    assert final_trust >= GREEN, "trust must recover to the green threshold"
    assert final_trust > attack_min, "trust_after_recovery > trust_during_attack"
    # every post-attack window is better than the worst attack window
    assert min(trust_of(r) for r in post) > attack_min


def test_recovery_redistributes_weights_back(story_stream):
    attack = [r for r in story_stream if r["attack"]]
    post = [r for r in story_stream if not r["attack"] and r["w0"] > attack[-1]["w0"]]
    assert min(gnss_weight_of(r) for r in post) > min(gnss_weight_of(r) for r in attack)
    assert gnss_weight_of(story_stream[-1]) > min(gnss_weight_of(r) for r in attack)


# --------------------------------------------------------------------------- contract plumbing
def test_integration_adapters_are_registered():
    assert not interfaces.MISSING, f"unregistered interfaces: {sorted(interfaces.MISSING)}"


def test_run_observation_message_shape():
    df, _ = make_spoof_scenario(n=200, attack_start=80, attack_end=140)
    msg = run_observation(df.iloc[:WINDOW].reset_index(drop=True))
    assert msg["schema_version"] == "1.0"
    for key in ("scores", "evidence"):
        assert key in msg
    # derived cross-sensor agreement surfaces in the scores block (schema §2)
    t = compute_trust(msg["scores"], [], observations=sensor_observations(
        df, slice(0, WINDOW), rng_seed=1))
    assert "scores" in t
    assert "cross_sensor_agreement" in t["scores"]
