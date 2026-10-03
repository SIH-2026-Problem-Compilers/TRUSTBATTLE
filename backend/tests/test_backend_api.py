from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestHealth:
    def test_root_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_v1_health(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["schema_version"] == "1.0"


class TestTrustEndpoints:
    def test_get_current_trust(self, client):
        r = client.get("/api/v1/trust/current")
        assert r.status_code == 200
        body = r.json()
        assert "trust" in body
        assert "scores" in body
        assert "evidence" in body
        assert "alert" in body
        assert 0 <= body["trust"]["observation_trust"] <= 100

    def test_get_trust_history(self, client):
        r = client.get("/api/v1/trust/history?limit=10")
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        # (may be empty on cold start)
        for p in arr:
            assert "observation_trust" in p
            assert "timestamp" in p

    def test_get_evidence(self, client):
        msg = client.get("/api/v1/trust/current").json()
        oid = msg["observation_id"]
        r = client.get(f"/api/v1/evidence/{oid}")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        for it in items:
            assert "check" in it
            assert "pass" in it


class TestAlerts:
    def test_get_alerts(self, client):
        r = client.get("/api/v1/alerts?active_only=true&limit=20")
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)


class TestTrajectory:
    def test_get_trajectory(self, client):
        r = client.get("/api/v1/trajectory")
        assert r.status_code == 200
        body = r.json()
        for key in ("true_trajectory", "reported_trajectory", "fused_trajectory"):
            assert key in body
            assert isinstance(body[key], list)


class TestDemo:
    def test_start_invalid_scenario(self, client):
        r = client.post("/api/v1/demo/attack/not_a_scenario")
        assert r.status_code == 400

    @pytest.mark.parametrize("scenario", [
        "normal", "gnss_spoof", "replay", "mixed_c20",
    ])
    def test_start_valid_scenario(self, client, scenario):
        r = client.post(f"/api/v1/demo/attack/{scenario}")
        assert r.status_code == 202
        body = r.json()
        assert "session_id" in body
        assert "n_messages" in body
        assert body["n_messages"] > 0


class TestSchemaCompliance:
    """All responses must match data_schema.md §2 at the top-level keys."""

    def test_trust_message_keys(self, client):
        body = client.get("/api/v1/trust/current").json()
        for key in ("schema_version", "scores", "evidence", "trust", "alert"):
            assert key in body, f"missing key {key} from data_schema.md §2"

    def test_trust_subkeys(self, client):
        t = client.get("/api/v1/trust/current").json()["trust"]
        for key in ("observation_trust", "sensor_weights", "state_estimate"):
            assert key in t, f"trust.{key} required by schema §2"

    def test_alert_subkeys(self, client):
        a = client.get("/api/v1/trust/current").json()["alert"]
        for key in ("level", "message", "possible_causes"):
            assert key in a, f"alert.{key} required by schema §2"

    def test_score_convention(self, client):
        """scores.*_consistency / *_integrity 0-1; observation_trust 0-100."""
        m = client.get("/api/v1/trust/current").json()
        for k in ("physical_consistency", "temporal_consistency",
                  "network_integrity", "cross_sensor_agreement"):
            v = m["scores"].get(k)
            if v is not None:
                assert 0 <= v <= 1, f"{k} must be 0-1"
        assert 0 <= m["trust"]["observation_trust"] <= 100

    def test_alert_level_values(self, client):
        level = client.get("/api/v1/trust/current").json()["alert"]["level"]
        assert level in {"GREEN", "AMBER", "RED"}
