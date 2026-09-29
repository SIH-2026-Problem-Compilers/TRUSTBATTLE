"""TRUSTBATTLE — Member 1 physics feature extraction.

Layer 1 of about_project.txt §7: physics/state-consistency features computed
from the shared telemetry schema (data_schema.md §1).

Contract (module_interfaces.md, "Owned by Member 1"):
    extract_physical_features(df) -> df
Exact name and signature — Member 3's tooling imports it.

Design notes
------------
* The schema's telemetry row carries the navigation state reported by the
  platform (GNSS position/velocity/heading) plus raw IMU rates
  (accel_*, gyro_*). We treat the reported kinematics as the "GNSS claim"
  and integrate the IMU forward to check whether the motion supports it.
* All added feature columns are prefixed ``m1_`` so M1 output columns can
  never collide with another member's columns in data/processed/.
* The function is pure (no side effects) and never mutates the input frame.
* IMU integration is anchored to the reported state at the start of the track
  and re-anchored after any timestamp gap (replay/re-start), so a single
  stale window cannot poison the whole trajectory.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

# Scales used to normalize disagreement features to ~[0, 1]. These mirror the
# evidence thresholds in configs/settings.yaml (physical.checks.*).
_VELOCITY_SCALE_MPS = 22.0     # historical max speed example (about_project §7)
_HEADING_SCALE_DEG = 30.0      # typical heading-residual scale
_DT_GAP_FACTOR = 5.0           # dt larger than median*dt*factor => track gap

# Leak-anchored IMU dead reckoning (mirrors settings.yaml physical.velocity_anchor):
# the IMU-integrated velocity is pulled toward the reported velocity with time
# constant tau — but ONLY while reported accelerations agree (|a_kin - a_imu| <
# gate, compared after a short median filter). On clean data this bounds the
# integration drift; during spoof/malfunction the gate closes and the
# disagreement survives instead of being absorbed into the anchor.
_ANCHOR_TAU_S = 5.0   # clean-data drift ≈ bias·τ/dt; short τ keeps it sub-m/s
_ANCHOR_GATE_MPS2 = 0.5
_ANCHOR_MEDIAN_K = 5
_MIN_COURSE_SPEED_MPS = 1.5  # below this speed course/heading is noise (mirrors settings)

FEATURE_COLUMNS: List[str] = [
    "m1_dt_s",
    "m1_speed_mps",
    "m1_speed_excess_mps",
    "m1_position_residual_m",
    "m1_velocity_residual_mps",
    "m1_accel_residual_mps2",
    "m1_heading_residual_deg",
    "m1_course_heading_residual_deg",
    "m1_speed_component_residual_mps",
    "m1_accel_mag_mps2",
    "m1_heading_rate_deg_s",
    "m1_smoothness_heading_deg_s",
    "m1_smoothness_accel_mps2",
    "m1_traj_deviation_m",
    "m1_traj_deviation_sigma",
    "m1_gnss_imu_disagreement",
    "m1_sensor_disagreement",
    "m1_gnss_quality",
]

_SMOOTH_WINDOW = 21  # ~2 s at the 10 Hz base rate (settings.simulation.base_frequency_hz)


def _wrap_deg(x: np.ndarray) -> np.ndarray:
    """Wrap angles in degrees to (-180, 180]."""
    return (np.asarray(x, dtype=float) + 180.0) % 360.0 - 180.0


def _safe_diff(x: np.ndarray) -> np.ndarray:
    """First difference with 0 for the first element."""
    d = np.diff(x, prepend=x[:1]) if len(x) else x.copy()
    return d


def _finite(x: np.ndarray, fill: float = 0.0) -> np.ndarray:
    """Replace NaN/inf with *fill*."""
    return np.nan_to_num(np.asarray(x, dtype=float), nan=fill, posinf=fill, neginf=fill)


def _imu_forward_heading(gyro_z: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """Dead-reckoned heading change (deg) from the IMU z gyro."""
    dpsi = np.rad2deg(_finite(gyro_z)) * _finite(dt)
    return np.cumsum(dpsi)


def extract_physical_features(df: pd.DataFrame, smooth_window: int = _SMOOTH_WINDOW) -> pd.DataFrame:
    """Compute per-observation physics-consistency features (contract function).

    For every row this derives residuals between the reported navigation state
    (GNSS claim) and the IMU-integrated motion, plus trajectory-shape metrics:

    * position residual: GNSS position vs velocity-propagated (dead-reckoned) position
    * velocity residual: reported speed vs leak-anchored IMU-integrated speed
      (anchoring is gated on acceleration consistency, so spoofing survives)
    * acceleration consistency: kinematic accel (from speed) vs reported IMU accel
    * heading consistency: heading change vs integrated z-gyro, and course-vs-heading
    * trajectory smoothness / deviation: rolling heading-rate and accel dispersion,
      displacement vs velocity-predicted displacement (normalized by robust sigma)
    * GNSS-vs-IMU and sensor-to-sensor disagreement (normalized 0–1)

    Args:
        df: DataFrame following docs/contracts/data_schema.md §1.
        smooth_window: Rolling window (samples) for smoothness features.

    Returns:
        Copy of *df* with additional ``m1_*`` float columns (FEATURE_COLUMNS).
        First row of each track segment carries neutral residuals (0).

    Raises:
        ValueError: If required motion columns are missing.
    """
    need = ["timestamp", "velocity", "heading", "accel_x", "accel_y", "gyro_z"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"extract_physical_features: missing required columns {missing}")

    out = df.copy()
    n = len(out)

    ts = _finite(out["timestamp"].to_numpy(dtype=float))
    lat = _finite(out["latitude"].to_numpy(dtype=float)) if "latitude" in out else np.zeros(n)
    lon = _finite(out["longitude"].to_numpy(dtype=float)) if "longitude" in out else np.zeros(n)
    vel = _finite(out["velocity"].to_numpy(dtype=float))
    vx = _finite(out["vx"].to_numpy(dtype=float)) if "vx" in out else None
    vy = _finite(out["vy"].to_numpy(dtype=float)) if "vy" in out else None
    hdg = _finite(out["heading"].to_numpy(dtype=float))
    acc = np.column_stack([
        _finite(out[c].to_numpy(dtype=float)) for c in ("accel_x", "accel_y", "accel_z")
    ])
    gyro_z = _finite(out["gyro_z"].to_numpy(dtype=float))

    dt = _safe_diff(ts)
    med_dt = float(np.median(dt[dt > 0])) if np.any(dt > 0) else 0.1
    gap = dt > (_DT_GAP_FACTOR * max(med_dt, 1e-6))
    new_track = np.zeros(n, dtype=bool)
    new_track[0] = True
    new_track[1:] |= gap[1:]

    # ---- reported speed (prefer ||(vx,vy,vz)|| over the magnitude field) ----
    if vx is not None and vy is not None:
        vz = _finite(out["vz"].to_numpy(dtype=float)) if "vz" in out else np.zeros(n)
        speed_vec = np.sqrt(vx**2 + vy**2 + vz**2)
        speed_component_residual = np.abs(vel - speed_vec)
        speed = np.where(vel > 0, vel, speed_vec)  # trust the magnitude field; fall back to norm
    else:
        speed_component_residual = np.zeros(n)
        speed = vel

    # ---- dead-reckoned GNSS position from reported velocity ----------------
    # meters-per-degree at the current latitude
    m_per_deg_lat = np.full(n, 111320.0)
    m_per_deg_lon = 111320.0 * np.cos(np.deg2rad(np.clip(lat, -89.5, 89.5)))
    p = np.column_stack([lon * m_per_deg_lon, lat * m_per_deg_lat])          # meters (E, N)
    v2 = np.column_stack([
        speed * np.sin(np.deg2rad(hdg)),
        speed * np.cos(np.deg2rad(hdg)),
    ])
    dp_vel = v2[:-1] * dt[1:, None] if n > 1 else np.zeros((0, 2))
    p_dr = p.copy()
    if n > 1:
        p_dr[1:] = p[:-1] + dp_vel
    position_residual = np.linalg.norm(p[1:] - p_dr[1:], axis=1) if n > 1 else np.zeros(0)
    position_residual = np.concatenate([[0.0], position_residual]) if n > 1 else np.zeros(n)
    position_residual[new_track] = 0.0

    # predicted-vs-actual displacement deviation (same scale as position residual)
    disp_pred = np.linalg.norm(v2[:-1] * dt[1:, None], axis=1) if n > 1 else np.zeros(0)
    disp_pred = np.concatenate([[0.0], disp_pred]) if n > 1 else np.zeros(n)

    # ---- accelerations (kinematic vs IMU) and the anchor gate --------------
    h = np.deg2rad(hdg)
    a_forward = acc[:, 0] * np.cos(h) + acc[:, 1] * np.sin(h)
    a_kin = _safe_diff(speed) / np.where(dt > 1e-6, dt, np.nan)
    a_kin = _finite(a_kin, fill=0.0)
    # short median filters suppress per-sample noise before gating
    a_kin_s = pd.Series(a_kin).rolling(_ANCHOR_MEDIAN_K, center=True, min_periods=1).median().to_numpy()
    a_fwd_s = pd.Series(a_forward).rolling(_ANCHOR_MEDIAN_K, center=True, min_periods=1).median().to_numpy()
    accel_agrees = np.abs(a_kin_s - _finite(a_fwd_s)) < _ANCHOR_GATE_MPS2
    alpha = np.where(accel_agrees & (dt > 1e-6), dt / _ANCHOR_TAU_S, 0.0)

    # ---- IMU dead reckoning: leak-anchored velocity residual ---------------
    # res[k] = (1-alpha[k]) * (res[k-1] + dv_reported[k] - dv_imu[k])
    # Gate open (clean): res stays near 0 (bounded drift). Gate closed
    # (spoof/malfunction): res accumulates the full GNSS-vs-IMU disagreement.
    innov = _safe_diff(speed) - _finite(a_forward) * dt
    vel_res = np.zeros(n)
    r = 0.0
    for k in range(1, n):
        if new_track[k]:
            r = 0.0
        else:
            r = (1.0 - alpha[k]) * (r + innov[k])
        vel_res[k] = r
    velocity_residual = np.abs(vel_res)
    velocity_residual[new_track] = 0.0

    # ---- heading consistency: per-step gyro innovation ----------------------
    # Heading innovations do not accumulate a random walk the way velocity
    # does, so a drift-free per-step comparison is the right check here; a
    # short median filter suppresses single-sample measurement spikes.
    d_hdg_reported = _wrap_deg(_safe_diff(hdg))
    gyro_rate = np.rad2deg(_finite(gyro_z))
    innov_h = _wrap_deg(d_hdg_reported - gyro_rate * dt)
    innov_s = pd.Series(innov_h).rolling(_ANCHOR_MEDIAN_K, center=True, min_periods=1).median().to_numpy()
    heading_residual = np.abs(_finite(innov_s))
    heading_residual[new_track] = 0.0

    # ---- acceleration consistency -----------------------------------------
    accel_residual = np.abs(a_kin - a_forward)
    accel_residual[new_track] = 0.0
    accel_mag = np.linalg.norm(acc, axis=1)

    # ---- course vs heading -------------------------------------------------
    # Preferred: course from the GNSS velocity components (vx, vy) — Doppler-
    # derived and far less noisy than position differencing. Fallback: course
    # from position deltas when the schema row lacks components.
    if vx is not None and vy is not None:
        vz_c = _finite(out["vz"].to_numpy(dtype=float)) if "vz" in out else np.zeros(n)
        course = np.degrees(np.arctan2(vx, vy))
        course_speed = np.hypot(vx, vy)
    else:
        dE = np.diff(p[:, 0], prepend=p[:1, 0])
        dN = np.diff(p[:, 1], prepend=p[:1, 1])
        course = np.degrees(np.arctan2(dE, dN))
        course_speed = np.hypot(dE, dN) / np.where(dt > 1e-6, dt, np.nan)
    move = np.hypot(np.diff(p[:, 0], prepend=p[:1, 0]), np.diff(p[:, 1], prepend=p[:1, 1]))
    course_residual = np.abs(_wrap_deg(course - hdg))
    # median smoothing suppresses residual per-sample noise; sustained
    # disagreement (spoof/conflict) survives the filter
    course_residual = pd.Series(course_residual).rolling(_ANCHOR_MEDIAN_K, center=True, min_periods=1).median().to_numpy()
    course_residual[(course_speed < _MIN_COURSE_SPEED_MPS) | new_track] = 0.0  # course undefined when barely moving

    # ---- trajectory shape --------------------------------------------------
    hdg_rate = _wrap_deg(_safe_diff(hdg)) / np.where(dt > 1e-6, dt, np.nan)
    hdg_rate = _finite(hdg_rate, fill=0.0)
    smooth_h = pd.Series(hdg_rate).rolling(smooth_window, center=True, min_periods=1).std(ddof=0).to_numpy()
    smooth_a = pd.Series(a_forward).rolling(smooth_window, center=True, min_periods=1).std(ddof=0).to_numpy()
    smooth_h = _finite(np.nan_to_num(smooth_h), fill=0.0)
    smooth_a = _finite(np.nan_to_num(smooth_a), fill=0.0)

    # deviation of actual per-step displacement vs velocity-predicted
    # displacement, as a CENTERED robust z-score: raw |move - predicted| has a
    # positive GNSS-noise bias, so we measure deviation from the track's own
    # typical consistency. Sustained corruption shifts the distribution and
    # still scores high.
    dev = np.abs(move - disp_pred)
    med = float(np.median(dev)) if n else 0.0
    dev_centered = np.abs(dev - med)
    mad = float(np.median(dev_centered)) if n else 0.0
    sigma = max(1.4826 * mad, 1e-3)
    dev_sigma = dev_centered / sigma

    # ---- normalized disagreements (0..~1+) ---------------------------------
    vel_dis = np.clip(velocity_residual / _VELOCITY_SCALE_MPS, 0.0, 5.0)
    hdg_dis = np.clip(heading_residual / _HEADING_SCALE_DEG, 0.0, 5.0)
    gnss_imu_dis = 0.5 * vel_dis + 0.5 * hdg_dis
    comp_dis = np.clip(speed_component_residual / _VELOCITY_SCALE_MPS, 0.0, 5.0)
    sensor_dis = np.maximum(gnss_imu_dis, np.maximum(comp_dis, np.clip(course_residual / _HEADING_SCALE_DEG, 0.0, 5.0)))

    # historical-speed context comes from training limits; here expose raw speed
    # excess is filled by physical_module using learned historical max
    speed_excess = np.zeros(n)

    feats = {
        "m1_dt_s": _finite(dt),
        "m1_speed_mps": _finite(speed),
        "m1_speed_excess_mps": _finite(speed_excess),
        "m1_position_residual_m": _finite(position_residual),
        "m1_velocity_residual_mps": _finite(velocity_residual),
        "m1_accel_residual_mps2": _finite(accel_residual),
        "m1_heading_residual_deg": _finite(heading_residual),
        "m1_course_heading_residual_deg": _finite(course_residual),
        "m1_speed_component_residual_mps": _finite(speed_component_residual),
        "m1_accel_mag_mps2": _finite(accel_mag),
        "m1_heading_rate_deg_s": _finite(hdg_rate),
        "m1_smoothness_heading_deg_s": _finite(smooth_h),
        "m1_smoothness_accel_mps2": _finite(smooth_a),
        "m1_traj_deviation_m": _finite(dev),
        "m1_traj_deviation_sigma": _finite(dev_sigma),
        "m1_gnss_imu_disagreement": _finite(gnss_imu_dis),
        "m1_sensor_disagreement": _finite(sensor_dis),
    }
    if "gnss_quality" in out.columns:
        feats["m1_gnss_quality"] = _finite(out["gnss_quality"].to_numpy(dtype=float))
    else:
        feats["m1_gnss_quality"] = np.ones(n)

    for col, arr in feats.items():
        out[col] = arr.astype(float)

    # feature columns must never contain NaN/inf (models and M3 depend on it)
    out[FEATURE_COLUMNS] = out[FEATURE_COLUMNS].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return out


def learned_limits(feature_df: pd.DataFrame, percentile: float = 0.999) -> dict:
    """Robust per-feature limits from clean data (used as 'historical max').

    Args:
        feature_df: Output of :func:`extract_physical_features` on clean data.
        percentile: Quantile used as the historical limit per feature.

    Returns:
        Dict mapping feature name -> historical limit (float).
    """
    limits = {}
    for col in FEATURE_COLUMNS:
        if col in feature_df.columns:
            q = float(feature_df[col].quantile(percentile))
            limits[col] = q if q > 0 else float(feature_df[col].max())
    return limits
