"""Cross-module tests for the Step-3 context wiring (CR #5).

* ``temporal_context_rows()`` reads ``configs/settings.yaml → temporal.context_rows``;
* ``score_window`` / ``run_observation`` forward preceding rows to M2 as its
  ``history`` (replay/stale seen-before evidence) while keeping the original
  no-context call shape;
* the §22 demo-mode scenario (Step 11) opens a real-pipeline session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integration import interfaces                        # noqa: E402
from integration.pipeline import (                        # noqa: E402
    register_available_implementations,
    run_observation,
    score_window,
    temporal_context_rows,
)


def test_context_rows_from_config():
    """The context length is a settings.yaml tunable, not a code constant."""
    rows = temporal_context_rows()
    assert rows >= 121, "must cover attacks.replay.delay_s = 12 s = 121 ticks"
    # config value is what the helper reports
    import yaml
    cfg = yaml.safe_load((REPO_ROOT / "configs" / "settings.yaml")
                         .read_text(encoding="utf-8"))
    assert rows == int(cfg["temporal"]["context_rows"])


def test_score_window_forward_history(monkeypatch):
    """score_window must pass prior rows to M2 as history= (CR #5)."""
    register_available_implementations()
    seen = {}

    def fake_temporal(window_df, history=None):
        seen["history"] = history
        return {"scores": {"temporal_consistency": 1.0,
                           "anomaly_temporal": 0.0,
                           "network_integrity": 1.0},
                "evidence": []}

    def fake_physical(window_df):
        return {"scores": {"physical_consistency": 1.0,
                           "anomaly_physical": 0.0}, "evidence": []}

    monkeypatch.setitem(interfaces._REGISTRY, "score_temporal", fake_temporal)
    monkeypatch.setitem(interfaces._REGISTRY, "score_physical", fake_physical)
    win = pd.DataFrame([{"timestamp": 1.0}])
    prior = pd.DataFrame([{"timestamp": 0.0}])
    out = score_window(win, prior_rows=prior)
    assert seen["history"] is prior
    assert "temporal_consistency" in out["scores"]
    assert "evidence" in out

    # without prior rows the original no-context call shape is kept
    out2 = score_window(win)
    assert seen["history"] is None


def test_run_observation_forwards_prior_rows(monkeypatch):
    register_available_implementations()
    seen = {}

    def fake_temporal(window_df, history=None):
        seen["history"] = history
        return {"scores": {"temporal_consistency": 1.0}, "evidence": []}

    def fake_physical(window_df):
        return {"scores": {"physical_consistency": 1.0}, "evidence": []}

    monkeypatch.setitem(interfaces._REGISTRY, "score_temporal", fake_temporal)
    monkeypatch.setitem(interfaces._REGISTRY, "score_physical", fake_physical)
    win = pd.DataFrame([{"timestamp": 1.0}])
    prior = pd.DataFrame([{"timestamp": 0.0}])
    msg = run_observation(win, prior_rows=prior)
    assert seen["history"] is prior
    assert msg["schema_version"] == "1.0"
    assert "scores" in msg and "evidence" in msg


def test_context_scoring_end_to_end_no_crash():
    """Real M1+M2 through score_window with 150 rows of context (no history
    TypeError, schema-§2 keys present)."""
    register_available_implementations()
    from member2_temporal.src.fallback_data import make_normal
    df = make_normal(400, seed=3)
    win = df.iloc[200:250].reset_index(drop=True)
    prior = df.iloc[50:200].reset_index(drop=True)
    out = score_window(win, prior_rows=prior)
    s = out["scores"]
    for key in ("physical_consistency", "temporal_consistency",
                "network_integrity"):
        assert key in s, key
        assert 0.0 <= float(s[key]) <= 1.0
    assert out["evidence"]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    return TestClient(app)


class TestDemoStoryEndpoint:
    """Step 11 — dashboard demo mode serves the §22 story via the real pipeline."""

    def test_demo_story_scenario_accepted(self, client):
        r = client.post("/api/v1/demo/attack/demo_story")
        assert r.status_code == 202
        body = r.json()
        assert body["scenario"] == "demo_story"
        assert body["source"] == "pipeline"      # NOT the mock story
        assert body["n_messages"] > 30           # clean + attack + recovery

    def test_demo_story_advances_through_trust_drop(self, client):
        r = client.post("/api/v1/demo/attack/demo_story")
        sid = r.json()["session_id"]
        trusts = []
        for _ in range(40):
            adv = client.post(f"/api/v1/demo/advance/{sid}")
            assert adv.status_code == 200
            msg = adv.json()
            trusts.append(msg["trust"]["observation_trust"])
            # every entry is readable (check/pass/detail, schema §2)
            for e in msg.get("evidence", []):
                assert "check" in e and "pass" in e and "detail" in e
            # M3's explainability entries (Step 9) carry HIGH/MEDIUM/LOW
            m3 = [e for e in msg.get("evidence", [])
                  if e["check"].startswith(("Per-sensor trust",
                                             "Dynamic trust trend",
                                             "Historical reliability"))]
            assert m3, "M3 per-sensor/trend evidence entries missing"
            for e in m3:
                assert e.get("level") in ("HIGH", "MEDIUM", "LOW")
        # §22 story: starts trusted, drops to RED during spoofing, recovers
        assert trusts[0] >= 85
        assert min(trusts[20:36]) <= 40
        assert trusts[-1] > trusts[20:36][0], "must recover after the attack"
