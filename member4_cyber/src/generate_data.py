"""TRUSTBATTLE — Member 4 synthetic UAV telemetry generator (TASK 1).

Simulates a realistic multi-leg UAV mission (straight legs, coordinated
turns, a climb, speed changes) at the configs → simulation settings
(10 Hz, 600 s, seed 42) and emits ALL fields of data_schema.md §1.

Two serializations of the same simulated mission:

* **Fused platform rows (canonical, ``data/synthetic/uav_normal_v1.parquet``)**
  — one row = one platform observation tick (10 Hz) carrying the full §1
  field set (GNSS-reported navigation + IMU + telemetry). This is the format
  Members 1–3's loaders/feature code and the interim models consume, and the
  format of every ``scenario_*.parquet`` (§5 pairs).
* **Per-sensor streams variant** (``member4_cyber/scenarios/…_streams.parquet``)
  — the four streams uav1_gnss / uav1_imu / uav1_visual / uav1_net at their
  configured rates with per-stream sequence counters, as requested by the
  M4 brief. NOT yet consumable by M1/M2 feature code (which assumes fused
  10 Hz rows); a CHANGE_REQUESTS entry proposes the schema clarification.
  It is intentionally kept OUT of data/synthetic/ because M1's
  load_synthetic_directory concatenates every file in that folder.

All randomness is seeded (configs → simulation.random_seed) — datasets are
bit-reproducible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from member4_cyber.src.schema import COLUMNS, FLOAT_COLUMNS, INT_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]

try:  # pyyaml is not in the shared requirements.txt; degrade gracefully
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

_SETTINGS_PATH = REPO_ROOT / "configs" / "settings.yaml"


def simulation_settings() -> Dict[str, Any]:
    """M4-relevant settings from configs/settings.yaml with code defaults."""
    cfg: Dict[str, Any] = {}
    if yaml is not None and _SETTINGS_PATH.exists():
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    sim = cfg.get("simulation") or {}
    sensors = cfg.get("sensors") or {}
    gnss = sensors.get("gnss") or {}
    imu = sensors.get("imu") or {}
    visual = sensors.get("visual") or {}
    return {
        "uav_id": str(sim.get("uav_id", "uav1")),
        "duration_s": float(sim.get("duration_s", 600.0)),
        "fs": float(sim.get("base_frequency_hz", 10.0)),
        "seed": int(sim.get("random_seed", 42)),
        "gnss_noise_std_m": float(gnss.get("noise_std_m", 3.0)),
        "gnss_rate_hz": float(gnss.get("update_rate_hz", 10.0)),
        "imu_accel_noise_std": float(imu.get("accel_noise_std", 0.05)),
        "imu_gyro_noise_std": float(imu.get("gyro_noise_std", 0.01)),
        "imu_rate_hz": float(imu.get("update_rate_hz", 100.0)),
        "visual_rate_hz": float(visual.get("update_rate_hz", 5.0)),
    }


# ---------------------------------------------------------------------------
# mission: straight legs, coordinated turns, a climb, speed changes
# ---------------------------------------------------------------------------
# (east, north) waypoints in metres relative to the launch point, per-leg
# target speed (m/s), altitude target (m). The core route is a ~170 s circuit
# REPEATED 3× so every time slice of the track contains the same mix of
# behaviors (legs/turns/climb) — downstream threshold calibration splits the
# clean data 80/20 and needs every slice to be representative.
_MISSION_LOOP: List[Dict[str, float]] = [
    {"e": 400.0, "n": 0.0, "v": 18.0, "alt": 120.0},    # long straight east
    {"e": 450.0, "n": 250.0, "v": 20.0, "alt": 120.0},  # turn + mild speed-up
    {"e": 200.0, "n": 600.0, "v": 20.0, "alt": 150.0},  # diagonal + climb
    {"e": -250.0, "n": 650.0, "v": 15.0, "alt": 150.0}, # slow leg
    {"e": -450.0, "n": 250.0, "v": 16.0, "alt": 130.0}, # descend a little
    {"e": -100.0, "n": -100.0, "v": 19.0, "alt": 120.0},# return diagonal
]
_MISSION_TAIL = {"e": 400.0, "n": -200.0, "v": 16.0, "alt": 120.0}  # final straight
_MISSION: List[Dict[str, float]] = _MISSION_LOOP * 3 + [_MISSION_TAIL]

_TURN_RATE_DEG_S = 8.0         # coordinated-turn rate cap (banked smoothly)
_LAUNCH_LAT, _LAUNCH_LON = 28.61, 77.21   # reference airfield (synthetic)
_M_PER_DEG_LAT = 111_320.0

# Jerk/rate limits — a real airframe cannot step its acceleration, turn rate
# or climb rate: everything is second-order smooth. Without these, leg/turn
# transitions produce step features (jerk spikes, accel-rate spikes) whose
# heavy tails in CLEAN data inflate downstream anomaly thresholds and mask
# the diluted attacks (M3/M2 evaluation finding, 2026-10-03).
_JERK_MAX_MPS3 = 0.5           # m/s^3
_YAW_ACCEL_MAX = np.radians(4.0)   # rad/s^2
_VZ_ACCEL_MAX = 0.5            # m/s^2


def _m_per_deg_lon(lat: float) -> float:
    """Metres per degree longitude at *lat* (spherical approximation)."""
    return _M_PER_DEG_LAT * np.cos(np.radians(lat))


def simulate_truth(fs: float, duration_s: float,
                   seed: int) -> Dict[str, np.ndarray]:
    """Simulate the TRUE platform state over the mission (no sensor errors).

    Returns arrays (length n = duration*fs): timestamp, east/north (m),
    up (m), velocity components (m/s), speed, heading (deg), plus the
    per-tick true acceleration (m/s^2) and yaw rate (rad/s) the IMU senses.
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * fs))
    dt = 1.0 / fs
    t = 1_735_600_000.0 + np.arange(n) * dt

    east = np.zeros(n)
    north = np.zeros(n)
    up = np.zeros(n)
    alt_arr = np.zeros(n)
    vE = np.zeros(n)
    vN = np.zeros(n)
    speed = np.zeros(n)
    heading = np.zeros(n)
    yaw_rate = np.zeros(n)                 # rad/s

    # current state — airborne start at initial cruise speed; all commands
    # (accel, yaw rate, climb rate) are JERK-LIMITED second-order states
    e, nn, alt = 0.0, 0.0, _MISSION[0]["alt"]
    v_cur = 10.0
    hdg = 90.0                              # start heading east
    wp = 0
    cruise = _MISSION[-1]["v"]
    accel_cur = 0.0
    omega_cur = 0.0
    vz_cur = 0.0

    for i in range(n):
        accel_des, omega_des, vz_des = 0.0, 0.0, 0.0
        if wp < len(_MISSION):
            tgt = _MISSION[wp]
            de, dn = tgt["e"] - e, tgt["n"] - nn
            if float(np.hypot(de, dn)) < max(30.0, v_cur * dt * 5):
                wp += 1
                tgt = _MISSION[wp] if wp < len(_MISSION) else tgt
            if wp < len(_MISSION):
                de, dn = tgt["e"] - e, tgt["n"] - nn
                # bearing toward the waypoint → desired turn rate (≤12°/s)
                brg = float(np.degrees(np.arctan2(de, dn))) % 360.0
                diff = (brg - hdg + 180.0) % 360.0 - 180.0
                turn = float(np.clip(diff, -_TURN_RATE_DEG_S * dt, _TURN_RATE_DEG_S * dt))
                omega_des = np.radians(turn) / dt
                # desired accel toward the leg target speed (≤2 m/s²)
                accel_des = float(np.clip(tgt["v"] - v_cur, -2.0, 2.0))
                # desired climb rate toward the leg altitude (≤2 m/s)
                vz_des = float(np.clip(tgt["alt"] - alt, -2.0, 2.0))
        else:
            # mission complete: hold a wide circle at cruise speed
            omega_des = np.radians(8.0)
            accel_des = float(np.clip(cruise - v_cur, -2.0, 2.0))

        # jerk-limited second-order dynamics
        accel_cur += float(np.clip(accel_des - accel_cur,
                                   -_JERK_MAX_MPS3 * dt, _JERK_MAX_MPS3 * dt))
        omega_cur += float(np.clip(omega_des - omega_cur,
                                   -_YAW_ACCEL_MAX * dt, _YAW_ACCEL_MAX * dt))
        vz_cur += float(np.clip(vz_des - vz_cur,
                                -_VZ_ACCEL_MAX * dt, _VZ_ACCEL_MAX * dt))
        v_cur = max(3.0, v_cur + accel_cur * dt)
        hdg = (hdg + float(np.degrees(omega_cur)) * dt) % 360.0
        up[i] = vz_cur
        yaw_rate[i] = omega_cur

        hdg_rad = np.radians(hdg)
        vE[i] = v_cur * np.sin(hdg_rad)
        vN[i] = v_cur * np.cos(hdg_rad)
        speed[i] = v_cur
        e += vE[i] * dt
        nn += vN[i] * dt
        alt += up[i] * dt
        east[i], north[i] = e, nn
        alt_arr[i] = alt
        heading[i] = hdg

    truth = {
        "timestamp": t,
        "east": east, "north": north, "up": up,
        "vE": vE, "vN": vN,
        "speed": speed, "heading": heading,
        "yaw_rate": yaw_rate,
    }
    # IMU senses the ACTUAL acceleration of the velocity trace (finite
    # difference): tangential + centripetal terms, so reported accel and
    # reported velocity are mutually consistent on clean data — what M1's
    # physics checks compare.
    truth["accel_E"] = np.gradient(vE, dt)
    truth["accel_N"] = np.gradient(vN, dt)
    truth["latitude"] = _LAUNCH_LAT + north / _M_PER_DEG_LAT
    truth["longitude"] = _LAUNCH_LON + east / _m_per_deg_lon(_LAUNCH_LAT)
    truth["altitude"] = alt_arr
    truth["n"] = n
    return truth


def true_position_m(truth: Dict[str, np.ndarray], idx) -> Tuple[float, float]:
    """True (east, north) metres at row *idx* — the reference for attack offsets."""
    return float(truth["east"][idx]), float(truth["north"][idx])


# ---------------------------------------------------------------------------
# sensor models → schema-§1 rows
# ---------------------------------------------------------------------------
def _base_frame(truth: Dict[str, np.ndarray], rng: np.random.Generator,
                s: Dict[str, Any]) -> pd.DataFrame:
    """Assemble the clean fused schema-§1 frame from the true state.

    Sensor models (all noise seeded):
    * GNSS   — position = truth + N(0, gnss_noise_std_m); reports its own
               velocity/heading (same truth here, clean flight);
               quality ~ N(0.95, 0.03) clipped to [0, 1]
    * IMU    — accel/gyro = true values + N(0, configs noise)
    * NET    — packet_rate ~ N(100, 2) pps, delay ~ N(20, 1.5) ms, no loss
    * sequence_number — nav-message counter, strictly +1 per tick
    """
    n = int(truth["n"])
    lat0 = _LAUNCH_LAT
    lon0 = _LAUNCH_LON
    lat = truth["latitude"] + rng.normal(0.0, s["gnss_noise_std_m"], n) / _M_PER_DEG_LAT
    lon = truth["longitude"] + rng.normal(0.0, s["gnss_noise_std_m"], n) / _m_per_deg_lon(lat0)
    quality = np.clip(rng.normal(0.95, 0.03, n), 0.0, 1.0)
    df = pd.DataFrame({
        "timestamp": truth["timestamp"],
        "sensor_id": s["uav_id"],
        "latitude": lat,
        "longitude": lon,
        "altitude": truth["altitude"] + rng.normal(0.0, 0.8, n),
        "velocity": truth["speed"],
        "vx": truth["vE"],
        "vy": truth["vN"],
        "vz": truth["up"],
        "accel_x": truth["accel_E"] + rng.normal(0.0, s["imu_accel_noise_std"], n),
        "accel_y": truth["accel_N"] + rng.normal(0.0, s["imu_accel_noise_std"], n),
        "accel_z": 9.81 + rng.normal(0.0, s["imu_accel_noise_std"], n),
        "gyro_x": rng.normal(0.0, s["imu_gyro_noise_std"], n),
        "gyro_y": rng.normal(0.0, s["imu_gyro_noise_std"], n),
        "gyro_z": truth["yaw_rate"] + rng.normal(0.0, s["imu_gyro_noise_std"], n),
        "heading": truth["heading"],
        "gnss_quality": quality,
        "packet_rate": np.clip(rng.normal(100.0, 2.0, n), 1.0, None),
        "packet_delay_ms": np.clip(rng.normal(20.0, 1.5, n), 1.0, None),
        "packet_loss": np.zeros(n),
        "sequence_number": np.arange(n, dtype=np.int64),
        "label": np.zeros(n, dtype=np.int64),
        "attack_start": np.zeros(n, dtype=np.int64),
    })[COLUMNS]
    df.attrs["truth_latitude"] = truth["latitude"]
    df.attrs["truth_longitude"] = truth["longitude"]
    df.attrs["truth_velocity"] = truth["speed"]
    return df


def make_clean_dataset(n: Optional[int] = None,
                       seed: Optional[int] = None) -> pd.DataFrame:
    """Clean fused dataset (label 0 everywhere) — the canonical data/synthetic file.

    Args:
        n: Row override (defaults to configs duration × frequency = 6000).
        seed: Seed override (defaults to configs simulation.random_seed).

    Returns:
        Schema-§1 DataFrame with truth arrays in ``attrs``.
    """
    s = simulation_settings()
    fs, dur = s["fs"], s["duration_s"]
    if n is not None:
        dur = n / fs
    seed = s["seed"] if seed is None else int(seed)
    truth = simulate_truth(fs, dur, seed)
    rng = np.random.default_rng(seed + 1)   # sensor noise stream
    return _base_frame(truth, rng, s)


# ---------------------------------------------------------------------------
# per-sensor streams variant (M4 brief; see module docstring)
# ---------------------------------------------------------------------------
def make_streams_variant(df: pd.DataFrame, s: Dict[str, Any]) -> pd.DataFrame:
    """Split the fused frame into per-sensor rows (uav1_gnss/imu/visual/net).

    Rates from configs sensors.*.update_rate_hz; each stream carries its own
    monotonic sequence counter and only the fields its physical sensor
    reports (others NaN — the streams format is explicitly multi-rate, so
    consumers must group by sensor_id before diffing timestamps):

    * ``uav1_gnss``  — timestamp/lat/lon/alt/velocity/vx,vy,vz/heading/gnss_quality
    * ``uav1_imu``   — timestamp/accel_*/gyro_*/heading (100 Hz)
    * ``uav1_visual``— timestamp/lat/lon (truth + 8 m visual-fix noise, 5 Hz)
    * ``uav1_net``   — timestamp/packet_rate/packet_delay_ms/packet_loss (10 Hz)

    ``label``/``attack_start`` are copied from the source tick onto every
    stream row so ground-truth alignment stays trivial.
    """
    rng = np.random.default_rng(int(s["seed"]) + 2)
    n = len(df)
    t = df["timestamp"].to_numpy()
    frames = []

    def _rows(mask_rate_hz: float, cols: Dict[str, np.ndarray], name: str) -> pd.DataFrame:
        step = max(1, int(round(s["fs"] / mask_rate_hz)))
        idx = np.arange(0, n, step)
        out = pd.DataFrame({"timestamp": t[idx], "sensor_id": name})
        for c, arr in cols.items():
            out[c] = np.asarray(arr)[idx]
        out["sequence_number"] = np.arange(len(idx), dtype=np.int64)
        out["label"] = df["label"].to_numpy()[idx].astype(np.int64)
        out["attack_start"] = df["attack_start"].to_numpy()[idx].astype(np.int64)
        return out

    frames.append(_rows(s["gnss_rate_hz"], {
        "latitude": df["latitude"].to_numpy(),
        "longitude": df["longitude"].to_numpy(),
        "altitude": df["altitude"].to_numpy(),
        "velocity": df["velocity"].to_numpy(),
        "vx": df["vx"].to_numpy(), "vy": df["vy"].to_numpy(), "vz": df["vz"].to_numpy(),
        "heading": df["heading"].to_numpy(),
        "gnss_quality": df["gnss_quality"].to_numpy(),
    }, f"{s['uav_id']}_gnss"))

    frames.append(_rows(s["imu_rate_hz"], {
        "accel_x": df["accel_x"].to_numpy(),
        "accel_y": df["accel_y"].to_numpy(),
        "accel_z": df["accel_z"].to_numpy(),
        "gyro_x": df["gyro_x"].to_numpy(),
        "gyro_y": df["gyro_y"].to_numpy(),
        "gyro_z": df["gyro_z"].to_numpy(),
        "heading": df["heading"].to_numpy(),
        "altitude": df["altitude"].to_numpy(),
    }, f"{s['uav_id']}_imu"))

    tlat = df.attrs.get("truth_latitude", df["latitude"].to_numpy())
    tlon = df.attrs.get("truth_longitude", df["longitude"].to_numpy())
    vis_lat = tlat + rng.normal(0.0, 8.0, n) / _M_PER_DEG_LAT
    vis_lon = tlon + rng.normal(0.0, 8.0, n) / _m_per_deg_lon(_LAUNCH_LAT)
    frames.append(_rows(s["visual_rate_hz"], {
        "latitude": vis_lat, "longitude": vis_lon,
        "altitude": df["altitude"].to_numpy(),
        "heading": df["heading"].to_numpy(),
    }, f"{s['uav_id']}_visual"))

    frames.append(_rows(s["fs"], {
        "packet_rate": df["packet_rate"].to_numpy(),
        "packet_delay_ms": df["packet_delay_ms"].to_numpy(),
        "packet_loss": df["packet_loss"].to_numpy(),
    }, f"{s['uav_id']}_net"))

    streams = pd.concat(frames, ignore_index=True)
    streams = streams.sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)
    streams["timestamp"] = streams["timestamp"].astype("float64")
    return streams
