"""TRUSTBATTLE LIVE — controlled live-simulation controller (M5).

The presentation controller for the live demonstration. It generates
CONTROLLED SYNTHETIC INPUT OBSERVATIONS (a clean UAV kinematic track plus a
per-scenario input corruption — replay/stale, telemetry manipulation, sensor
malfunction) and pushes each window through the REAL pipeline:

    generator (input data only) -> run_observation (M1+M2)
        -> sensor_observations -> compute_trust (M3) -> fuse
        -> TrustMessage -> SQLite (via /ws/live) -> WebSocket -> dashboard

The controller controls ONLY the input data. It never sets scores, trust
values, weights or evidence — every number the dashboard shows is computed by
M1/M2/M3. A GNSS SPOOF state simply corrupts the synthetic GNSS position that
M4's ``attack_gnss_spoof`` would inject; the observed trust drop is M3's own
reaction (evidence-driven, §13/§14), not a scripted value.

Reproducibility: one fixed seed (42) drives the base track; per-window RNG is
seeded from (base seed, window index, scenario) so a reset replays the same
demo. No internet access, no external APIs.

Recovery note: M4's spoof ramp keeps GROWING after ``ramp_s`` (unbounded —
correct for sustained-attack evaluation). For the live demo's bounded
NORMAL -> SPOOF -> RECOVERY story the generator caps the ramp at
``ramp_s`` (30 s) and rewinds cleanly when the scenario ends, so the trust
recovery the judge sees is M3's real §13 gradual recovery dynamics.
"""

from __future__ import annotations

import math
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backend.app.models.schemas import (  # noqa: E402
    AlertData,
    EvidenceItem,
    Scores,
    TrajectoryPoint,
    TrustData,
    TrustMessage,
)
from backend.app.services.trust_service import WINDOW  # noqa: E402

DEMO_SEED = 42
BASE_LAT, BASE_LON = 28.61, 77.21   # Delhi-region reference airfield — same
                                    # convention as the M1/M2/M4 data
DEG_TO_M_LAT = 111_320.0

SCENARIOS = {
    "normal",
    "gnss_spoof",
    "replay",
    "telemetry_manip",
    "sensor_malfunction",
}   # scenario keys offered by the LIVE control panel


def _m_per_deg_lon(lat: float) -> float:
    return DEG_TO_M_LAT * math.cos(math.radians(lat))


def _schema_row(t: float, seq: int, lat: float, lon: float,
                vE: float, vN: float, accel: tuple, gyro: tuple,
                gnss_quality: float, packet_delay_ms: float,
                packet_loss: float, label: int) -> Dict[str, Any]:
    speed = math.hypot(vE, vN)
    heading = math.degrees(math.atan2(vE, vN)) % 360.0
    return {
        "timestamp": t,
        "sensor_id": "uav1",
        "latitude": lat,
        "longitude": lon,
        "altitude": 120.0,
        "velocity": speed,
        "vx": vE, "vy": vN, "vz": 0.05,
        "accel_x": accel[0], "accel_y": accel[1], "accel_z": 0.0,
        "gyro_x": gyro[0], "gyro_y": gyro[1], "gyro_z": gyro[2],
        "heading": heading,
        "gnss_quality": gnss_quality,
        "packet_rate": 100.0,
        "packet_delay_ms": packet_delay_ms,
        "packet_loss": packet_loss,
        "sequence_number": seq,
        "label": label,
        "attack_start": 1 if label else 0,
    }


class LiveDemoController:
    """Stateful live-demo controller: scenario + window cursor -> TrustMessage.

    Thread-safe (the /ws/live task, REST handlers and the run_live_demo
    script may all touch it). One instance per backend process.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scenario: str = "normal"
        self._row: int = 0                  # absolute row cursor into the track
        self._epoch: int = 0                # bumped on every reset/scenario switch
        self._events: List[Dict[str, Any]] = []
        self._observations: List[Dict[str, Any]] = []   # last window's rows
        # running state for the track generator + input corruption
        self._rng = np.random.default_rng(DEMO_SEED)
        self._vE = 6.0                      # gentle forward drift (M1 fallback)
        self._vN = 0.0
        self._east = 0.0
        self._north = 0.0
        self._spoof_elapsed = 0.0           # seconds inside current spoof state
        self._t0 = 1_735_600_000.0 + time.time() % 1000.0
        # history buffers for M3 (its own §13 dynamic trust needs them)
        self._trust_history: List[Dict[str, Any]] = []
        self._prior: List[Dict[str, Any]] = []
        self._messages: List[TrustMessage] = []
        self._reported: List[TrajectoryPoint] = []
        self._fused: List[TrajectoryPoint] = []
        self._log("SYSTEM ONLINE — controlled live simulation (seed 42)")

    # ------------------------------------------------------------------ #
    # state / introspection
    # ------------------------------------------------------------------ #
    @property
    def scenario(self) -> str:
        return self._scenario

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def auto_running(self) -> bool:
        """True while the ▶ RUN LIVE DEMO auto sequence is in progress."""
        return getattr(self, "_auto_running", False)

    def status(self) -> Dict[str, Any]:
        """Everything the LIVE status panel + pipeline panel need."""
        with self._lock:
            last = self._messages[-1] if self._messages else None
            trust = last.trust if last else None
            return {
                "mode": "live",
                "scenario": self._scenario,
                "epoch": self._epoch,
                "data_source": "Controlled Live Simulation (fixed seed 42)",
                "pipeline": {
                    "data": True,
                    "m1_physical": last is not None,
                    "m2_temporal": last is not None,
                    "m3_trust": last is not None,
                    "fusion": trust is not None and bool(trust.state_estimate),
                },
                "observation_trust": trust.observation_trust if trust else None,
                "alert_level": last.alert.level if last else None,
                "sensor_trust": dict(trust.sensor_trust) if trust and trust.sensor_trust else {},
                "sensor_weights": dict(trust.sensor_weights) if trust else {},
                "events": list(self._events[-30:]),
                "rows_generated": self._row,
                "auto_running": getattr(self, "_auto_running", False),
            }

    def events(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events[-limit:])

    def trajectory(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "true_trajectory": [p.model_dump() for p in self._reported],
                "reported_trajectory": [p.model_dump() for p in self._reported],
                "fused_trajectory": [p.model_dump() for p in self._fused],
                "scenario": f"live_{self._scenario}",
            }

    # ------------------------------------------------------------------ #
    # control
    # ------------------------------------------------------------------ #
    def set_scenario(self, scenario: str, *, reset_track: bool = False) -> Dict[str, Any]:
        """Switch the controlled INPUT scenario (e.g. start/stop an attack).

        Switching back to ``normal`` (RECOVERY) deliberately does NOT reset
        the track: the story continues on the same stream — the spoof stops,
        clean rows resume and M3's own §13 dynamics recover trust gradually.
        Only RESET regenerates the track from the seed."""
        with self._lock:
            if scenario not in SCENARIOS:
                raise ValueError(f"unknown live scenario '{scenario}'")
            self._epoch += 1
            if reset_track:
                self._reset_track_locked()
            self._scenario = scenario
            self._spoof_elapsed = 0.0
            self._log(f"SCENARIO → {scenario.upper().replace('_', ' ')}")
            return {"scenario": self._scenario, "epoch": self._epoch}

    def reset(self) -> Dict[str, Any]:
        """RESET: fresh track, fresh M3 history, same seed — replayable demo."""
        with self._lock:
            self._epoch += 1
            self._reset_track_locked()
            self._log("SYSTEM RESET — track regenerated from seed 42")
            return {"scenario": self._scenario, "epoch": self._epoch}

    def _reset_track_locked(self) -> None:
        self._rng = np.random.default_rng(DEMO_SEED)
        self._vE, self._vN = 6.0, 0.0
        self._east = self._north = 0.0
        self._spoof_elapsed = 0.0
        self._scenario = "normal"
        self._trust_history = []
        self._prior = []
        self._messages = []
        self._reported = []
        self._fused = []
        # fresh buffer frame (new identity) + IMU dead-reckoner restart
        self._frame = None
        self._buf_pos = 0
        self._history = []
        try:
            from member3_trust.src.eval_scenarios import _reset_imu_state
            _reset_imu_state()
        except Exception:
            pass

    def _log(self, text: str) -> None:
        self._events.append({
            "time": time.strftime("%H:%M:%S"),
            "epoch": self._epoch,
            "scenario": self._scenario,
            "text": text,
        })
        if len(self._events) > 500:
            self._events = self._events[-500:]

    # ------------------------------------------------------------------ #
    # controlled input generation (schema §1 rows)
    # ------------------------------------------------------------------ #
    def _next_rows(self, n: int) -> List[Dict[str, Any]]:
        """Advance the synthetic track *n* rows, applying the current
        scenario's INPUT corruption. Nothing downstream is touched."""
        rows: List[Dict[str, Any]] = []
        rng = self._rng
        fs = 10.0
        dt = 1.0 / fs
        m_per_deg_lon = _m_per_deg_lon(BASE_LAT)
        for _ in range(n):
            t = self._t0 + self._row * dt
            seq = self._row
            accel = (float(rng.normal(0, 0.35)), float(rng.normal(0, 0.35)), 0.0)
            gyro = (float(rng.normal(0, 0.02)), float(rng.normal(0, 0.02)),
                    float(rng.normal(0, 0.02)))
            self._vE += accel[0] * dt
            self._vN += accel[1] * dt
            self._east += self._vE * dt
            self._north += self._vN * dt
            lat = BASE_LAT + self._north / DEG_TO_M_LAT
            lon = BASE_LON + self._east / m_per_deg_lon
            row = _schema_row(t, seq, lat, lon, self._vE, self._vN, accel, gyro,
                              float(np.clip(rng.normal(0.95, 0.03), 0.0, 1.0)),
                              20.0, 0.0, 0)
            sc = self._scenario
            if sc == "gnss_spoof":
                # M4 attack_gnss_spoof semantics (§7): reported position drifts
                # east at offset/ramp rate; velocity grows with it; IMU fields
                # stay truthful. Ramp CAPPED at 30 s for the bounded demo story.
                self._spoof_elapsed += dt
                ramp_s = 30.0
                offset = 150.0
                frac = min(self._spoof_elapsed / ramp_s, 1.0)
                dist = offset * frac
                rate = offset / ramp_s
                lat_s = lat
                lon_s = lon + dist / m_per_deg_lon
                row["latitude"] = lat_s
                row["longitude"] = lon_s
                row["vx"] = row["vx"] + rate
                row["velocity"] = math.hypot(row["vx"], row["vy"])
                row["gnss_quality"] *= 0.6
                row["label"] = 1
            elif sc == "replay":
                # M4 attack_replay semantics: every OTHER row is a verbatim
                # copy of the row ~12 s (121 ticks) earlier — old timestamps,
                # old sequence numbers, stale nav state.
                delay_ticks = 121
                src = max(0, self._row - delay_ticks)
                if self._row % 2 == 1 and src != self._row:
                    old = self._history_row(src)
                    if old is not None:
                        for c in ("timestamp", "latitude", "longitude", "altitude",
                                  "velocity", "vx", "vy", "vz", "heading",
                                  "packet_delay_ms", "sequence_number", "gnss_quality"):
                            row[c] = old[c]
                        row["label"] = 2
            elif sc == "telemetry_manip":
                # M4 attack_telemetry_manipulation semantics: plausible-looking
                # but jointly broken telemetry (seq jumps/repeats, jittered
                # timestamps, noisy packet stats, subtly noisier kinematics).
                row["sequence_number"] = seq + int(rng.choice([3, 5, 3]))
                row["packet_delay_ms"] = float(np.clip(rng.normal(20.0, 12.0), 1.0, None))
                row["packet_rate"] = max(1.0, 100.0 + float(rng.normal(0, 15.0)))
                row["timestamp"] = t + float(rng.normal(0, 0.03))
                row["latitude"] += float(rng.normal(0, 9.0)) / DEG_TO_M_LAT
                row["longitude"] += (float(rng.normal(0, 9.0)) / m_per_deg_lon)
                row["velocity"] = max(0.0, row["velocity"] + float(rng.normal(0, 1.5)))
                row["label"] = 3
            elif sc == "sensor_malfunction":
                # M4 attack_sensor_malfunction semantics: IMU accel bias ramps
                # up and the REPORTED nav integrates the faulty IMU (GNSS stays
                # truthful) — GNSS-vs-IMU disagreement; stuck accel stretches.
                bias = 1.2 * min(self._spoof_elapsed / 10.0, 1.0)
                self._spoof_elapsed += dt
                ax = accel[0] + bias
                ay = accel[1] + 0.3 * bias
                if int(self._row) % 200 < 15:      # stuck values ~1.5 s stretch
                    ax, ay = float(rng.normal(0, 0.02)), float(rng.normal(0, 0.02))
                self._vE += (ax - accel[0]) * dt   # faulty integration on top
                self._vN += (ay - accel[1]) * dt
                row["accel_x"], row["accel_y"] = ax, ay
                row["label"] = 5
            rows.append(row)
            self._row += 1
        self._history: List[Dict[str, Any]] = getattr(self, "_history", [])
        self._history.extend(rows)
        if len(self._history) > 4000:
            self._history = self._history[-4000:]
        return rows

    def _history_row(self, src: int) -> Optional[Dict[str, Any]]:
        h = getattr(self, "_history", [])
        if 0 <= src < len(h):
            return h[src]
        return None

    # ------------------------------------------------------------------ #
    # one live step: generate window -> REAL M1 -> M2 -> M3 -> fusion
    # ------------------------------------------------------------------ #
    # M3's IMU dead-reckoner is keyed to DataFrame identity (it integrates
    # accel across windows). The live generator therefore fills a single
    # preallocated buffer IN PLACE and scores windows from it, so the
    # dead-reckoned IMU genuinely diverges from a spoofed GNSS track —
    # exactly the cross-sensor evidence the demo must show.
    BUFFER_ROWS = 1200

    def _ensure_buffer(self) -> None:
        from member3_trust.src.eval_scenarios import _reset_imu_state
        if getattr(self, "_frame", None) is None:
            self._frame = pd.DataFrame(
                columns=list(_schema_row(0.0, 0, 0.0, 0.0, 0.0, 0.0,
                                         (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                         0.0, 0.0, 0.0, 0).keys()))
            self._buf_pos = 0              # rows currently written in the buffer
            _reset_imu_state()

    def step(self) -> TrustMessage:
        """Generate one window of controlled input and score it through the
        REAL pipeline. Returns the TrustMessage the dashboard will show."""
        from integration.pipeline import run_observation, temporal_context_rows
        from integration import interfaces
        from member3_trust.src.eval_scenarios import (
            sensor_observations, _reset_imu_state)

        with self._lock:
            self._ensure_buffer()
            if self._buf_pos + WINDOW > self.BUFFER_ROWS:
                # buffer full: start a fresh pass (reproducible — the RNG
                # state continues, the IMU dead-reckoner restarts)
                self._frame = None
                self._buf_pos = 0
                _reset_imu_state()
                self._ensure_buffer()
            new_rows = self._next_rows(WINDOW)
            for i, row in enumerate(new_rows):
                self._frame.loc[self._buf_pos + i] = list(row.values())
            start = self._buf_pos
            end = start + WINDOW
            self._buf_pos = end
            window = self._frame.iloc[start:end]
            ctx = temporal_context_rows()
            p0 = max(0, start - ctx)
            prior = self._frame.iloc[p0:start] if start > p0 else None

            # ---- REAL M1 + M2 -------------------------------------------
            result = run_observation(window, prior_rows=prior)
            scores = dict(result.get("scores", {}))

            # ---- per-sensor observations (same derivation as M3 eval) ----
            obs = sensor_observations(self._frame, slice(start, end),
                                      rng_seed=DEMO_SEED + self._row,
                                      scores=scores)

            # ---- REAL M3 -------------------------------------------------
            trust_out = interfaces.compute_trust(scores, self._trust_history,
                                                 observations=obs)
            result["scores"] = {**scores, **trust_out.get("scores", {})}
            result["evidence"] = list(result.get("evidence", [])) + list(trust_out.get("evidence", []))
            result["trust"] = trust_out.get("trust", {})
            result["alert"] = trust_out.get("alert", {})
            self._trust_history.append(trust_out)
            if len(self._trust_history) > 200:
                self._trust_history = self._trust_history[-200:]

            # ---- REAL trust-aware fusion ---------------------------------
            try:
                state = interfaces.fuse(obs, result["trust"])
                result["trust"].setdefault("state_estimate", {}).update(
                    {k: state[k] for k in ("lat", "lon", "velocity") if k in state})
            except Exception as exc:
                print(f"[live_demo] fusion failed: {exc}", file=sys.stderr)

            last = new_rows[-1]
            msg = TrustMessage(
                schema_version="1.0",
                observation_id=f"live_{self._row:06d}",
                sensor_id="uav1",
                timestamp=float(last["timestamp"]),
                scores=Scores(**result.get("scores", {})),
                evidence=[EvidenceItem(**e) for e in result.get("evidence", [])],
                trust=TrustData(**result.get("trust", {})),
                alert=AlertData(**result.get("alert", {})),
            )
            self._messages.append(msg)
            if len(self._messages) > 500:
                self._messages = self._messages[-500:]

            est = msg.trust.state_estimate or {}
            self._reported.append(TrajectoryPoint(
                timestamp=msg.timestamp or 0.0, lat=float(last["latitude"]),
                lon=float(last["longitude"]), velocity=float(last["velocity"])))
            if est.get("lat") is not None:
                self._fused.append(TrajectoryPoint(
                    timestamp=msg.timestamp or 0.0, lat=float(est["lat"]),
                    lon=float(est["lon"]),
                    velocity=float(est.get("velocity") or 0.0)))
            if len(self._reported) > 400:
                self._reported = self._reported[-400:]
                self._fused = self._fused[-400:]

            # ---- state-transition event log (from ACTUAL computed values) --
            self._log_transitions(msg)
            return msg

    def _log_transitions(self, msg: TrustMessage) -> None:
        """Event log entries derived from real computed state changes."""
        t = msg.trust
        level = msg.alert.level
        prev = self._messages[-2] if len(self._messages) >= 2 else None
        prev_level = prev.alert.level if prev else None
        prev_w = (prev.trust.sensor_weights.get("gnss") if prev and prev.trust
                  else None)
        w_gnss = t.sensor_weights.get("gnss")
        prev_trust = prev.trust.observation_trust if prev and prev.trust else None

        if prev_level and level != prev_level:
            self._log(f"ALERT LEVEL {prev_level} → {level}")
        if prev_trust is not None and w_gnss is not None and prev_w is not None \
                and w_gnss < prev_w * 0.9 and self._scenario != "normal":
            self._log(f"GNSS WEIGHT REDUCED ({prev_w:.3f} → {w_gnss:.3f})")
        if prev_trust is not None and msg.trust.observation_trust < prev_trust * 0.75:
            self._log(f"OVERALL TRUST DROPPING ({prev_trust:.0f} → "
                      f"{msg.trust.observation_trust:.0f})")
        if prev_trust is not None and msg.trust.observation_trust > prev_trust + 2 \
                and self._scenario == "normal" and prev_trust < 85:
            self._log(f"TRUST RECOVERING ({prev_trust:.0f} → "
                      f"{msg.trust.observation_trust:.0f})")

    # ------------------------------------------------------------------ #
    # auto sequence (PHASE 1-4) — drives the INPUT scenario only
    # ------------------------------------------------------------------ #
    def run_auto(self, phases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Spawn a background thread that walks NORMAL → GNSS SPOOFING →
        RECOVERY (NORMAL) → HOLD. Each phase just switches the controlled
        input scenario; every trust number remains M3's computed output."""
        if phases is None:
            phases = [
                {"scenario": "normal", "seconds": 10.0, "label": "PHASE 1 — NORMAL"},
                {"scenario": "gnss_spoof", "seconds": 18.0,
                 "label": "PHASE 2 — GNSS SPOOFING"},
                {"scenario": "normal", "seconds": 15.0,
                 "label": "PHASE 3 — RECOVERY (attack stopped)"},
                {"scenario": "normal", "seconds": 5.0, "label": "PHASE 4 — HOLD NORMAL"},
            ]
        with self._lock:
            self._epoch += 1
            self._reset_track_locked()
            self._log("AUTO DEMO START — controlled sequence "
                      "(NORMAL → GNSS SPOOF → RECOVERY)")

        def _runner() -> None:
            self._auto_running = True
            try:
                for ph in phases:
                    try:
                        self.set_scenario(ph["scenario"])
                    except ValueError:
                        return
                    self._log(ph["label"])
                    deadline = time.time() + float(ph["seconds"])
                    while time.time() < deadline:
                        try:
                            self.step()
                        except Exception as exc:
                            print(f"[live_demo] auto step failed: {exc}", file=sys.stderr)
                            return
                        time.sleep(0.5)   # ~2 windows/s — visible but not overwhelming
                self._log("AUTO DEMO COMPLETE — system NORMAL")
            finally:
                self._auto_running = False

        threading.Thread(target=_runner, daemon=True, name="live-demo-auto").start()
        return {"started": True, "phases": len(phases)}


_controller: Optional[LiveDemoController] = None
_controller_lock = threading.Lock()


def get_live_controller() -> LiveDemoController:
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = LiveDemoController()
        return _controller
