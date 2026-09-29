"""TRUSTBATTLE — Member 1 interim fallback data generator (NOT the contract dataset).

Member 4 owns data/synthetic/ and data/attacks/ (both currently empty).
Until those land, this module fabricates a *minimal* schema-v1.0-compatible
UAV telemetry track so M1 can be trained and evaluated today, and the code is
re-validated against real datasets the moment Member 4 ships.

This file contains NO contract types of its own and writes nothing outside
member1_physical/tests/data/ (via ``write_generated``) — never data/synthetic/
or data/attacks/, which are Member 4's.

Scenario generators (labels follow data_schema.md §1):
    normal operation (0), gnss_spoof (1), replay (2), sensor_malfunction (5),
    cross_sensor_conflict (6)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

RANDOM_SEED = 42  # mirrors configs/settings.yaml simulation.random_seed
SAMPLE_COLUMNS = [
    "timestamp", "sensor_id", "latitude", "longitude", "altitude",
    "velocity", "vx", "vy", "vz",
    "accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z",
    "heading", "gnss_quality",
    "packet_rate", "packet_delay_ms", "packet_loss", "sequence_number",
    "label", "attack_start",
]

# isotropic random-walk acceleration (m/s^2) with gyro noise (rad/s)
_ACCEL_STD = 0.35
_GYRO_STD = 0.02


def _track(rng: np.random.Generator, n: int, fs: float = 10.0,
           maneuver: Optional[tuple] = None) -> dict:
    """Simulate one nominal UAV track and return per-tick arrays.

    ``maneuver=(a, b)`` adds a speed-up + coordinated turn over the fractional
    span [a, b] of the track — used by the replay scenario so the stale
    navigation solution genuinely disagrees with the live IMU.
    """
    dt = 1.0 / fs
    t0 = 1_735_600_000.0
    ts = t0 + np.arange(n) * dt

    accel = rng.normal(0.0, _ACCEL_STD, size=(n, 2))
    if maneuver is not None:
        a, b = int(n * maneuver[0]), int(n * maneuver[1])
        accel[a:b, 0] += 0.8   # speed-up phase
        accel[a:b, 1] += 1.0   # coordinated turn phase
    gyro_z = rng.normal(0.0, _GYRO_STD, size=n)
    gyro_x = rng.normal(0.0, _GYRO_STD, size=n)
    gyro_y = rng.normal(0.0, _GYRO_STD, size=n)

    # integrate to velocity/heading/position (E/N plane)
    vE = np.cumsum(accel[:, 0]) * dt + 6.0   # gentle forward drift
    vN = np.cumsum(accel[:, 1]) * dt
    speed = np.hypot(vE, vN)
    heading = np.degrees(np.arctan2(vE, vN)) % 360.0

    E = np.cumsum(vE) * dt
    N = np.cumsum(vN) * dt
    lat0, lon0 = 28.61, 77.21  # fixed reference airfield
    lat = lat0 + N / 111_320.0
    lon = lon0 + E / (111_320.0 * np.cos(np.deg2rad(lat0)))
    altitude = 120.0 + 2.0 * np.sin(np.arange(n) * 0.05)

    # measurement noise on the reported navigation state
    lat = lat + rng.normal(0, 3.0, size=n) / 111_320.0
    lon = lon + rng.normal(0, 3.0, size=n) / (111_320.0 * np.cos(np.deg2rad(lat0)))

    return {
        "timestamp": ts, "lat": lat, "lon": lon, "alt": altitude,
        "vE": vE, "vN": vN, "vz": np.full(n, 0.05), "speed": speed,
        "accel": accel, "gyro_z": gyro_z, "gyro_x": gyro_x, "gyro_y": gyro_y,
        "heading": heading,
    }


def _rows(trk: dict, label: int, attack_flags: np.ndarray, quality_scale: float,
          spoof: Optional[dict] = None, replay: Optional[dict] = None,
          malfunction: Optional[dict] = None) -> pd.DataFrame:
    """Assemble schema-v1.0 rows (single fused platform stream)."""
    n = len(trk["timestamp"])
    vE, vN = trk["vE"].copy(), trk["vN"].copy()
    lat, lon = trk["lat"].copy(), trk["lon"].copy()
    speed = trk["speed"].copy()
    accel = trk["accel"].copy()

    if spoof is not None:
        # ramp the *reported* GNSS kinematics away from the inertial truth
        ramp = np.clip((np.arange(n) - spoof["start"]) / spoof["ramp_s"], 0.0, None)
        ramp *= (np.arange(n) >= spoof["start"])
        vE = vE + spoof["dvE"] * ramp
        vN = vN + spoof["dvN"] * ramp
        speed = np.hypot(vE, vN)
        lat = lat + spoof["dN"] * ramp / 111_320.0
        lon = lon + spoof["dE"] * ramp / (111_320.0 * np.cos(np.deg2rad(28.61)))

    if replay is not None:
        # Real replay (about_project §17/§18): the reported navigation solution
        # (position + velocity) is a stale copy from delay_ticks ago while the
        # IMU keeps sensing the live maneuver — stale nav vs live inertial.
        k = replay["delay_ticks"]
        idx = np.arange(n)
        stale = idx >= replay["start"]
        src = np.clip(idx - k, 0, n - 1)
        vE[stale] = vE[src[stale]]
        vN[stale] = vN[src[stale]]
        lat[stale] = lat[src[stale]]
        lon[stale] = lon[src[stale]]
        speed = np.hypot(vE, vN)

    if malfunction is not None:
        # inertial readings drift/drop out from `start` onward
        idx = np.arange(n) >= malfunction["start"]
        accel[idx, 0] += malfunction["bias"]
        accel[idx, 1] += 0.3 * malfunction["bias"]
        vE = vE + malfunction["bias"] * np.maximum(np.arange(n) - malfunction["start"], 0) / 10.0
        speed = np.hypot(vE, vN)

    packet_rate = np.full(n, 100.0) + np.random.RandomState(7).normal(0, 2, n)
    quality = np.clip(np.random.RandomState(11).normal(0.95, 0.03, n), 0, 1) * quality_scale
    if spoof is not None:
        idx = np.arange(n)
        quality[idx >= spoof["start"]] *= 0.6  # degraded signal during spoof

    df = pd.DataFrame({
        "timestamp": trk["timestamp"],
        "sensor_id": "uav1_fused",
        "latitude": lat,
        "longitude": lon,
        "altitude": trk["alt"],
        "velocity": speed,
        "vx": vE,
        "vy": vN,
        "vz": trk["vz"],
        "accel_x": accel[:, 0],
        "accel_y": accel[:, 1],
        "accel_z": np.zeros(n),
        "gyro_x": trk["gyro_x"],
        "gyro_y": trk["gyro_y"],
        "gyro_z": trk["gyro_z"],
        "heading": trk["heading"],
        "gnss_quality": np.clip(quality, 0, 1),
        "packet_rate": packet_rate,
        "packet_delay_ms": np.full(n, 20.0),
        "packet_loss": np.zeros(n),
        "sequence_number": np.arange(n, dtype=np.int64),
        # per-row label: attack code only inside the injected window (schema §1)
        "label": np.where(attack_flags == 1, label, 0).astype(np.int64),
        "attack_start": attack_flags.astype(np.int64),
    })
    return df[SAMPLE_COLUMNS]


def make_normal(n: int = 4000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Normal operation track (label 0) — the training distribution stand-in."""
    return _rows(_track(np.random.default_rng(seed), n), label=0,
                 attack_flags=np.zeros(n), quality_scale=1.0)


def make_spoof(n: int = 4000, start: int = 2000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """GNSS spoofing scenario (label 1): reported kinematics ramp away.

    Mirrors about_project.txt §7: GNSS claims ~120 km/h while IMU-integrated
    motion stays at the real ~55 km/h.
    """
    trk = _track(np.random.default_rng(seed), n)
    flags = np.zeros(n, dtype=np.int64)
    flags[start:] = 1
    spoof = {"start": start, "ramp_s": 30.0, "dvE": 25.0, "dvN": 4.0, "dE": 250.0, "dN": 60.0}
    return _rows(trk, label=1, attack_flags=flags, quality_scale=1.0, spoof=spoof)


def make_replay(n: int = 4000, start: int = 2500, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Replay/stale-data scenario (label 2): stale nav solution vs live IMU.

    The UAV maneuvers mid-flight; from `start` the reported position/velocity
    are a 12 s-old copy (configs: attacks.replay.delay_s) while the IMU
    reports the live maneuver — the classic replay signature.
    """
    trk = _track(np.random.default_rng(seed), n, maneuver=(0.55, 0.78))
    flags = np.zeros(n, dtype=np.int64)
    flags[start:] = 1
    replay = {"delay_ticks": 120, "start": start}  # 12 s at 10 Hz
    return _rows(trk, label=2, attack_flags=flags, quality_scale=1.0, replay=replay)


def make_malfunction(n: int = 4000, start: int = 2200, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Sensor malfunction scenario (label 5): inertial readings go bad."""
    trk = _track(np.random.default_rng(seed), n)
    flags = np.zeros(n, dtype=np.int64)
    flags[start:] = 1
    mal = {"start": start, "bias": 1.2}
    return _rows(trk, label=5, attack_flags=flags, quality_scale=1.0, malfunction=mal)


def make_conflict(n: int = 4000, start: int = 2400, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Cross-sensor conflict scenario (label 6): GNSS-vs-course disagreement."""
    trk = _track(np.random.default_rng(seed), n)
    flags = np.zeros(n, dtype=np.int64)
    flags[start:] = 1
    # course and heading diverge: rotate the reported velocity components
    spoof = {"start": start, "ramp_s": 10.0, "dvE": -8.0, "dvN": 18.0, "dE": 0.0, "dN": 0.0}
    return _rows(trk, label=6, attack_flags=flags, quality_scale=1.0, spoof=spoof)


def generated_ground_truth(df: pd.DataFrame) -> pd.DataFrame:
    """Ground truth derived from generated labels (data_schema.md §5 format)."""
    return df.loc[df["attack_start"] == 1, ["timestamp", "sensor_id", "label", "attack_start"]].reset_index(drop=True)


def write_generated(directory: str = "member1_physical/tests/data") -> dict:
    """Optionally persist the generated stand-ins under the module's tests dir."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = {
        "fallback_normal.parquet": make_normal(),
        "fallback_spoof.parquet": make_spoof(),
        "fallback_replay.parquet": make_replay(),
        "fallback_malfunction.parquet": make_malfunction(),
        "fallback_conflict.parquet": make_conflict(),
    }
    for name, df in parts.items():
        df.to_parquet(out_dir / name, index=False)
    return parts
