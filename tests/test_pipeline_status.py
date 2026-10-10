"""Pipeline source diagnostic tests (competition-readiness, Priority 2).

``GET /api/v1/pipeline/status`` must never claim "pipeline" without actually
having run every stage: the self-check executes M1/M2/M3/fusion through the
real integration adapters, and a mock-bound service must report ``source:
"mock"`` so the dashboard can warn loudly.
"""

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


class TestPipelineStatus:
    def test_shape_is_additive_and_safe(self, client):
        r = client.get("/api/v1/pipeline/status")
        assert r.status_code == 200
        body = r.json()
        for key in ("source", "service", "ready", "missing_modules",
                    "registered_adapters", "self_check", "python_executable"):
            assert key in body, f"missing diagnostic key {key}"
        assert body["source"] in {"pipeline", "mock"}

    def test_self_check_actually_runs_every_stage(self, client):
        """The self-check must execute M1/M2/M3/fusion, not just report flags."""
        sc = client.get("/api/v1/pipeline/status").json()["self_check"]["stages"]
        for stage in ("m1_physical", "m2_temporal", "m3_trust", "fusion"):
            assert isinstance(sc.get(stage), bool), f"{stage} not reported"
            assert sc.get(stage) is True, f"stage {stage} failed: {sc}"
        # a real computed trust value in the 0-100 convention
        assert 0 <= sc["trust_value"] <= 100

    def test_all_adapters_registered_when_pipeline(self, client):
        body = client.get("/api/v1/pipeline/status").json()
        if body["source"] == "pipeline":
            assert body["missing_modules"] == []
            for name in ("score_physical", "score_temporal", "compute_trust", "fuse"):
                assert name in body["registered_adapters"]

    def test_mock_service_is_reported_as_mock(self, client, monkeypatch):
        """A mock-bound runtime must say so (dashboard shows the red banner)."""
        import backend.app.api.v1 as v1
        from backend.app.services.trust_service import MockTrustService

        monkeypatch.setattr(v1, "get_trust_service", lambda: MockTrustService())
        body = client.get("/api/v1/pipeline/status").json()
        assert body["source"] == "mock"
        assert body["service"] == "MockTrustService"
        # even in mock mode the self-check still reports the TRUE stage results
        assert "stages" in body["self_check"]

    def test_existing_endpoints_unchanged_by_diagnostic(self, client):
        """Additive endpoint must not disturb the documented formats."""
        h = client.get("/api/v1/health")
        assert h.status_code == 200 and h.json()["schema_version"] == "1.0"
        t = client.get("/api/v1/trust/current")
        assert t.status_code == 200
        for key in ("schema_version", "scores", "evidence", "trust", "alert"):
            assert key in t.json()
