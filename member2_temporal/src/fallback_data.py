"""TRUSTBATTLE — Member 2 interim fallback data generator (NOT the contract dataset).

Member 4 owns data/synthetic/ and data/attacks/ (both currently empty).
Until those land, this module fabricates minimal schema-v1.0-compatible UAV
telemetry carrying the *temporal/network* signatures M2 must detect, so the
module can be trained and evaluated today and re-validated unchanged the
moment Member 4 ships.

This file writes nothing outside member2_temporal/tests/data/ (via
``write_generated``) — never data/synthetic/ or data/attacks/ (Member 4's).

Scenario generators (labels follow data_schema.md §1):
    normal operation (0), replay (2), telemetry_manip (3), network_anomaly (4)

Temporal/network signatures injected (about_project.txt §9/§10):
    replay:           timestamp clock jumps BACKWARD then freezes, sequence
                      numbers repeat, navigation state is a stale copy
    telemetry_manip:  sequence gaps/duplicates/jumps, timestamp jitter and
                      monotonicity violations, inflated kinematic noise
    network_anomaly:  packet inter-arrival spikes (~950 ms vs normal ~20 ms),
                      burst catch-up gaps (~4 ms), 25% packet loss, rate drop
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

_FS = 10.0          # base sample rate (Hz) — settings.simulation.base_frequency_hz
_DT = 1.0 / _FS
_T0 = 1_735_600_000.0
_ACCEL_STD = 0.35   # m/s^2 isotropic random-walk acceleration
_GYRO_STD = 0.02    # rad/s gyro noise
_PK_RATE = 100.0    # normal packet rate (packets/s)
_PK_DELAY = 20.0    # normal packet inter-arrival (ms)
_V_THETA = 0.005    # velocity mean-reversion rate (keeps the process stationary)
_V_DRIFT = 6.0      # m/s gentle forward drift


def _track(rng: np.random.Generator, n: int, maneuver: Optional[tuple] = None) -> dict:
    """Simulate one nominal UAV track and return per-tick arrays.

    ``maneuver=(a, b)`` adds a speed-up + coordinated turn over the fractional
    span [a, b] of the track — used by the replay scenario so the stale
    navigation solution genuinely disagrees with the live IMU.
    """
    ts = _T0 + np.arange(n) * _DT
    accel = rng.normal(0.0, _ACCEL_STD, size=(n, 2))
    if maneuver is not None:
        a, b = int(n * maneuver[0]), int(n * maneuver[1])
        accel[a:b, 0] += 0.8   # speed-up phase
        accel[a:b, 1] += 1.0   # coordinated turn phase
    gyro_z = rng.normal(0.0, _GYRO_STD, size=n)
    gyro_x = rng.normal(0.0, _GYRO_STD, size=n)
    gyro_y = rng.normal(0.0, _GYRO_STD, size=n)

    # Mean-reverting (OU-style) velocity around a gentle forward drift: a pure
    # cumsum random walk would be non-stationary, so train/holdout/eval
    # segments of a long track would come from different distributions and
    # clean-score calibration would not transfer.
    n2 = accel.shape[0]
    vE = np.empty(n2)
    vN = np.empty(n2)
    vE[0], vN[0] = _V_DRIFT, 0.0
    keep = 1.0 - _V_THETA
    for k in range(1, n2):
        vE[k] = keep * vE[k - 1] + _V_THETA * _V_DRIFT + accel[k, 0] * _DT
        vN[k] = keep * vN[k - 1] + accel[k, 1] * _DT
    speed = np.hypot(vE, vN)
    heading = np.degrees(np.arctan2(vE, vN)) % 360.0

    E = np.cumsum(vE) * _DT
    N = np.cumsum(vN) * _DT
    lat0, lon0 = 28.61, 77.21
    lat = lat0 + N / 111_320.0 + rng.normal(0, 3.0, size=n) / 111_320.0
    lon = lon0 + E / (111_320.0 * np.cos(np.deg2rad(lat0))) \
        + rng.normal(0, 3.0, size=n) / (111_320.0 * np.cos(np.deg2rad(lat0)))
    altitude = 120.0 + 2.0 * np.sin(np.arange(n) * 0.05)

    return {
        "timestamp": ts, "lat": lat, "lon": lon, "alt": altitude,
        "vE": vE, "vN": vN, "speed": speed, "accel": accel,
        "gyro_z": gyro_z, "gyro_x": gyro_x, "gyro_y": gyro_y, "heading": heading,
    }


def _flags(n: int, start: int) -> np.ndarray:
    """attack_start flags: 1 from row *start* onward (schema §1)."""
    flags = np.zeros(n, dtype=np.int64)
    flags[max(int(start), 0):] = 1
    return flags


def _net_normal(rng: np.random.Generator, n: int) -> tuple:
    """Normal network telemetry: ~100 pkt/s, ~20 ms inter-arrival, no loss."""
    rate = _PK_RATE + rng.normal(0.0, 2.0, n)
    delay = np.clip(rng.normal(_PK_DELAY, 1.0, n), 5.0, None)
    loss = np.zeros(n)
    return rate, delay, loss


def _base_rows(trk: dict, rng: np.random.Generator, label: int,
               flags: np.ndarray, rate: np.ndarray, delay: np.ndarray,
               loss: np.ndarray, seq: np.ndarray, ts: np.ndarray,
               quality: Optional[np.ndarray] = None) -> pd.DataFrame:
    """Assemble schema-v1.0 rows (single fused platform stream)."""
    n = len(trk["timestamp"])
    if quality is None:
        quality = np.clip(rng.normal(0.95, 0.03, n), 0.0, 1.0)
    df = pd.DataFrame({
        "timestamp": ts,
        "sensor_id": "uav1_fused",
        "latitude": trk["lat"], "longitude": trk["lon"], "altitude": trk["alt"],
        "velocity": trk["speed"],
        "vx": trk["vE"], "vy": trk["vN"], "vz": np.full(n, 0.05),
        "accel_x": trk["accel"][:, 0], "accel_y": trk["accel"][:, 1],
        "accel_z": np.zeros(n),
        "gyro_x": trk["gyro_x"], "gyro_y": trk["gyro_y"], "gyro_z": trk["gyro_z"],
        "heading": trk["heading"],
        "gnss_quality": np.clip(quality, 0.0, 1.0),
        "packet_rate": rate, "packet_delay_ms": delay, "packet_loss": loss,
        "sequence_number": seq.astype(np.int64),
        "label": np.where(flags == 1, label, 0).astype(np.int64),
        "attack_start": flags,
    })
    return df[SAMPLE_COLUMNS]


def make_normal(n: int = 4000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Normal operation track (label 0) — the training distribution stand-in."""
    rng = np.random.default_rng(seed)
    trk = _track(rng, n)
    rate, delay, loss = _net_normal(rng, n)
    return _base_rows(trk, rng, 0, np.zeros(n, dtype=np.int64),
                      rate, delay, loss, np.arange(n, dtype=np.int64), trk["timestamp"])


def make_replay(n: int = 4000, start: int = 2500, seed: int = RANDOM_SEED,
                delay_ticks: int = 121) -> pd.DataFrame:
    """Replay/stale-data scenario (label 2) — M2's primary detection target.

    From ``start`` the attacker re-delivers messages from ``delay_ticks`` ago
    (~12 s at 10 Hz, matching configs: attacks.replay.delay_s) INTERLEAVED with
    the live stream — the classic duplicate-frame replay signature:

    * every other row inside the attack window is a verbatim copy of the
      message transmitted ``delay_ticks`` rows earlier (old timestamp, old
      sequence number, old navigation state, old packet-delay pattern);
      an ODD delay guarantees each re-delivered frame's source row is a
      live (untouched) frame, so every duplicate value truly existed before
    * the clock therefore jumps backward ~12 s and forward again on every
      re-delivery, and sequence numbers repeat already-transmitted values
    * the UAV maneuvers mid-flight, so re-delivered navigation data also
      disagrees with the live IMU (visible to M1's physics checks)
    """
    rng = np.random.default_rng(seed)
    # the live maneuver begins INSIDE the attack window (never before it), so
    # pre-attack rows stay genuinely clean-labeled
    frac = start / max(n, 1)
    maneuver = (frac + 0.02, min(frac + 0.35, 0.95))
    trk = _track(rng, n, maneuver=maneuver)
    flags = _flags(n, start)
    k = int(delay_ticks)

    idx = np.arange(n)
    atk = flags == 1
    stale_row = atk & ((idx - start) % 2 == 1)   # alternate live / re-delivered
    src = np.clip(idx - k, 0, n - 1)

    trk2 = dict(trk)
    for key in ("timestamp", "lat", "lon", "alt", "vE", "vN", "speed", "heading"):
        arr = trk[key].copy()
        arr[stale_row] = arr[src[stale_row]]
        trk2[key] = arr

    seq = np.arange(n, dtype=np.int64)
    seq[stale_row] = seq[src[stale_row]]         # duplicate sequence numbers

    rate, delay, loss = _net_normal(rng, n)
    delay = delay.copy()
    delay[stale_row] = delay[src[stale_row]]     # replayed IAT pattern
    quality = np.clip(rng.normal(0.95, 0.03, n), 0.0, 1.0)
    return _base_rows(trk2, rng, 2, flags, rate, delay, loss, seq,
                      trk2["timestamp"], quality)


def make_telemetry_manip(n: int = 4000, start: int = 2300, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Telemetry manipulation scenario (label 3) — M2's sequence/timestamp target.

    From ``start``:

    * sequence numbers jump (+3/+5) and occasionally repeat (duplicates)
    * timestamps jitter ±30 ms with occasional small non-monotonic steps
    * packet delays get 8× noisier; kinematic noise triples; GNSS quality sags
    """
    rng = np.random.default_rng(seed)
    trk = _track(rng, n)
    flags = _flags(n, start)
    atk = flags == 1
    m = int(atk.sum())

    seq = np.arange(n, dtype=np.int64)
    jumps = rng.choice(np.array([3, 5, -2, 1]), size=m, p=[0.05, 0.03, 0.05, 0.87])
    seq[atk] = seq[atk] + np.cumsum(jumps)

    ts = trk["timestamp"].copy()
    dt = np.full(n, _DT)
    dt[atk] = _DT + rng.normal(0.0, 0.03, m)
    nonmono = rng.random(m) < 0.03
    dt[atk] = np.where(nonmono, -0.02, dt[atk])
    ts[1:] = ts[1:] + np.cumsum(dt[1:] - _DT)

    rate, delay, loss = _net_normal(rng, n)
    delay = delay.copy()
    delay[atk] = np.clip(rng.normal(_PK_DELAY, 8.0, m), 1.0, None)
    rate = rate.copy()
    rate[atk] = _PK_RATE + rng.normal(0.0, 15.0, m)

    trk = dict(trk)
    for key in ("lat", "lon"):
        trk[key] = trk[key] + rng.normal(0, 9.0, n) / 111_320.0 * atk
    trk["vE"] = trk["vE"] + rng.normal(0, 1.5, n) * atk
    trk["vN"] = trk["vN"] + rng.normal(0, 1.5, n) * atk
    trk["speed"] = np.hypot(trk["vE"], trk["vN"])
    trk["timestamp"] = ts

    quality = np.clip(rng.normal(0.95, 0.03, n), 0.0, 1.0)
    quality[atk] = np.clip(quality[atk] - 0.25, 0.0, 1.0)
    return _base_rows(trk, rng, 3, flags, rate, delay, loss, seq, ts, quality)


def make_network_anomaly(n: int = 4000, start: int = 2600, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Network anomaly scenario (label 4) — M2's packet-behaviour target.

    From ``start`` (about_project.txt §10 example):

    * packet inter-arrival mostly ~20 ms but ~8% of rows spike to 850–1050 ms
    * the row right after each spike bursts in at ~4 ms (catch-up)
    * packet loss 25%, effective packet rate drops to ~62 pkt/s
    * navigation state stays clean — only the link misbehaves
    """
    rng = np.random.default_rng(seed)
    trk = _track(rng, n)
    flags = _flags(n, start)
    atk = flags == 1
    m = int(atk.sum())

    rate, delay, loss = _net_normal(rng, n)
    delay = delay.copy()
    rate = rate.copy()
    loss = loss.copy()

    spike = atk & (rng.random(n) < 0.08)
    after = np.roll(spike, 1) & ~spike & atk
    delay[spike] = rng.uniform(850.0, 1050.0, int(spike.sum()))
    delay[after] = rng.uniform(3.0, 6.0, int(after.sum()))     # burst catch-up
    rate[atk] = np.clip(_PK_RATE - rng.uniform(30.0, 45.0, m)
                        + rng.normal(0.0, 5.0, m), 1.0, None)
    loss[atk] = np.clip(rng.normal(0.25, 0.05, m), 0.0, 1.0)

    quality = np.clip(rng.normal(0.95, 0.03, n), 0.0, 1.0)
    return _base_rows(trk, rng, 4, flags, rate, delay, loss,
                      np.arange(n, dtype=np.int64), trk["timestamp"], quality)


def generated_ground_truth(df: pd.DataFrame) -> pd.DataFrame:
    """Ground truth derived from generated labels (data_schema.md §5 format)."""
    return df.loc[df["attack_start"] == 1,
                  ["timestamp", "sensor_id", "label", "attack_start"]].reset_index(drop=True)


def write_generated(directory: str = "member2_temporal/tests/data") -> dict:
    """Optionally persist the generated stand-ins under the module's tests dir."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = {
        "fallback_normal.parquet": make_normal(),
        "fallback_replay.parquet": make_replay(),
        "fallback_telemetry_manip.parquet": make_telemetry_manip(),
        "fallback_network_anomaly.parquet": make_network_anomaly(),
    }
    for name, df in parts.items():
        df.to_parquet(out_dir / name, index=False)
    return parts
