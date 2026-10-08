"""TRUSTBATTLE — Member 3 evaluation scenarios (TASK 5 data source).

M4's attack datasets (``data/attacks/scenario_*.parquet`` +
``scenario_*_ground_truth.csv`` pairs, data_schema.md §5) are the intended
source. Until they land, this module provides a clearly-marked stand-in
generator that follows the M1/M2 fallback precedent:

* schema-§1-compatible frames (combined sensor rows, sensor_id "uav1"),
* clean straight/maneuvering UAV track with §1 fields,
* GNSS spoofing injection using configs/settings.yaml → attacks.gnss_spoof
  (offset_start_m, ramp_s) — the classic "consistent trajectory" spoof:
  GNSS reports a coherent-but-wrong trajectory while IMU stays truthful,
  visible only as GNSS/IMU disagreement,
* controlled corruption-rate sweeps for the §19 experiments
  (0/5/10/20/30% corrupted observations).

Ground-truth *position* (needed for the §20 position-error comparison) is
carried in ``DataFrame.attrs["truth_latitude"/"truth_longitude"]`` — it never
leaks into the schema-§1 columns, so the frames stay contract-pure. The
loader (:func:`load_scenarios`) prefers real M4 data when present and never
writes anywhere outside member3_trust/.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from member3_trust.src.settings import REPO_ROOT, load_settings

SCHEMA_COLUMNS = [
    "timestamp", "sensor_id", "latitude", "longitude", "altitude",
    "velocity", "vx", "vy", "vz",
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "heading", "gnss_quality",
    "packet_rate", "packet_delay_ms", "packet_loss", "sequence_number",
    "label", "attack_start",
]

DATA_ATTACKS_DIR = REPO_ROOT / "data" / "attacks"
DATA_SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"

# Convention note: M1's and M2's interim models are trained on THEIR fallback
# generators (M4's datasets are still empty), so this generator matches their
# track conventions (member1_physical/src/fallback_data.py): ~6 m/s random-walk
# kinematics with accel↔velocity consistency, accel_z = 0, arctan2(vE, vN)
# heading, packet_rate ≈ 100 pps / 20 ms delay / no loss. When M4 ships, ALL
# modules retrain on the same real data and this coupling disappears.
_LAT0, _LON0 = 28.61, 77.21      # same reference airfield as M1's fallback
_FS = 10.0                        # base frequency Hz (configs simulation)
_ACCEL_STD = 0.35                 # m/s^2 random walk (M1 fallback convention)


def _meters_per_deg_lon(lat: float) -> float:
    """Metres per degree longitude at *lat* (spherical approximation)."""
    return 111_320.0 * math.cos(math.radians(lat))


# ---------------------------------------------------------------------------
# clean track generator (schema §1)
# ---------------------------------------------------------------------------
def make_clean_track(n: int = 1600, seed: int = 42) -> pd.DataFrame:
    """Generate a clean schema-§1 UAV track (gentle random-walk kinematics).

    Truth state (before any spoofing) is stored in ``df.attrs`` —
    ``truth_latitude`` / ``truth_longitude`` (degrees) and ``truth_velocity``
    (m/s) — for the §20 error evaluation; it never leaks into schema columns.

    Reported kinematics are the INTEGRATED accel random walk (forward drift
    +6 m/s), so reported velocity, accel and heading are mutually consistent
    — matching the M1/M2 fallback training distribution.

    Args:
        n: Number of rows (one row = one 10 Hz observation).
        seed: RNG seed for reproducibility.

    Returns:
        DataFrame with exactly SCHEMA_COLUMNS; label 0, attack_start 0.
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / _FS
    t = 1_735_600_000.0 + np.arange(n) * dt

    accel = rng.normal(0.0, _ACCEL_STD, size=(n, 2))
    vE = np.cumsum(accel[:, 0]) * dt + 6.0    # gentle forward drift (M1 fallback)
    vN = np.cumsum(accel[:, 1]) * dt
    speed = np.hypot(vE, vN)
    heading = np.degrees(np.arctan2(vE, vN)) % 360.0

    east = np.cumsum(vE) * dt
    north = np.cumsum(vN) * dt
    truth_lat = _LAT0 + north / 111_320.0
    truth_lon = _LON0 + east / _meters_per_deg_lon(_LAT0)

    df = pd.DataFrame({
        "timestamp": t,
        "sensor_id": "uav1",
        "latitude": truth_lat + rng.normal(0, 3.0, n) / 111_320.0,
        "longitude": truth_lon + rng.normal(0, 3.0, n) / _meters_per_deg_lon(_LAT0),
        "altitude": 120.0 + 2.0 * np.sin(np.arange(n) * 0.05),
        "velocity": speed,
        "vx": vE,
        "vy": vN,
        "vz": np.full(n, 0.05),
        "accel_x": accel[:, 0],
        "accel_y": accel[:, 1],
        "accel_z": np.zeros(n),
        "gyro_x": rng.normal(0, 0.02, n),
        "gyro_y": rng.normal(0, 0.02, n),
        "gyro_z": rng.normal(0, 0.02, n),
        "heading": heading,
        "gnss_quality": np.clip(rng.normal(0.95, 0.03, n), 0.0, 1.0),
        "packet_rate": 100.0 + rng.normal(0, 2.0, n),
        "packet_delay_ms": np.full(n, 20.0),
        "packet_loss": np.zeros(n),
        "sequence_number": np.arange(n, dtype=np.int64),
        "label": np.zeros(n, dtype=np.int64),
        "attack_start": np.zeros(n, dtype=np.int64),
    })[SCHEMA_COLUMNS]
    df.attrs["truth_latitude"] = truth_lat
    df.attrs["truth_longitude"] = truth_lon
    df.attrs["truth_velocity"] = speed
    return df


# ---------------------------------------------------------------------------
# spoof / corruption injection (configs attacks.gnss_spoof)
# ---------------------------------------------------------------------------
def inject_spoof(df: pd.DataFrame, start: int, end: Optional[int] = None,
                 offset_m: Optional[float] = None, ramp_s: Optional[float] = None,
                 bearing_deg: float = 90.0, label: int = 1) -> pd.DataFrame:
    """Inject a consistent GNSS spoof into *df* (returns a copy).

    The spoofed GNSS reports a coherent trajectory drifting away from the
    inertial truth at a constant rate (``offset_m`` reached after ``ramp_s``
    and continuing — the unbounded-ramp convention of M1's fallback spoof,
    about_project.txt §7: the claimed trajectory keeps diverging from what
    the IMU supports) while IMU stays truthful — the §1/§22 demo scenario.
    Reported velocity components move with the ramp so the spoofed stream is
    self-consistent, exactly like a well-built spoof must be.

    Args:
        df: Clean schema-§1 frame.
        start: First attacked row index.
        end: One-past-the-last attacked row (default: end of frame).
        offset_m: Final offset in metres (default from settings).
        ramp_s: Ramp duration in seconds (default from settings).
        bearing_deg: Displacement bearing (0=N, 90=E).
        label: schema label for attacked rows (1 = gnss_spoof).

    Returns:
        Copy of *df* with attacked GNSS fields + label/attack_start set.
        Truth position in attrs is untouched.
    """
    cfg = (load_settings().get("attacks") or {}).get("gnss_spoof") or {}
    offset_m = float(cfg.get("offset_start_m", 150.0)) if offset_m is None else float(offset_m)
    ramp_s = float(cfg.get("ramp_s", 30.0)) if ramp_s is None else float(ramp_s)
    end = len(df) if end is None else int(end)

    out = df.copy()
    idx = np.arange(start, min(end, len(df)))
    if len(idx) == 0:
        return out
    t_rel = (idx - start) / _FS
    ramp = t_rel / max(ramp_s, 1e-6)          # unbounded: keeps diverging (§7)
    dist = offset_m * ramp
    rate = offset_m / max(ramp_s, 1e-6) * np.ones_like(t_rel)   # m/s, constant

    brg = math.radians(bearing_deg)
    east_m, north_m = dist * math.sin(brg), dist * math.cos(brg)
    v_east, v_north = rate * math.sin(brg), rate * math.cos(brg)

    lat0 = float(df["latitude"].iloc[start])
    out.loc[idx, "latitude"] = out.loc[idx, "latitude"] + north_m / 111_320.0
    out.loc[idx, "longitude"] = out.loc[idx, "longitude"] + east_m / _meters_per_deg_lon(lat0)
    out.loc[idx, "vx"] = out.loc[idx, "vx"] + v_east
    out.loc[idx, "vy"] = out.loc[idx, "vy"] + v_north
    out.loc[idx, "velocity"] = np.hypot(out.loc[idx, "vx"], out.loc[idx, "vy"])
    out.loc[idx, "vz"] = 0.0
    # degraded reported signal quality during the spoof (M1 fallback convention)
    out.loc[idx, "gnss_quality"] = out.loc[idx, "gnss_quality"] * 0.6
    out.loc[idx, "label"] = label
    out.loc[idx, "attack_start"] = 1
    return out


def make_spoof_scenario(n: int = 3200, attack_start: int = 1000,
                        attack_end: Optional[int] = 1800,
                        seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Demo scenario (§22 story): clean → spoofing → recovery.

    Returns:
        (data, ground_truth) where ground_truth has the §5 columns
        timestamp, sensor_id, label, attack_start.
    """
    df = make_clean_track(n=n, seed=seed)
    df = inject_spoof(df, attack_start, attack_end)
    truth = df[["timestamp", "sensor_id", "label", "attack_start"]].copy()
    return df, truth


def make_corruption_scenario(level_pct: float, n: int = 1600, seed: int = 7,
                             region: Tuple[float, float] = (0.5, 1.0)) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """§19 corruption experiment: ``level_pct`` % of rows in *region* spoofed.

    Corruption forms ONE CONTIGUOUS BLOCK of the requested total length
    (sustained false-data injection, like real attack operations and M4's
    block-based scenarios) — scattered single-row jumps would dilute below
    any window-level detection at low rates. Rows in the block receive the
    full configured offset as a jump (label 1 = gnss_spoof).

    Returns:
        (data, ground_truth) with §5 truth columns.
    """
    df = make_clean_track(n=n, seed=seed)
    lo, hi = int(n * region[0]), int(n * region[1])
    rng = np.random.default_rng(seed + int(level_pct * 1000))
    k = int(round((hi - lo) * level_pct / 100.0))
    if k > 0:
        start = int(rng.integers(lo, hi - k))
        rows = np.arange(start, start + k)
        cfg = (load_settings().get("attacks") or {}).get("gnss_spoof") or {}
        offset = float(cfg.get("offset_start_m", 150.0))
        brg = math.radians(90.0)
        east_m, north_m = offset * math.sin(brg), offset * math.cos(brg)
        df.loc[rows, "latitude"] = df.loc[rows, "latitude"] + north_m / 111_320.0
        df.loc[rows, "longitude"] = df.loc[rows, "longitude"] + east_m / _meters_per_deg_lon(_LAT0)
        df.loc[rows, "label"] = 1
        df.loc[rows, "attack_start"] = 1
    truth = df[["timestamp", "sensor_id", "label", "attack_start"]].copy()
    return df, truth


# ---------------------------------------------------------------------------
# per-sensor fusion observations (MVP simulated sources, §17)
# ---------------------------------------------------------------------------

# IMU dead-reckoning state: persists across sensor_observations calls so the
# IMU position drifts away from a spoof over multiple windows (the §22 story:
# GNSS and IMU start agreeing, then diverge as the spoof accumulates).
_IMU_STATE: Dict[str, Any] = {}


def _reset_imu_state() -> None:
    """Reset IMU dead-reckoning state (called between scenarios)."""
    global _IMU_STATE
    _IMU_STATE = {}


def _get_imu_state(df: pd.DataFrame) -> Dict[str, float]:
    """Get or initialize IMU dead-reckoning state for *df*."""
    global _IMU_STATE
    if not _IMU_STATE or _IMU_STATE.get("_df_id") != id(df):
        # Initialize from first row (assumed clean at scenario start)
        first = df.iloc[0]
        _IMU_STATE = {
            "_df_id": id(df),
            "lat": float(first["latitude"]),
            "lon": float(first["longitude"]),
            "v_x": float(first["vx"]),
            "v_y": float(first["vy"]),
            "last_idx": 0,
        }
    return _IMU_STATE


def truth_positions(df: pd.DataFrame, window: slice) -> Tuple[Optional[float], Optional[float]]:
    """Mean truth (lat, lon) over *window* from attrs (None if unavailable)."""
    tlat, tlon = df.attrs.get("truth_latitude"), df.attrs.get("truth_longitude")
    if tlat is None or tlon is None:
        return None, None
    return float(np.mean(tlat[window])), float(np.mean(tlon[window]))


def sensor_observations(df: pd.DataFrame, window: slice,
                        rng_seed: int = 123,
                        scores: Optional[Dict[str, float]] = None
                        ) -> Dict[str, Dict[str, float]]:
    """Build per-sensor position/velocity observations for one window.

    MVP simulated sources (about_project.txt §17):

    * ``gnss``   — reported GNSS position/velocity (the spoofable source)
    * ``imu``    — dead-reckoned from IMU accel/gyro integration starting
                  from the scenario's first row; drifts away from a spoof over
                  time because accel is not spoofed (§22 story)
    * ``visual`` — independent position estimate: truth (or IMU-based) + noise
                  (corroborates IMU against spoof)
    * ``net``    — excluded (telemetry channel contributes trust, not position)

    With truth attrs (fallback generator) the IMU/visual are anchored to truth
    + calibrated noise. Without truth attrs (M4 real data) the IMU dead-
    reckons from the first row using only accel — this catches a well-built
    GNSS spoof because the spoofed velocity diverges from the accel-integrated
    velocity (see §22 story).

    **Trust-gated aiding (aided-INS, ``trust_engine.estimator_aiding``).**
    When *scores* (this window's M1/M2 evidence) show the reported stream fully
    clean — physical and temporal consistency at/above the degraded threshold
    — yet the dead-reckoned channel has diverged from the reported position by
    more than ``min_disagreement_m``, the divergence is uncorroborated: the
    plausible cause is accumulated inertial drift (e.g. after a sensor-
    malfunction glitch), not a spoofed measurement. The inertial estimate is
    then pulled a bounded fraction (``rate``) toward the reported position and
    velocity each window — the way a GNSS-aided INS re-anchors. A spoofed or
    conflicting GNSS always degrades physical/temporal consistency first, so
    the gate never lets corrupted evidence drag the inertial reference.
    Omit *scores* to disable aiding (pre-existing call sites stay valid).
    Within the same gate, the inertial *speed* (velocity magnitude) is also
    leaked toward the reported speed (``velocity_leak_rate``) every clean
    window — that bounds the dead-reckoner drift at its source, while a
    rotation-only conflict (speed preserved) and a spoofed speed signature
    (gate off) stay fully visible.
    """
    w = df.iloc[window]
    if len(w) == 0:
        return {}
    rng = np.random.default_rng(rng_seed)
    tlat, tlon = truth_positions(df, window)
    m_per_deg_lat = 111_320.0
    has_truth = tlat is not None and tlon is not None
    ref_lat = float(tlat) if has_truth else float(w["latitude"].iloc[0])
    ref_lon = float(tlon) if has_truth else float(w["longitude"].iloc[0])
    m_per_deg_lon = _meters_per_deg_lon(ref_lat)

    # ---- GNSS: reported position/velocity (spoofable) --------------------
    gnss_lat = float(w["latitude"].mean())
    gnss_lon = float(w["longitude"].mean())
    gnss_vel = float(w["velocity"].mean())

    # ---- IMU: dead-reckoned from accel integration -----------------------
    state = _get_imu_state(df)
    dt = 1.0 / _FS
    win_start = int(w.index[0])
    win_end = int(w.index[-1]) + 1
    # Reported epoch = window MEAN (same epoch as the reported GNSS mean, the
    # visual truth-mean, and the evaluation's truth mean). Reporting the
    # dead-reckoner's END-of-window position instead creates a systematic
    # half-window lag (speed x 2.5 s ≈ 37 m at 15 m/s) that reads as
    # cross-sensor disagreement on a perfectly clean, fast track — the
    # dominant part of the "clean-phase IMU-drift artifact"
    # (system_audit.md M3-open). The state itself still integrates to the
    # window end so the next window continues seamlessly.
    start_lat, start_lon = state["lat"], state["lon"]
    start_vx, start_vy = state["v_x"], state["v_y"]
    # Integrate accel from the last processed row to the end of this window
    for i in range(state["last_idx"], win_end):
        if i == 0:
            continue
        state["v_x"] += float(df["accel_x"].iloc[i]) * dt
        state["v_y"] += float(df["accel_y"].iloc[i]) * dt
        d_east = state["v_x"] * dt
        d_north = state["v_y"] * dt
        state["lat"] += d_north / m_per_deg_lat
        state["lon"] += d_east / m_per_deg_lon
    state["last_idx"] = win_end

    # ---- trust-gated aiding of the inertial channel (aided-INS) -----------
    if scores is not None:
        from .settings import trust_settings
        tcfg = trust_settings()
        aid = tcfg.get("estimator_aiding", {}) or {}
        thr = float((tcfg.get("aggregation") or {}).get("degraded_threshold", 0.75))
        phys_ok = ("physical_consistency" not in scores
                   or float(scores["physical_consistency"]) >= thr)
        temp_ok = ("temporal_consistency" not in scores
                   or float(scores["temporal_consistency"]) >= thr)
        gap_e = (gnss_lon - state["lon"]) * m_per_deg_lon
        gap_n = (gnss_lat - state["lat"]) * m_per_deg_lat
        vx_g = float(w["vx"].mean())
        vy_g = float(w["vy"].mean())
        # velocity signature: a spoofed track carries its own velocity, so the
        # reported-vs-inertial velocity gap stays large; drift does not.
        vel_gap = math.hypot(vx_g - state["v_x"], vy_g - state["v_y"])

        # ---- bounded inertial drift: speed damping (scalar leak) -----------
        # Two dead-reckoner error sources exist on a clean track: the
        # end-vs-mean epoch lag (fixed above) and a genuine slow drift that
        # reaches ~25-55 m over 600 s (system_audit.md M3-open), which drags
        # cross-sensor agreement below the degraded threshold on clean data.
        # Leak the inertial speed (SCALAR — magnitude only) toward the
        # reported speed at the same epoch while evidence is clean:
        #   * drift corrupts the integrated speed -> bounded at the source;
        #   * a cross-sensor conflict ROTATES the velocity but preserves
        #     speed -> the leak is a no-op, the step position offset stays
        #     fully visible to cross-sensor agreement;
        #   * a spoof changes the reported speed by ~18 m/s -> gate off
        #     (max_velocity_gap_mps), never dragging the reference.
        speed_ref = math.hypot(float(w["vx"].iloc[-1]), float(w["vy"].iloc[-1]))
        v_now = math.hypot(state["v_x"], state["v_y"])
        leak = float(aid.get("velocity_leak_rate", 0.2))
        if (bool(aid.get("enabled", True)) and phys_ok and temp_ok
                and abs(speed_ref - v_now) <= float(aid.get("max_velocity_gap_mps", 8.0))
                and v_now > 1e-6):
            scale = 1.0 + leak * (speed_ref / v_now - 1.0)
            state["v_x"] *= scale
            state["v_y"] *= scale

        if (bool(aid.get("enabled", True)) and phys_ok and temp_ok
                and vel_gap <= float(aid.get("max_velocity_gap_mps", 8.0))
                and math.hypot(gap_e, gap_n) >= float(aid.get("min_disagreement_m", 60.0))):
            rate = float(aid.get("rate", 0.35))
            state["lat"] += rate * (gnss_lat - state["lat"])
            state["lon"] += rate * (gnss_lon - state["lon"])
            state["v_x"] += rate * (vx_g - state["v_x"])
            state["v_y"] += rate * (vy_g - state["v_y"])

    imu_lat = 0.5 * (start_lat + state["lat"])
    imu_lon = 0.5 * (start_lon + state["lon"])
    # mean velocity over the window (start -> end midpoint), same epoch
    _mvx = 0.5 * (start_vx + state["v_x"])
    _mvy = 0.5 * (start_vy + state["v_y"])
    v_imu = float(np.hypot(_mvx, _mvy))
    # IMU measurement noise (IMU drift)
    if has_truth:
        imu_lat += rng.normal(0, 2.0) / m_per_deg_lat
        imu_lon += rng.normal(0, 2.0) / m_per_deg_lon
    else:
        imu_lat += rng.normal(0, 3.0) / m_per_deg_lat
        imu_lon += rng.normal(0, 3.0) / m_per_deg_lon

    # ---- Visual: independent position estimate ---------------------------
    if has_truth:
        vis_lat = tlat + rng.normal(0, 4.0) / m_per_deg_lat
        vis_lon = tlon + rng.normal(0, 4.0) / m_per_deg_lon
    else:
        vis_lat = imu_lat + rng.normal(0, 10.0) / m_per_deg_lat
        vis_lon = imu_lon + rng.normal(0, 10.0) / m_per_deg_lon
    v_vis = v_imu + rng.normal(0, 1.0)

    return {
        "gnss": {
            "lat": gnss_lat,
            "lon": gnss_lon,
            "velocity": gnss_vel,
        },
        "imu": {"lat": imu_lat, "lon": imu_lon, "velocity": v_imu},
        "visual": {"lat": vis_lat, "lon": vis_lon, "velocity": v_vis},
    }


# ---------------------------------------------------------------------------
# M4 loader preference
# ---------------------------------------------------------------------------
def load_scenarios() -> Tuple[str, List[Tuple[str, pd.DataFrame, pd.DataFrame]]]:
    """Return (source_label, [(name, data, ground_truth), ...]).

    Prefers Member 4's real pairs from data/attacks/ (schema §5); falls back
    to the stand-in generator (spoof demo + corruption sweep) until M4
    ships. Callers rerun unchanged either way.
    """
    if DATA_ATTACKS_DIR.exists():
        pairs = sorted(DATA_ATTACKS_DIR.glob("scenario_*.parquet"))
        if pairs:
            out: List[Tuple[str, pd.DataFrame, pd.DataFrame]] = []
            for pq in pairs:
                gt_path = pq.with_name(pq.stem + "_ground_truth.csv")
                data = pd.read_parquet(pq)
                if gt_path.exists():
                    gt = pd.read_csv(gt_path)
                else:
                    gt = data[["timestamp", "sensor_id", "label", "attack_start"]].copy()
                out.append((pq.stem, data, gt))
            return "Member 4 data (data/attacks/)", out
    scenarios: List[Tuple[str, pd.DataFrame, pd.DataFrame]] = [
        ("fallback_spoof_demo", *make_spoof_scenario()),
    ]
    for level in (0, 5, 10, 20, 30):
        scenarios.append(
            (f"fallback_corruption_{int(level):02d}pct", *make_corruption_scenario(level))
        )
    return ("FALLBACK generator (member3_trust/src/eval_scenarios.py) — "
            "data/attacks/ is empty", scenarios)
