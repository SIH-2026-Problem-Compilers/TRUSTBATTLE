"""Tests for the Step-2/4 evidence-aggregation rules (CR #5).

Covers the configurable rules added on top of the weighted geometric mean:

* corroboration penalty — several independent degraded families amplify;
* primary-channel pull — a sensor cannot out-live its own primary channel;
* recovery ramp — §13 recovery accelerates over consecutive clean windows;
* explainability — every evidence entry carries a HIGH/MEDIUM/LOW level and
  per-sensor trust entries (Step 5/9);
* floor_normalize — fusion weight floor enforced AFTER normalization, Σ=1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from member3_trust.src.fusion import floor_normalize          # noqa: E402
from member3_trust.src.settings import trust_settings         # noqa: E402
from member3_trust.src.trust_engine import (                  # noqa: E402
    _per_sensor_quality,
    compute_trust,
    load_trust_weights,
)


def _quality(scores: dict, agg_overrides: dict | None = None,
             sensor: str = "gnss") -> float:
    """Per-sensor quality for *scores* under the configured (or overridden) rules."""
    agg = dict(trust_settings().get("aggregation") or {})
    if agg_overrides:
        agg.update(agg_overrides)
    doc = load_trust_weights()
    return _per_sensor_quality(scores, doc, agg=agg)[sensor]


# ---------------------------------------------------------------- corroboration
class TestCorroborationPenalty:
    def test_two_degraded_families_amplified_vs_no_penalty(self):
        """With >= min_degraded degraded families the penalty lowers quality."""
        scores = {
            "physical_consistency": 0.60,     # degraded (< 0.75), attr 1.0 -> gnss
            "temporal_consistency": 0.60,     # degraded, attr 0.30 -> gnss
            "network_integrity": 0.96,
        }
        penalized = _quality(scores)
        unpenalized = _quality(scores, {"corroboration_penalty": 1.0})
        assert penalized < unpenalized, "2 degraded families must amplify"

    def test_single_degraded_family_not_penalized(self):
        """Below min_degraded (2) families there is no penalty at all."""
        scores = {
            "physical_consistency": 0.60,     # only ONE degraded family
            "temporal_consistency": 0.97,
            "network_integrity": 0.96,
        }
        penalized = _quality(scores)
        unpenalized = _quality(scores, {"corroboration_penalty": 1.0})
        assert penalized == pytest.approx(unpenalized)

    def test_severe_floor_skips_amplification(self):
        """Already-severe quality (< severe_floor) is not double-punished."""
        scores = {
            "physical_consistency": 0.10,     # severe alone -> q below floor
            "temporal_consistency": 0.60,
            "network_integrity": 0.96,
        }
        penalized = _quality(scores)
        unpenalized = _quality(scores, {"corroboration_penalty": 1.0})
        # base quality is already < severe_floor (0.35) -> penalty gated off
        assert penalized == pytest.approx(unpenalized)


# ------------------------------------------------------------ primary-channel pull
class TestPrimaryChannelPull:
    def test_degraded_primary_pulls_sensor_down(self):
        """network_integrity 0.65 must pull the `net` sensor below its raw mean."""
        scores = {
            "physical_consistency": 0.95,
            "temporal_consistency": 1.00,
            "network_integrity": 0.65,        # net's PRIMARY channel (attr 1.0)
        }
        pulled = _quality(scores, sensor="net")
        raw = _quality(scores, {"primary_blend": 0.0}, sensor="net")
        assert pulled < raw, "a degraded primary channel must pull its sensor down"

    def test_pull_never_raises_quality(self):
        """The pull only ever moves quality DOWN (never launders upward)."""
        for net_q in (0.55, 0.65, 0.80, 0.95):
            scores = {"network_integrity": net_q}
            pulled = _quality(scores, sensor="net")
            raw = _quality(scores, {"primary_blend": 0.0}, sensor="net")
            assert pulled <= raw + 1e-9

    def test_clean_evidence_keeps_high_quality(self):
        """Clean everything -> gnss quality stays well above the GREEN line."""
        scores = {
            "physical_consistency": 0.95,
            "anomaly_physical": 0.05,
            "temporal_consistency": 0.97,
            "anomaly_temporal": 0.03,
            "network_integrity": 0.96,
        }
        assert _quality(scores) >= 0.85


# ----------------------------------------------------------------- recovery ramp
class TestRecoveryRamp:
    def test_clean_streak_accelerates_recovery(self, clean_scores, spoof_scores,
                                              spoof_obs, clean_obs, monkeypatch):
        """After an attack, consecutive clean windows recover FASTER than the
        configured recovery_rate alone (§13: gradual, but not lingering)."""
        import member3_trust.src.trust_engine as te

        # ramp ON (shipped config)
        hist = [te.compute_trust(spoof_scores, [], observations=spoof_obs)
                for _ in range(3)]
        for _ in range(4):
            hist.append(te.compute_trust(clean_scores, hist, observations=clean_obs))
        with_ramp = hist[-1]["trust"]["observation_trust"]

        # ramp OFF: same trajectory, recovery_ramp = 0
        cfg = te.trust_settings()
        cfg = {**cfg, "decay": {**cfg["decay"], "recovery_ramp": 0.0}}
        monkeypatch.setattr(te, "trust_settings", lambda: cfg)
        hist2 = [te.compute_trust(spoof_scores, [], observations=spoof_obs)
                 for _ in range(3)]
        for _ in range(4):
            hist2.append(te.compute_trust(clean_scores, hist2, observations=clean_obs))
        without_ramp = hist2[-1]["trust"]["observation_trust"]

        assert with_ramp > without_ramp, "clean-streak ramp must speed recovery"

    def test_ramp_never_blocks_a_drop(self, clean_scores, spoof_scores,
                                      clean_obs, spoof_obs):
        """The streak only accelerates recovery — a drop is never slowed."""
        hist = [compute_trust(clean_scores, [], observations=clean_obs)
                for _ in range(6)]
        before = hist[-1]["trust"]["observation_trust"]
        dropped = compute_trust(spoof_scores, hist, observations=spoof_obs)
        assert dropped["trust"]["observation_trust"] < before - 20


# ----------------------------------------------------------- explainability (Step 5/9)
class TestExplainability:
    def test_every_evidence_entry_has_level(self, clean_scores, spoof_scores,
                                           spoof_obs):
        for scores, obs in ((clean_scores, None), (spoof_scores, spoof_obs)):
            out = compute_trust(scores, [], observations=obs)
            assert out["evidence"]
            for e in out["evidence"]:
                assert e.get("level") in ("HIGH", "MEDIUM", "LOW"), e

    def test_per_sensor_entries_present(self, clean_scores):
        out = compute_trust(clean_scores, [])
        checks = [e["check"] for e in out["evidence"]]
        sensor_entries = [c for c in checks if c.startswith("Per-sensor trust [")]
        assert len(sensor_entries) >= 4  # gnss, imu, visual, net


# ------------------------------------------------------------------ floor_normalize
class TestFloorNormalize:
    def test_floor_applied_and_sums_to_one(self):
        out = floor_normalize({"a": 0.0, "b": 0.0, "c": 1.0}, 0.05)
        assert abs(sum(out.values()) - 1.0) < 1e-9
        assert all(v >= 0.05 - 1e-12 for v in out.values())

    def test_already_healthy_weights_unchanged_shape(self):
        out = floor_normalize({"a": 0.5, "b": 0.5}, 0.05)
        assert out["a"] == pytest.approx(0.5)
        assert out["b"] == pytest.approx(0.5)

    def test_zero_trust_sensor_still_in_fusion(self, spoof_scores, spoof_obs):
        """A floored sensor keeps a nonzero fusion influence (§14 contract)."""
        out = compute_trust(spoof_scores, [], observations=spoof_obs)
        weights = out["trust"]["sensor_weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert all(w >= 0.05 - 1e-6 for w in weights.values())
