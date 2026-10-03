"""TRUSTBATTLE — Member 4 attack injection engine (TASK 2).

One function per attack scenario; each takes a clean schema-§1 DataFrame
plus parameters and returns:

    (attacked_df, info)

where ``info`` documents what was injected::

    {"name", "label", "params", "rows_attacked",
     "windows": [(start_row, end_row_exclusive), ...]}

Every function is deterministic under the passed ``seed`` and only touches
the fields its real-world analogue could touch (documented per function and
in docs/threat_model.md). Attack conventions match the interim M1/M2
fallback generators so the modules' published rerun path
(``train`` + ``evaluate`` unchanged) works the moment these datasets land.

Labels (data_schema.md §1): 1=gnss_spoof, 2=replay, 3=telemetry_manip,
4=network_anomaly, 5=sensor_malfunction, 6=cross_sensor_conflict.

All work is controlled simulation on synthetic data ONLY (about_project.txt
§18/§24) — nothing here touches real systems.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from member4_cyber.src.generate_data import (
    REPO_ROOT,
    _LAUNCH_LAT,
    _M_PER_DEG_LAT,
    _m_per_deg_lon,
    simulation_settings,
)
from member4_cyber.src.schema import GROUND_TRUTH_COLUMNS, LABEL_NAMES

try:  # pyyaml is not in the shared requirements.txt; degrade gracefully
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

_SETTINGS_PATH = REPO_ROOT / "configs" / "settings.yaml"


def attack_settings() -> Dict[str, Dict[str, float]]:
    """configs/settings.yaml → attacks section with code defaults."""
    cfg: Dict[str, Any] = {}
    if yaml is not None and _SETTINGS_PATH.exists():
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    atk = cfg.get("attacks") or {}
    spoof = atk.get("gnss_spoof") or {}
    replay = atk.get("replay") or {}
    net = atk.get("network_anomaly") or {}
    return {
        "gnss_spoof": {
            "offset_start_m": float(spoof.get("offset_start_m", 150.0)),
            "ramp_s": float(spoof.get("ramp_s", 30.0)),
        },
        "replay": {"delay_s": float(replay.get("delay_s", 12.0))},
        "network_anomaly": {
            "packet_delay_spike_ms": float(net.get("packet_delay_spike_ms", 900.0)),
            "packet_loss_pct": float(net.get("packet_loss_pct", 25.0)),
        },
    }


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------
def _window(df: pd.DataFrame, start: Optional[int], end: Optional[int]) -> Tuple[int, int]:
    """Default attack window: the second half of the track, to its end."""
    n = len(df)
    s = int(start) if start is not None else n // 2
    e = int(end) if end is not None else n
    s = max(0, min(s, n - 1))
    e = max(s + 1, min(e, n))
    return s, e


def ground_truth_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row §5 ground truth (row *i* aligns with data row *i*)."""
    return df[GROUND_TRUTH_COLUMNS].copy()


def _info(name: str, label: int, params: Dict[str, Any],
          df: pd.DataFrame, windows: List[Tuple[int, int]]) -> Dict[str, Any]:
    """Assemble the standard attack info dict."""
    return {
        "name": name,
        "label": label,
        "label_name": LABEL_NAMES[label],
        "params": params,
        "rows_attacked": int((df["label"] == label).sum()),
        "windows": windows,
    }


def _displace_m(df: pd.DataFrame, idx: np.ndarray,
                east_m: np.ndarray, north_m: np.ndarray,
                lat0: Optional[float] = None) -> None:
    """Apply an east/north metre offset to the GNSS position fields in place."""
    lat0 = float(df["latitude"].iloc[0] if lat0 is None else lat0)
    df.loc[idx, "latitude"] = df.loc[idx, "latitude"].to_numpy() + north_m / _M_PER_DEG_LAT
    df.loc[idx, "longitude"] = df.loc[idx, "longitude"].to_numpy() + east_m / _m_per_deg_lon(lat0)


# ---------------------------------------------------------------------------
# (a) GNSS spoofing — label 1
# ---------------------------------------------------------------------------
def attack_gnss_spoof(df: pd.DataFrame, start: Optional[int] = None,
                      end: Optional[int] = None, offset_m: Optional[float] = None,
                      ramp_s: Optional[float] = None,
                      seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Gradually ramp the GNSS-reported position/velocity off the truth.

    The reported trajectory stays self-consistent (position grows at the ramp
    rate, reported velocity components move with it) — the classic
    make-it-look-legitimate spoof (§7: GNSS claims a different trajectory
    than the IMU supports). The IMU/telemetry fields stay truthful, so the
    spoof is only visible as GNSS-vs-IMU disagreement and via the historical
    speed envelope. The ramp is UNBOUNDED (offset keeps growing after
    ``ramp_s``) — a sustained manipulation, matching M1's interim convention.

    Real-world analogy: GNSS spoofing demonstrated against UAVs in recent
    conflicts (about_project.txt §2).
    """
    cfg = attack_settings()["gnss_spoof"]
    offset_m = float(cfg["offset_start_m"] if offset_m is None else offset_m)
    ramp_s = float(cfg["ramp_s"] if ramp_s is None else ramp_s)
    s, e = _window(df, start, end)
    fs = 10.0
    dt = 1.0 / fs

    out = df.copy()
    idx = np.arange(s, e)
    t_rel = (idx - s) * dt
    ramp = t_rel / max(ramp_s, 1e-6)                    # unbounded (sustained)
    dist = offset_m * ramp                              # metres off truth
    rate = offset_m / max(ramp_s, 1e-6)                 # m/s drift, constant
    brg = np.radians(90.0)                              # drift due east
    east_m, north_m = dist * np.sin(brg), dist * np.cos(brg)
    v_east, v_north = rate * np.sin(brg), rate * np.cos(brg)

    _displace_m(out, idx, east_m, north_m)
    out.loc[idx, "vx"] = out.loc[idx, "vx"].to_numpy() + v_east
    out.loc[idx, "vy"] = out.loc[idx, "vy"].to_numpy() + v_north
    out.loc[idx, "vz"] = 0.0
    out.loc[idx, "velocity"] = np.hypot(out.loc[idx, "vx"], out.loc[idx, "vy"])
    out.loc[idx, "gnss_quality"] = out.loc[idx, "gnss_quality"].to_numpy() * 0.6
    out.loc[idx, "label"] = 1
    out.loc[idx, "attack_start"] = 1
    return out, _info("gnss_spoof", 1,
                      {"offset_start_m": offset_m, "ramp_s": ramp_s,
                       "drift_rate_mps": rate, "window_rows": [s, e]},
                      out, [(s, e)])


# ---------------------------------------------------------------------------
# (b) Replay / stale data — label 2
# ---------------------------------------------------------------------------
def attack_replay(df: pd.DataFrame, start: Optional[int] = None,
                  end: Optional[int] = None, delay_s: Optional[float] = None,
                  seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Re-deliver old messages interleaved with the live stream.

    From ``start``, every OTHER row inside the window is a verbatim copy of
    the message transmitted ``delay_s`` (configs, ~121 ticks at 10 Hz — odd,
    so each copied source row is itself a live frame) earlier:

    * old timestamps (the clock jumps backward ~12 s and forward again),
      old sequence numbers (already-transmitted values re-broadcast),
      old navigation state and old packet-delay pattern
    * the live rows in between keep fresh timestamps — so the stream shows
      alternating fresh/frozen messages, M2's headline replay signature;
    * the truth trajectory kept flying during the delay, so the re-delivered
      nav state also disagrees with the live IMU (M1-visible during turns).

    Real-world analogy: recorded-signal replay / stale-data injection
    (about_project.txt §9).
    """
    cfg = attack_settings()["replay"]
    delay_s = float(cfg["delay_s"] if delay_s is None else delay_s)
    delay_ticks = int(round(delay_s * 10.0))
    if delay_ticks % 2 == 0:
        delay_ticks += 1                                # odd → live source rows
    s, e = _window(df, start, end)

    out = df.copy()
    n = len(out)
    idx = np.arange(s, e)
    stale = (idx - s) % 2 == 1
    stale_rows = idx[stale]
    src = np.clip(stale_rows - delay_ticks, 0, n - 1)

    copy_cols = ["timestamp", "latitude", "longitude", "altitude", "velocity",
                 "vx", "vy", "vz", "heading", "packet_delay_ms",
                 "sequence_number", "gnss_quality"]
    for c in copy_cols:
        arr = out[c].to_numpy()
        arr[stale_rows] = arr[src]
        out[c] = arr
    # window semantics (data_schema.md §1: attack_start = "inside an injected
    # attack window"): ALL rows in the window carry the scenario label — the
    # live interleaved rows belong to the replay operation too (this matches
    # the M1/M2 scenario convention); which rows are actually stale frames is
    # discoverable from the duplicated timestamps/sequence numbers.
    out.loc[idx, "label"] = 2
    out.loc[idx, "attack_start"] = 1
    return out, _info("replay", 2,
                      {"delay_s": delay_s, "delay_ticks": delay_ticks,
                       "stale_rows": int(len(stale_rows)),
                       "window_rows": [s, e]},
                      out, [(s, e)])


# ---------------------------------------------------------------------------
# (c) Telemetry manipulation — label 3
# ---------------------------------------------------------------------------
def attack_telemetry_manipulation(df: pd.DataFrame, start: Optional[int] = None,
                                  end: Optional[int] = None,
                                  seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Alter reported sensor values with plausible-looking statistics.

    Nothing is extreme — every manipulated value sits inside a plausible
    envelope, but the joint pattern breaks:

    * sequence numbers jump (+3/+5) and occasionally repeat or step backward,
    * timestamps jitter ±30 ms with occasional small non-monotonic steps,
    * packet delay gets 8× noisier, packet rate wanders,
    * kinematics get subtly noisier (position σ 9 m, velocity σ 1.5 m/s),
    * GNSS quality sags ~0.25.

    Real-world analogy: false-data injection with statistically plausible
    values — the manipulation is only visible as joint inconsistency (§9).
    """
    rng = np.random.default_rng(seed)
    s, e = _window(df, start, end)
    out = df.copy()
    idx = np.arange(s, e)
    m = len(idx)
    lat0 = _LAUNCH_LAT

    seq = out["sequence_number"].to_numpy().copy()
    jumps = rng.choice(np.array([3, 5, -2, 1]), size=m, p=[0.05, 0.03, 0.05, 0.87])
    seq[idx] = seq[idx] + np.cumsum(jumps)
    out["sequence_number"] = seq.astype(np.int64)

    ts = out["timestamp"].to_numpy().copy()
    dt = np.full(len(out), 0.1)
    dt[idx] = 0.1 + rng.normal(0.0, 0.03, m)
    dt[idx] = np.where(rng.random(m) < 0.03, -0.02, dt[idx])
    ts[1:] = ts[1:] + np.cumsum(dt[1:] - 0.1)
    out["timestamp"] = ts

    out.loc[idx, "packet_delay_ms"] = np.clip(
        rng.normal(20.0, 12.0, m), 1.0, None)
    out.loc[idx, "packet_rate"] = np.clip(
        out.loc[idx, "packet_rate"].to_numpy() + rng.normal(0.0, 15.0, m), 1.0, None)
    _displace_m(out, idx, rng.normal(0, 9.0, m), rng.normal(0, 9.0, m), lat0)
    out.loc[idx, "vx"] = out.loc[idx, "vx"].to_numpy() + rng.normal(0, 1.5, m)
    out.loc[idx, "vy"] = out.loc[idx, "vy"].to_numpy() + rng.normal(0, 1.5, m)
    out.loc[idx, "velocity"] = np.hypot(out.loc[idx, "vx"], out.loc[idx, "vy"])
    out.loc[idx, "gnss_quality"] = np.clip(
        out.loc[idx, "gnss_quality"].to_numpy() - 0.25, 0.0, 1.0)
    out.loc[idx, "label"] = 3
    out.loc[idx, "attack_start"] = 1
    return out, _info("telemetry_manipulation", 3,
                      {"ts_jitter_s": 0.03, "nonmono_frac": 0.03,
                       "pos_noise_m": 9.0, "window_rows": [s, e]},
                      out, [(s, e)])


# ---------------------------------------------------------------------------
# (d) Network anomaly — label 4
# ---------------------------------------------------------------------------
def attack_network_anomaly(df: pd.DataFrame, start: Optional[int] = None,
                           end: Optional[int] = None,
                           seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Packet-delay spikes, loss bursts and rate changes; navigation stays clean.

    Per configs attacks.network_anomaly (spike centre ~900 ms, loss 25%):

    * ~8% of rows spike to spike±150 ms (the §10 example: ~20 ms → ~950 ms),
      each followed by a ~4 ms catch-up burst,
    * packet rate drops 30–45 pps below baseline,
    * packet loss jumps to ~25%.

    Real-world analogy: jamming/degraded links, congested or manipulated
    datalinks (about_project.txt §10).
    """
    rng = np.random.default_rng(seed)
    cfg = attack_settings()["network_anomaly"]
    spike_center = float(cfg["packet_delay_spike_ms"])
    loss_pct = float(cfg["packet_loss_pct"])
    s, e = _window(df, start, end)
    out = df.copy()
    idx = np.arange(s, e)
    m = len(idx)

    spike_mask = rng.random(m) < 0.08
    spike_rows = idx[spike_mask]
    after = np.roll(spike_mask, 1) & ~spike_mask
    after_rows = idx[after]

    out.loc[spike_rows, "packet_delay_ms"] = rng.uniform(
        max(spike_center - 150.0, 1.0), spike_center + 150.0, len(spike_rows))
    out.loc[after_rows, "packet_delay_ms"] = rng.uniform(3.0, 6.0, len(after_rows))
    out.loc[idx, "packet_rate"] = np.clip(
        out.loc[idx, "packet_rate"].to_numpy() - rng.uniform(30.0, 45.0, m)
        + rng.normal(0.0, 5.0, m), 1.0, None)
    out.loc[idx, "packet_loss"] = np.clip(
        rng.normal(loss_pct / 100.0, 0.05, m), 0.0, 1.0)
    out.loc[idx, "label"] = 4
    out.loc[idx, "attack_start"] = 1
    return out, _info("network_anomaly", 4,
                      {"spike_ms": spike_center, "spike_frac": 0.08,
                       "loss_pct": loss_pct, "window_rows": [s, e]},
                      out, [(s, e)])


# ---------------------------------------------------------------------------
# (e) Sensor malfunction — label 5
# ---------------------------------------------------------------------------
def attack_sensor_malfunction(df: pd.DataFrame, start: Optional[int] = None,
                              end: Optional[int] = None, bias: float = 1.2,
                              seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """IMU bias/drift, stuck values and noise bursts — the sensor itself lies.

    From ``start``:

    * the IMU accel grows a ramping bias (to ``bias`` m/s² on x, 0.3× on y),
    * the reported nav state integrates the faulty IMU (velocity random-walks
      away from truth while GNSS stays truthful — GNSS-vs-IMU disagreement),
    * stuck values: accel freezes for ~1.5 s stretches every ~20 s,
    * noise bursts: accel noise ×8 for ~1 s every ~15 s.

    Real-world analogy: hardware failure/degradation — no adversary needed
    (about_project.txt §1 "sensor malfunction").
    """
    rng = np.random.default_rng(seed)
    s, e = _window(df, start, end)
    out = df.copy()
    idx = np.arange(s, e)
    m = len(idx)
    fs = 10.0
    dt = 1.0 / fs

    ramp = np.minimum((idx - s) * dt / 10.0, 1.0)       # bias ramps over 10 s
    bias_x = bias * ramp
    bias_y = 0.3 * bias * ramp
    out.loc[idx, "accel_x"] = out.loc[idx, "accel_x"].to_numpy() + bias_x
    out.loc[idx, "accel_y"] = out.loc[idx, "accel_y"].to_numpy() + bias_y

    # reported nav integrates the faulty IMU: velocity drifts off truth
    drift = np.cumsum(bias_x) * dt
    out.loc[idx, "vx"] = out.loc[idx, "vx"].to_numpy() + drift
    out.loc[idx, "velocity"] = np.hypot(out.loc[idx, "vx"], out.loc[idx, "vy"])

    # stuck values: freeze accel/gyro for 15-row stretches every ~200 rows
    for r0 in range(s, e, 200):
        r1 = min(r0 + 15, e)
        rows = np.arange(r0, r1)
        out.loc[rows, "accel_x"] = out.loc[rows[0], "accel_x"]
        out.loc[rows, "accel_y"] = out.loc[rows[0], "accel_y"]
        out.loc[rows, "gyro_z"] = out.loc[rows[0], "gyro_z"]

    # noise bursts: accel noise ×8 for ~10 rows every ~150 rows
    for r0 in range(s + 75, e, 150):
        r1 = min(r0 + 10, e)
        rows = np.arange(r0, r1)
        out.loc[rows, "accel_x"] = out.loc[rows, "accel_x"].to_numpy() \
            + rng.normal(0.0, 0.4, len(rows))
        out.loc[rows, "accel_y"] = out.loc[rows, "accel_y"].to_numpy() \
            + rng.normal(0.0, 0.4, len(rows))

    out.loc[idx, "label"] = 5
    out.loc[idx, "attack_start"] = 1
    return out, _info("sensor_malfunction", 5,
                      {"bias_mps2": bias, "stuck_stretch_rows": 15,
                       "burst_sigma": 0.4, "window_rows": [s, e]},
                      out, [(s, e)])


# ---------------------------------------------------------------------------
# (f) Cross-sensor conflict — label 6
# ---------------------------------------------------------------------------
def attack_cross_sensor_conflict(df: pd.DataFrame, start: Optional[int] = None,
                                 end: Optional[int] = None, offset_m: float = 35.0,
                                 course_shift_deg: float = 12.0,
                                 seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Two sensors persistently disagree — without either being extreme.

    From ``start`` (constant, no ramp): the GNSS-reported position carries a
    steady ~35 m offset while the reported course is rotated ~12° from the
    IMU-sensed heading. Individually every value looks plausible (a 35 m
    bias is within poor-satellite-geometry behaviour; 12° is within a sloppy
    calibration) — but GNSS, IMU and the visual estimate persistently
    disagree, so NOTHING is individually anomalous while everything is
    jointly inconsistent (about_project.txt §11).

    Real-world analogy: miscalibrated sources, multipath, subtle deception
    (§1 "conflicting observations from different sensors").
    """
    s, e = _window(df, start, end)
    out = df.copy()
    idx = np.arange(s, e)
    m = len(idx)
    brg = np.radians(90.0)
    _displace_m(out, idx,
                np.full(m, offset_m * np.sin(brg)),
                np.full(m, offset_m * np.cos(brg)))
    # rotate the reported velocity/course off the true heading
    rot = np.radians(course_shift_deg)
    vx = out.loc[idx, "vx"].to_numpy()
    vy = out.loc[idx, "vy"].to_numpy()
    out.loc[idx, "vx"] = vx * np.cos(rot) - vy * np.sin(rot)
    out.loc[idx, "vy"] = vx * np.sin(rot) + vy * np.cos(rot)
    out.loc[idx, "velocity"] = np.hypot(out.loc[idx, "vx"], out.loc[idx, "vy"])
    out.loc[idx, "label"] = 6
    out.loc[idx, "attack_start"] = 1
    return out, _info("cross_sensor_conflict", 6,
                      {"offset_m": offset_m, "course_shift_deg": course_shift_deg,
                       "window_rows": [s, e]},
                      out, [(s, e)])


# ---------------------------------------------------------------------------
# registry + mixed-corruption datasets (§19 experiments)
# ---------------------------------------------------------------------------
ATTACKS = {
    "gnss_spoof": attack_gnss_spoof,
    "replay": attack_replay,
    "telemetry_manipulation": attack_telemetry_manipulation,
    "network_anomaly": attack_network_anomaly,
    "sensor_malfunction": attack_sensor_malfunction,
    "cross_sensor_conflict": attack_cross_sensor_conflict,
}


def attack_mixed(df: pd.DataFrame, corruption_pct: float,
                 seed: int = 42) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Mixed dataset with exactly ``corruption_pct``% corrupted rows (§19).

    The corrupted rows form consecutive BLOCKS, one per attack family, cycled
    through :data:`member4_cyber.src.schema.MIXED_ATTACK_CYCLE` and laid out
    sequentially over the middle 80% of the track (sustained operations, not
    scattered single-row corruption — see the m4 evaluation notes). The total
    attacked row count is exact: ``round(len(df) * pct / 100)``.

    Returns:
        (attacked_df, info) with info["windows"] per block and info["params"]
        recording the realized percentage.
    """
    from member4_cyber.src.schema import MIXED_ATTACK_CYCLE

    n = len(df)
    total = int(round(n * corruption_pct / 100.0))
    out = df.copy()
    windows: List[Tuple[int, int]] = []
    per_type: Dict[str, int] = {}

    if total > 0:
        k = len(MIXED_ATTACK_CYCLE)
        base = total // k
        sizes = [base + (1 if i < total - base * k else 0) for i in range(k)]
        span_lo, span_hi = int(n * 0.10), int(n * 0.95)
        # every attack now labels its WHOLE window (window semantics, §1), so
        # block sizes map 1:1 to attacked-row counts
        block_sizes = sizes
        gap = max(1, (span_hi - span_lo - total) // k) \
            if total < span_hi - span_lo else 0
        cursor = span_lo
        for name, size in zip(MIXED_ATTACK_CYCLE, block_sizes):
            if size <= 0:
                continue
            s = min(cursor, n - size)
            e = s + size
            out, info = ATTACKS[name](out, start=s, end=e, seed=seed)
            windows.append((s, e))
            per_type[name] = per_type.get(name, 0) + info["rows_attacked"]
            cursor = e + gap

    realized = 100.0 * int((out["label"] > 0).sum()) / n
    return out, {
        "name": f"mixed_c{int(round(corruption_pct)):02d}",
        "label": -1,
        "label_name": "mixed",
        "params": {"requested_pct": corruption_pct, "realized_pct": round(realized, 3),
                   "rows_by_type": per_type},
        "rows_attacked": int((out["label"] > 0).sum()),
        "windows": windows,
    }
