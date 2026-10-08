"""TRUSTBATTLE — Member 3 Trust-Aware Fusion (TASK 3, about_project.txt §14, §20).

Two fusion strategies over the same per-sensor observations:

* **Normal fusion** — every sensor contributes with equal (static) weight.
  This is the project baseline that corrupted information can dominate.
* **Trust-aware fusion** — influence ∝ the sensor's *current* observation
  trust (§14): a suspect source is down-weighted instead of being allowed to
  dominate the final battlefield picture. Weights are floored at
  fusion.min_sensor_weight and normalized to Σ=1.

Contract (module_interfaces.md, "Owned by Member 3"; data_schema.md §2):

    fuse(observations, trust_scores) -> state_estimate
        state_estimate = {"lat", "lon", "velocity"} (+ diagnostic keys)

Also provides :class:`KalmanTracker`, a small constant-velocity Kalman filter
in local ENU metres, used as the smoothing baseline for the §20 comparison
(position/velocity error vs corruption percentage) so both fusion modes are
smoothed identically.

Pure functions; module importable with zero side effects.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from .settings import load_fusion_config, trust_settings

DEG_TO_M_LAT = 111_320.0          # metres per degree latitude (good enough for MVP)
POSITION_KEYS = ("lat", "lon", "velocity")


# ---------------------------------------------------------------------------
# input normalization
# ---------------------------------------------------------------------------
def _as_obs_list(observations: Any) -> List[Dict[str, Any]]:
    """Normalize observations to a list of per-sensor dicts.

    Accepts:
      * a dict {sensor_id: {"lat":.., "lon":.., "velocity":..}},
      * a list of such dicts each carrying a ``sensor_id`` key,
      * a DataFrame-like object with ``sensor_id`` column (rows used as dicts).
    """
    obs_list: List[Dict[str, Any]] = []
    if observations is None:
        return obs_list
    if isinstance(observations, dict):
        if "sensor_id" in observations:              # single observation dict
            obs_list.append(dict(observations))
        else:
            for sensor, ob in observations.items():
                ob = dict(ob)
                ob.setdefault("sensor_id", sensor)
                obs_list.append(ob)
        return obs_list
    # iterable of dicts (or DataFrame rows)
    try:
        iterator: Iterable[Any] = getattr(observations, "to_dict", lambda *a, **k: observations)("records") \
            if hasattr(observations, "to_dict") else list(observations)
    except TypeError:  # pragma: no cover
        iterator = list(observations)
    for ob in iterator:
        if isinstance(ob, dict):
            obs_list.append(dict(ob))
    return obs_list


def _trust_map(trust_scores: Any, sensors: List[str]) -> Dict[str, float]:
    """Normalize trust_scores to {sensor: 0–100}.

    Accepts (in priority order):
      * {sensor: number 0–100}                       — direct per-sensor trust
      * {"trust": {"sensor_trust": {...}}}           — a compute_trust() result
      * {"trust": {"sensor_weights": {...}}}         — weights only: relative
        trust rescaled so the best sensor reads 100 (ordering preserved)
      * a compute_trust() result ({"trust": {...}} / {"trust": {...}, ...})
    Sensors without an entry fall back to the trust_weights.json priors ×100
    (a sensor that never reported stays at its historical reliability).
    """
    from .settings import load_trust_weights

    priors = load_trust_weights()["sensor_priors"]
    fallback = {s: 100.0 * float(priors.get(s, 0.94)) for s in sensors}

    block: Any = trust_scores
    if isinstance(trust_scores, dict) and "trust" in trust_scores and isinstance(
        trust_scores["trust"], dict
    ):
        block = trust_scores["trust"]
    if not isinstance(block, dict):
        return fallback

    sensor_trust = block.get("sensor_trust")
    if isinstance(sensor_trust, dict) and sensor_trust:
        return {s: float(sensor_trust.get(s, fallback[s])) for s in sensors}

    weights = block.get("sensor_weights")
    if isinstance(weights, dict) and weights:
        top = max(float(v) for v in weights.values())
        scale = 100.0 / top if top > 0 else 1.0
        return {s: float(weights.get(s, 0.0)) * scale for s in sensors}

    # last resort: direct numeric entries on the block itself
    direct = {
        s: float(block[s]) for s in sensors
        if s in block and isinstance(block[s], (int, float))
    }
    if direct:
        return {s: direct.get(s, fallback[s]) for s in sensors}
    return fallback


# ---------------------------------------------------------------------------
# weight computation (§14)
# ---------------------------------------------------------------------------
def floor_normalize(raw: Dict[str, float], min_w: float) -> Dict[str, float]:
    """Normalize *raw* to Σ=1 with every weight ≥ ``min_w`` (Step 6).

    The floor is enforced AFTER normalization (re-checked, since the
    redistribution can push other weights down again), so the result is always
    valid: sums to 1, non-negative, never NaN (non-finite inputs are treated
    as 0). Shared by :func:`compute_weights` and the trust engine's
    ``sensor_weights`` so every consumer sees the same guarantee.

    Args:
        raw: {sensor: raw non-negative influence}; values may be 0 or NaN.
        min_weight: minimum per-sensor weight floor (fusion.min_sensor_weight).

    Returns:
        {sensor: weight} summing to 1.0, each ≥ min_w (when len×min_w ≤ 1).
    """
    sensors = list(raw)
    if not sensors:
        return {}
    clean: Dict[str, float] = {}
    for s, v in raw.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            fv = 0.0
        clean[s] = fv if (math.isfinite(fv) and fv > 0.0) else 0.0
    total = sum(clean.values())
    if total <= 0:
        return {s: 1.0 / len(sensors) for s in sensors}
    min_w = max(0.0, min(float(min_w), 1.0 / len(sensors)))
    w = {s: v / total for s, v in clean.items()}
    for _ in range(len(sensors) + 2):
        below = [s for s in w if w[s] < min_w - 1e-12]
        if not below:
            break
        for s in below:
            w[s] = min_w
        others = [s for s in w if s not in set(below)]
        osum = sum(w[s] for s in others)
        if not others or osum <= 0:
            break
        target_free = 1.0 - min_w * len(below)
        for s in others:
            w[s] *= target_free / osum
    return w


def compute_weights(trust_map: Dict[str, float], mode: str,
                    min_weight: float) -> Dict[str, float]:
    """Fusion weights for a mode; Σ = 1, every weight ≥ min_weight.

    Args:
        trust_map: {sensor: trust 0–100} (non-finite/negative treated as 0).
        mode: "trust_aware" (weights ∝ trust) or "normal" (equal weights).
        min_weight: fusion.min_sensor_weight floor — enforced AFTER
            normalization so the guarantee holds on the returned weights.

    Returns:
        {sensor: weight} summing to 1.0, each ≥ min_weight.
    """
    sensors = list(trust_map)
    if not sensors:
        return {}
    if mode == "normal":
        return {s: 1.0 / len(sensors) for s in sensors}
    raw = {s: float(t) / 100.0 for s, t in trust_map.items()}
    return floor_normalize(raw, min_weight)


# ---------------------------------------------------------------------------
# lat/lon helpers (local ENU approximation)
# ---------------------------------------------------------------------------
def latlon_to_xy(lat: float, lon: float, lat0: float, lon0: float) -> Tuple[float, float]:
    """Convert (lat, lon) degrees to local (east, north) metres around a reference."""
    north = (lat - lat0) * DEG_TO_M_LAT
    east = (lon - lon0) * DEG_TO_M_LAT * math.cos(math.radians(lat0))
    return east, north


def xy_to_latlon(east: float, north: float, lat0: float, lon0: float) -> Tuple[float, float]:
    """Convert local (east, north) metres back to (lat, lon) degrees."""
    lat = lat0 + north / DEG_TO_M_LAT
    lon = lon0 + east / (DEG_TO_M_LAT * math.cos(math.radians(lat0)))
    return lat, lon


# ---------------------------------------------------------------------------
# contract entry points
# ---------------------------------------------------------------------------
def fuse(observations: Any, trust_scores: Any,
         mode: Optional[str] = None) -> Dict[str, Any]:
    """Contract function: per-sensor observations + trust → fused state estimate.

    Args:
        observations: dict/list of per-sensor measurements (see _as_obs_list).
            Required keys per sensor: ``lat``, ``lon``; ``velocity`` optional.
        trust_scores: per-sensor trust 0–100 or a compute_trust() result
            (see _trust_map for accepted shapes).
        mode: "trust_aware" | "normal"; default from fusion_config.json.

    Returns:
        state_estimate per schema §2: {"lat", "lon", "velocity"} plus
        additive diagnostics for the dashboard/evaluation:
        {"mode", "weights_used", "sensors_used"}.
    """
    cfg = load_fusion_config()
    if mode is None:
        mode = str(cfg.get("mode", trust_settings()["fusion_mode"]))
    min_weight = float(cfg.get("min_sensor_weight", trust_settings()["min_sensor_weight"]))

    obs_list = _as_obs_list(observations)
    usable = [o for o in obs_list if o.get("lat") is not None and o.get("lon") is not None]
    if not usable:
        raise ValueError("fuse: no observation carries lat/lon")
    sensors = [str(o.get("sensor_id", f"sensor{i}")) for i, o in enumerate(usable)]
    trust = _trust_map(trust_scores, sensors)
    weights = compute_weights(trust, mode, min_weight)

    lat = sum(float(o["lat"]) * weights[s] for o, s in zip(usable, sensors))
    lon = sum(float(o["lon"]) * weights[s] for o, s in zip(usable, sensors))
    if all(o.get("velocity") is not None for o in usable):
        velocity = sum(float(o["velocity"]) * weights[s] for o, s in zip(usable, sensors))
    else:
        vels = [float(o["velocity"]) for o in usable if o.get("velocity") is not None]
        velocity = sum(vels) / len(vels) if vels else 0.0

    return {
        "lat": float(lat),
        "lon": float(lon),
        "velocity": float(velocity),
        "mode": mode,
        "weights_used": {s: round(w, 6) for s, w in weights.items()},
        "sensors_used": sensors,
    }


def fuse_normal(observations: Any) -> Dict[str, Any]:
    """Baseline: normal (equal-weight) fusion regardless of trust (§14)."""
    return fuse(observations, trust_scores={}, mode="normal")


# ---------------------------------------------------------------------------
# Kalman baseline (§20 comparison smoothing)
# ---------------------------------------------------------------------------
class KalmanTracker:
    """Constant-velocity Kalman filter on (east, north) in local metres.

    Fed with per-timestep position measurements, it smooths *either* fusion
    mode identically, giving the fair §20 error comparison. State is
    [x, y, vx, vy]; measurement noise is position-only.
    """

    def __init__(self, lat0: float, lon0: float,
                 meas_var: float = 25.0, process_var: float = 0.5):
        self.lat0, self.lon0 = lat0, lon0
        self.x = np.zeros(4)            # [east, north, v_east, v_north]
        self.P = np.eye(4) * 100.0
        self.meas_var = float(meas_var)
        self.process_var = float(process_var)
        self._initialized = False

    def step(self, lat: float, lon: float, dt: float) -> Tuple[float, float]:
        """Predict + update with one position measurement; returns filtered (east, north)."""
        dt = max(float(dt), 1e-6)
        F = np.array([
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ])
        Q = np.eye(4) * self.process_var * dt
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

        z = np.array(latlon_to_xy(lat, lon, self.lat0, self.lon0))
        if not self._initialized:
            self.x[:2] = z
            self._initialized = True
        H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ])
        R = np.eye(2) * self.meas_var
        y = z - H @ self.x
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ H) @ self.P
        return float(self.x[0]), float(self.x[1])

    @property
    def velocity(self) -> float:
        """Filtered speed magnitude (m/s)."""
        return float(math.hypot(self.x[2], self.x[3]))
