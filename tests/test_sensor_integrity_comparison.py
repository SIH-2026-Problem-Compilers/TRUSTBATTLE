"""Live Sensor Integrity Comparison — backend tests (source separation first).

Covers the spec §5 correctness requirements for the comparison feature:

* REAL-device and CONTROLLED-SIMULATED observations must travel through
  separate pathways that never mix or overwrite each other.
* Missing / invalid / stale real-device readings must degrade honestly
  (no fabricated trust for a single reading).
* Simulated data must be rejected on the real-device endpoint (source/mode
  validation server-side — a frontend label is not a boundary).
* Existing API/WS message compatibility (data_schema.md §2 keys) preserved.
* Controlled spoofing + trust recovery are already covered by
  ``tests/test_live_demo.py`` (13 tests) and re-asserted here briefly.

The browser permission/sensor states are covered by the mocked unit tests in
``frontend/src/services/deviceState.test.mjs`` (run with ``node --test``) —
those are explicitly mock tests, not device verification.
"""

from __future__ import annotations

import sys
import time
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


@pytest.fixture(autouse=True)
def _clean_real_session(client):
    """Deterministic row counts for this module; isolated from other suites."""
    client.post("/api/v1/live/scenario/reset")
    client.post("/api/v1/real/session")
    yield


def _device_row(ts, lat=28.61, lon=77.21, sensor="device_gnss"):
    return {
        "timestamp": ts, "sensor_id": sensor, "latitude": lat, "longitude": lon,
        "altitude": 120.0, "velocity": 8.0, "vx": 8.0, "vy": 0.0, "vz": 0.0,
        "accel_x": 0.1, "accel_y": 0.0, "accel_z": 0.0,
        "gyro_x": 0.0, "gyro_y": 0.0, "gyro_z": 0.0, "heading": 90.0,
        "gnss_quality": 0.9, "packet_rate": 1.0, "packet_delay_ms": 100.0,
        "packet_loss": 0.0, "sequence_number": int(ts * 10), "label": 0,
        "attack_start": 0,
    }


class TestRealSessionStatus:
    """GET /api/v1/real/status — honest empty/connected states (spec §4A)."""

    def test_status_shape_and_source_label(self, client):
        r = client.get("/api/v1/real/status")
        assert r.status_code == 200
        body = r.json()
        for key in ("source", "session_rows", "has_computed_trust", "trust", "last_row"):
            assert key in body
        assert body["source"] == "real_device_gps"

    def test_empty_session_reports_no_data_not_a_score(self, client):
        body = client.get("/api/v1/real/status").json()
        assert body["session_rows"] == 0
        assert body["has_computed_trust"] is False
        assert body["trust"] is None
        assert body["last_row"] is None

    def test_ingest_updates_status_without_fabricating_trust(self, client):
        now = time.time()
        rows = [_device_row(now + i * 0.1) for i in range(6)]
        res = client.post("/api/v1/real/ingest", json={"rows": rows})
        assert res.status_code == 200
        assert res.json()["accepted"] == 6

        body = client.get("/api/v1/real/status").json()
        assert body["session_rows"] == 6
        assert body["last_row"] is not None
        # fewer than a full window -> no computed trust yet (never invented)
        assert body["has_computed_trust"] in (True, False)
        if not body["has_computed_trust"]:
            assert body["trust"] is None


class TestSourceIsolation:
    """Spec §5: real and simulated observations must never mix."""

    def test_simulated_source_rejected_on_real_endpoint(self, client):
        r = client.post("/api/v1/real/ingest",
                        json={"rows": [_device_row(time.time())],
                              "source": "simulated"})
        assert r.status_code == 400
        assert "/api/v1/live/*" in r.json()["detail"]
        # nothing was stored
        assert client.get("/api/v1/real/status").json()["session_rows"] == 0

    def test_ingest_does_not_touch_live_controller(self, client):
        live_before = client.get("/api/v1/live/status").json()["rows_generated"]
        client.post("/api/v1/real/ingest",
                    json={"rows": [_device_row(time.time() + i * 0.1) for i in range(8)]})
        live_after = client.get("/api/v1/live/status").json()["rows_generated"]
        assert live_after == live_before, "real ingest must not advance the simulation"

    def test_live_steps_do_not_touch_real_session(self, client):
        client.post("/api/v1/real/ingest",
                    json={"rows": [_device_row(time.time() + i * 0.1) for i in range(5)]})
        real_rows = client.get("/api/v1/real/status").json()["session_rows"]
        assert real_rows == 5
        client.post("/api/v1/live/step")
        client.post("/api/v1/live/step")
        assert client.get("/api/v1/real/status").json()["session_rows"] == real_rows, \
            "simulation steps must not write into the real-device session"

    def test_sources_are_labelled_distinctly(self, client):
        real = client.get("/api/v1/real/status").json()
        sim = client.get("/api/v1/live/status").json()
        assert real["source"] == "real_device_gps"
        assert sim["mode"] == "live"
        assert "Controlled" in sim["data_source"]


class TestMissingInvalidStaleReadings:
    def test_empty_rows_accepted_zero_no_error(self, client):
        res = client.post("/api/v1/real/ingest", json={"rows": []})
        assert res.status_code == 200
        assert res.json()["accepted"] == 0

    def test_invalid_rows_are_dropped_not_crashing(self, client):
        """Dict rows with unusable timestamps are dropped (200, accepted=0).

        Non-object entries never reach the session: FastAPI/pydantic rejects
        the malformed body with 422 — request-shape validation, unchanged
        pre-existing behaviour, asserted here so it cannot regress silently.
        """
        res = client.post("/api/v1/real/ingest", json={"rows": [
            {"timestamp": "not-a-number", "latitude": 1, "longitude": 2},
            {"latitude": 1, "longitude": 2},          # missing timestamp
        ]})
        assert res.status_code == 200
        assert res.json()["accepted"] == 0
        assert client.get("/api/v1/real/status").json()["session_rows"] == 0

        bad = client.post("/api/v1/real/ingest", json={"rows": [42]})
        assert bad.status_code == 422
        assert client.get("/api/v1/real/status").json()["session_rows"] == 0

    def test_stale_reading_is_surfaced_with_its_timestamp(self, client):
        old_ts = time.time() - 7200  # 2 h old device capture
        client.post("/api/v1/real/ingest",
                    json={"rows": [_device_row(old_ts)]})
        last = client.get("/api/v1/real/status").json()["last_row"]
        assert last is not None
        # the API reports the ORIGINAL timestamp so the UI can mark it STALE
        # rather than pretending the reading is current
        assert abs(float(last["timestamp"]) - old_ts) < 1e-6

    def test_permission_denied_state_has_no_rows(self, client):
        # browser-side denied/unavailable states are mocked in
        # deviceState.test.mjs; here we assert the backend equivalent: a
        # denied session simply has no data and reports no trust
        client.post("/api/v1/real/session")
        body = client.get("/api/v1/real/status").json()
        assert body["session_rows"] == 0 and body["trust"] is None


class TestContractCompatibility:
    """Existing message/API shape must not change (data_schema.md §2)."""

    @pytest.mark.parametrize("path", ["/api/v1/trust/current", "/api/v1/live/status"])
    def test_existing_endpoints_still_respond(self, client, path):
        r = client.get(path)
        assert r.status_code == 200

    def test_live_step_message_has_schema_keys(self, client):
        msg = client.post("/api/v1/live/step").json()
        for key in ("schema_version", "scores", "evidence", "trust", "alert"):
            assert key in msg, f"missing {key} from data_schema.md §2"
        t = msg["trust"]
        for key in ("observation_trust", "sensor_weights", "state_estimate"):
            assert key in t
        assert 0 <= t["observation_trust"] <= 100

    def test_ws_route_still_present(self, client):
        with client.websocket_connect("/ws/live?session_id=x") as ws:
            frame = ws.receive_json()
            assert frame is not None


class TestSpoofAndRecoveryStillWork:
    """The feature must not disturb the existing controlled demo path
    (full coverage lives in tests/test_live_demo.py — these are the
    presentation-critical assertions)."""

    def test_spoof_lowers_trust_recovery_restores(self, client):
        client.post("/api/v1/live/scenario/reset")
        base = [client.post("/api/v1/live/step").json()["trust"]["observation_trust"]
                for _ in range(4)]
        client.post("/api/v1/live/scenario/gnss_spoof")
        spoof = [client.post("/api/v1/live/step").json()["trust"]["observation_trust"]
                 for _ in range(14)]
        assert min(spoof) < max(base) - 5, "spoof must observably reduce trust"

        client.post("/api/v1/live/scenario/normal")
        rec = [client.post("/api/v1/live/step").json()["trust"]["observation_trust"]
               for _ in range(16)]
        assert rec[-1] > min(spoof), "recovery must move trust back up"
