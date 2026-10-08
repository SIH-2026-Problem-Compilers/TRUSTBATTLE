"""TRUSTBATTLE — real-data ingestion and scoring (M5).

Two real-data paths feed the SAME M1 -> M2 -> M3 pipeline the synthetic
scenarios use, so the model's predictions on the dashboard come out of the
real observation stream, not a scripted story:

1. **Live device GPS** — a client (browser on a phone/laptop) POSTs real
   sensor rows to ``POST /api/v1/real/ingest``. Rows are coerced to the
   shared schema (docs/contracts/data_schema.md §1), persisted to
   ``data/real/device_capture.csv`` (gitignored), and scored in windows of
   up to 50 rows through ``integration.pipeline.run_observation`` +
   ``compute_trust`` (with trust history) + ``fuse``.

2. **Real dataset replay** — ``data/real/*.csv`` files (e.g. converted
   GeoLife GPS trajectories) are precomputed window-by-window through the
   same pipeline and served as playback messages / trajectories so the
   dashboard can stream real-data predictions without a live sensor.

Everything degrades gracefully: if the pipeline modules or real data files
are unavailable, methods return None / fall back so the mock service keeps
the dashboard alive.
"""

from __future__ import annotations

import csv
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from backend.app.models.schemas import (  # noqa: E402
    AlertData,
    EvidenceItem,
    Scores,
    TrajectoryPoint,
    TrajectoryResponse,
    TrustData,
    TrustMessage,
)

REAL_DIR = REPO_ROOT / "data" / "real"
CAPTURE_CSV = REAL_DIR / "device_capture.csv"

# docs/contracts/data_schema.md §1 — column order for captures
SCHEMA_COLUMNS = [
    "timestamp", "sensor_id", "latitude", "longitude", "altitude",
    "velocity", "vx", "vy", "vz", "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z", "heading", "gnss_quality",
    "packet_rate", "packet_delay_ms", "packet_loss",
    "sequence_number", "label", "attack_start",
]
INT_COLUMNS = {"sequence_number", "label", "attack_start"}
STR_COLUMNS = {"sensor_id"}
FLOAT_COLUMNS = [c for c in SCHEMA_COLUMNS if c not in INT_COLUMNS | STR_COLUMNS]

MIN_ROWS_TO_SCORE = 5      # smallest window we will run the pipeline on
SCORE_EVERY_N_ROWS = 10    # score once this many NEW rows arrived
WINDOW_MAX = 50            # same window size as the synthetic pipeline
MAX_ROWS = 20_000          # rolling buffer cap


def coerce_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Coerce loose client dicts to schema-typed rows (defaults where safe)."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            row: Dict[str, Any] = {}
            for c in FLOAT_COLUMNS:
                v = r.get(c, None)
                row[c] = float(v) if v is not None else 0.0
            for c in INT_COLUMNS:
                v = r.get(c, None)
                row[c] = int(float(v)) if v is not None else 0
            row["sensor_id"] = str(r.get("sensor_id") or "device_gnss")
            if pd.isna(row["timestamp"]):
                continue
            out.append(row)
        except (TypeError, ValueError):
            continue
    return out


class RealDataSession:
    """Rolling buffer + pipeline scoring for live real sensor data."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._df = pd.DataFrame(columns=SCHEMA_COLUMNS)
        self._new_since_score = 0
        self._trust_history: List[Dict[str, Any]] = []
        self._reported: List[TrajectoryPoint] = []
        self._fused: List[TrajectoryPoint] = []
        self._messages: List[TrustMessage] = []
        REAL_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # ingest
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        with self._lock:
            self._df = pd.DataFrame(columns=SCHEMA_COLUMNS)
            self._new_since_score = 0
            self._trust_history = []
            self._reported = []
            self._fused = []
            self._messages = []

    def add_rows(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Append real rows, persist capture, score if enough new data."""
        coerced = coerce_rows(rows)
        if not coerced:
            return {"accepted": 0, "total_rows": len(self._df), "trust": None}

        with self._lock:
            new = pd.DataFrame(coerced, columns=SCHEMA_COLUMNS)
            self._df = pd.concat([self._df, new], ignore_index=True)
            if len(self._df) > MAX_ROWS:
                self._df = self._df.iloc[-MAX_ROWS:].reset_index(drop=True)
            self._new_since_score += len(new)
            self._persist(new)
            for r in coerced:
                self._reported.append(TrajectoryPoint(
                    timestamp=r["timestamp"], lat=r["latitude"], lon=r["longitude"],
                    velocity=r["velocity"], altitude=r["altitude"] or None))

            trust: Optional[TrustMessage] = None
            if (self._new_since_score >= SCORE_EVERY_N_ROWS
                    and len(self._df) >= MIN_ROWS_TO_SCORE):
                trust = self._score_locked()
            total = len(self._df)
        return {"accepted": len(coerced), "total_rows": total, "trust": trust}

    def _persist(self, new: pd.DataFrame) -> None:
        try:
            write_header = not CAPTURE_CSV.exists()
            with open(CAPTURE_CSV, "a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if write_header:
                    w.writerow(SCHEMA_COLUMNS)
                for row in new.itertuples(index=False):
                    w.writerow(list(row))
        except OSError:
            pass  # capture persistence is best-effort

    # ------------------------------------------------------------------ #
    # scoring — real rows through the REAL pipeline (M1 -> M2 -> M3)
    # ------------------------------------------------------------------ #
    def _score_locked(self) -> Optional[TrustMessage]:
        try:
            from integration.pipeline import run_observation, temporal_context_rows
            from member3_trust.src.trust_engine import compute_trust
            from member3_trust.src.fusion import fuse

            window = self._df.iloc[-WINDOW_MAX:].reset_index(drop=True)
            self._new_since_score = 0

            # preceding rows -> M2 history (replay/stale seen-before, CR #5)
            start = max(0, len(self._df) - WINDOW_MAX)
            prior = self._df.iloc[max(0, start - temporal_context_rows()):start].reset_index(drop=True)
            result = run_observation(window, prior_rows=prior)
            scores = result.get("scores", {})
            obs = self._observations_locked(window)
            trust_out = compute_trust(scores, self._trust_history, observations=obs)
            result.update(trust_out)
            try:
                state = fuse(obs, result.get("trust", {}))
                result.setdefault("trust", {}).setdefault("state_estimate", {}).update(
                    {k: state[k] for k in ("lat", "lon", "velocity") if k in state})
                result.setdefault("trust", {})["sensor_weights"] = \
                    dict(state.get("weights_used", result.get("trust", {}).get("sensor_weights", {})))
            except (ValueError, KeyError):
                pass

            self._trust_history.append(result)
            if len(self._trust_history) > 200:
                self._trust_history = self._trust_history[-200:]

            msg = TrustMessage(
                schema_version="1.0",
                observation_id=f"real_{uuid.uuid4().hex[:8]}",
                sensor_id="device_gnss",
                timestamp=float(window["timestamp"].iloc[-1]),
                scores=Scores(**result.get("scores", {})),
                evidence=[EvidenceItem(**e) for e in result.get("evidence", [])],
                trust=TrustData(**result.get("trust", {})),
                alert=AlertData(**result.get("alert", {})),
            )
            self._messages.append(msg)
            if len(self._messages) > 500:
                self._messages = self._messages[-500:]

            est = msg.trust.state_estimate
            if isinstance(est, dict) and est.get("lat") is not None:
                self._fused.append(TrajectoryPoint(
                    timestamp=msg.timestamp or time.time(),
                    lat=float(est["lat"]), lon=float(est["lon"]),
                    velocity=float(est.get("velocity") or 0.0)))
            return msg
        except Exception:
            # Pipeline not ready / too few rows for a feature window —
            # ingest still succeeds; prediction comes on a later batch.
            self._new_since_score = 0
            return None

    def _observations_locked(self, window: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """Per-sensor observations from what the device REALLY provides.

        GNSS = reported position. IMU = position propagated from the device's
        motion sensors when the client sent accel data (row accel != 0),
        otherwise omitted — we never fabricate a sensor we do not have.
        """
        last = window.iloc[-1]
        lat, lon = float(last["latitude"]), float(last["longitude"])
        vel = float(last["velocity"])
        obs: Dict[str, Dict[str, Any]] = {
            "gnss": {"sensor_id": "gnss", "lat": lat, "lon": lon, "velocity": vel},
        }
        has_motion = bool(window[["accel_x", "accel_y"]].abs().to_numpy().max() > 1e-9
                          if len(window) else False)
        if has_motion:
            dt = float(window["timestamp"].iloc[-1] - window["timestamp"].iloc[0])
            dt = max(dt, 1e-3)
            # dead-reckon IMU position from mean acceleration of the window
            ax = float(window["accel_x"].mean())
            ay = float(window["accel_y"].mean())
            d = 0.5 * (ax ** 2 + ay ** 2) ** 0.5 * dt * dt
            heading = float(last["heading"] or 0.0)
            import math
            dlat = d * math.cos(math.radians(heading)) / 111_320.0
            dlon = d * math.sin(math.radians(heading)) / (111_320.0 * math.cos(math.radians(lat)))
            obs["imu"] = {"sensor_id": "imu", "lat": lat + dlat, "lon": lon + dlon,
                          "velocity": vel}
        return obs

    # ------------------------------------------------------------------ #
    # queries
    # ------------------------------------------------------------------ #
    @property
    def row_count(self) -> int:
        with self._lock:
            return len(self._df)

    def last_message(self) -> Optional[TrustMessage]:
        with self._lock:
            return self._messages[-1] if self._messages else None

    def trajectory(self) -> TrajectoryResponse:
        with self._lock:
            return TrajectoryResponse(
                true_trajectory=list(self._reported),   # device GPS = reference
                reported_trajectory=list(self._reported),
                fused_trajectory=list(self._fused),
                scenario="real_device_gps",
            )


# --------------------------------------------------------------------------- #
# real dataset replay (data/real/*.csv precomputed through the pipeline)
# --------------------------------------------------------------------------- #
_replay_cache: Dict[str, List[Dict[str, Any]]] = {}
_replay_lock = threading.Lock()


def list_real_datasets() -> List[str]:
    if not REAL_DIR.exists():
        return []
    return sorted(p.stem for p in list(REAL_DIR.glob("*.csv")) + list(REAL_DIR.glob("*.parquet")))


def _load_real_frame(name: str) -> Optional[pd.DataFrame]:
    """Load one data/real dataset, schema-validated when M1's loader exists."""
    if not REAL_DIR.exists():
        return None
    for ext in (".csv", ".parquet"):
        p = REAL_DIR / (name + ext)
        if p.exists():
            try:
                from member1_physical.src import data_loader
                return data_loader.load_data(p)
            except Exception:
                try:
                    return pd.read_csv(p) if ext == ".csv" else pd.read_parquet(p)
                except Exception:
                    return None
    return None


def build_replay_messages(name: str = "geolife",
                          limit_windows: int = 400) -> List[Dict[str, Any]]:
    """Precompute real data -> pipeline TrustMessages for dashboard playback."""
    with _replay_lock:
        if name in _replay_cache:
            return _replay_cache[name]
    df = _load_real_frame(name)
    if df is None or len(df) < 10:
        return []

    msgs: List[Dict[str, Any]] = []
    try:
        from integration.pipeline import run_observation
        from member3_trust.src.trust_engine import compute_trust
        from member3_trust.src.fusion import fuse
    except Exception:
        return []

    history: List[Dict[str, Any]] = []
    WINDOW = 50
    from integration.pipeline import temporal_context_rows
    ctx = temporal_context_rows()
    try:
        for w0 in range(0, min(len(df), WINDOW * limit_windows) - WINDOW + 1, WINDOW):
            window = df.iloc[w0:w0 + WINDOW].reset_index(drop=True)
            # preceding rows -> M2 history (replay/stale seen-before, CR #5)
            prior = df.iloc[max(0, w0 - ctx):w0].reset_index(drop=True)
            result = run_observation(window, prior_rows=prior)
            scores = result.get("scores", {})
            last = window.iloc[-1]
            obs = {"gnss": {"sensor_id": "gnss",
                            "lat": float(last["latitude"]), "lon": float(last["longitude"]),
                            "velocity": float(last["velocity"])},
                   "imu": {"sensor_id": "imu",
                           "lat": float(last["latitude"]), "lon": float(last["longitude"]),
                           "velocity": float(last["velocity"])},
                   "visual": {"sensor_id": "visual",
                              "lat": float(last["latitude"]), "lon": float(last["longitude"]),
                              "velocity": float(last["velocity"])},
                   }
            trust_out = compute_trust(scores, history, observations=obs)
            result.update(trust_out)
            try:
                state = fuse(obs, result.get("trust", {}))
                result.setdefault("trust", {}).setdefault("state_estimate", {}).update(
                    {k: state[k] for k in ("lat", "lon", "velocity") if k in state})
            except (ValueError, KeyError):
                pass
            history.append(result)
            if len(history) > 200:
                history = history[-200:]
            ts = float(window["timestamp"].iloc[-1])
            est = result.get("trust", {}).get("state_estimate", {}) or {}
            msgs.append({
                "observation_id": f"real_{name}_{w0:05d}",
                "sensor_id": "geolife_gnss",
                "timestamp": ts,
                "scores": result.get("scores", {}),
                "evidence": result.get("evidence", []),
                "trust": result.get("trust", {}),
                "alert": result.get("alert", {}),
            })
            if est.get("lat") is None:
                msgs[-1]["trust"].setdefault("state_estimate", {}).update(
                    {"lat": float(last["latitude"]), "lon": float(last["longitude"]),
                     "velocity": float(last["velocity"])})
    except Exception:
        return msgs

    with _replay_lock:
        _replay_cache[name] = msgs
    return msgs


def replay_trajectory(name: str = "geolife") -> TrajectoryResponse:
    """Trajectory built from real dataset rows + pipeline-fused estimates."""
    msgs = build_replay_messages(name)
    df = _load_real_frame(name)
    true_t: List[TrajectoryPoint] = []
    rep_t: List[TrajectoryPoint] = []
    fus_t: List[TrajectoryPoint] = []
    if df is not None:
        step = max(1, len(df) // 2000)
        for i in range(0, len(df), step):
            r = df.iloc[i]
            ts = float(r["timestamp"])
            true_t.append(TrajectoryPoint(timestamp=ts, lat=float(r["latitude"]),
                                          lon=float(r["longitude"]),
                                          velocity=float(r["velocity"])))
            rep_t.append(TrajectoryPoint(timestamp=ts, lat=float(r["latitude"]),
                                         lon=float(r["longitude"]),
                                         velocity=float(r["velocity"])))
    for m in msgs:
        est = (m.get("trust") or {}).get("state_estimate") or {}
        if est.get("lat") is not None:
            fus_t.append(TrajectoryPoint(timestamp=m["timestamp"],
                                         lat=float(est["lat"]), lon=float(est["lon"]),
                                         velocity=float(est.get("velocity") or 0.0)))
    return TrajectoryResponse(true_trajectory=true_t, reported_trajectory=rep_t,
                              fused_trajectory=fus_t, scenario=f"real_{name}")


# module-level singleton (one live ingest session per backend process)
_session = RealDataSession()


def get_real_session() -> RealDataSession:
    return _session
