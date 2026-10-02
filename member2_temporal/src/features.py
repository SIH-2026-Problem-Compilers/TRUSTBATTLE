"""TRUSTBATTLE — Member 2 temporal feature extraction (TASK 2).

Layer 3 of about_project.txt §9: time-series behaviour features computed from
the shared telemetry schema (data_schema.md §1). The replay/stale-data and
telemetry-manipulation scenarios are M2's primary detection targets.

Contract (module_interfaces.md, "Owned by Member 2"):
    extract_temporal_features(df) -> df
EXACT name and signature — Member 3's tooling imports it.

Design notes
------------
* Baseline first: rolling statistics, no LSTM/Transformer (project plan §9).
* All added columns are prefixed ``m2_`` so M2 output columns can never
  collide with another member's columns in data/processed/.
* Pure function: never mutates the input frame, no side effects.
* Replay subtlety: a replayed stream is *self-consistent* (it is a copy of
  real traffic), so diffs alone only fire at the replay boundary. Detection
  therefore leans on "seen-before" checks — a sequence number or timestamp
  that was already transmitted earlier in the track — plus clock/monotonic
  behaviour and velocity/acceleration change-rate irregularities.
* Network/telemetry features (TASK 3) live in network_features.py and are
  merged in here, so M3 imports ONE extractor.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from .common import col, finite, rolling_stat
from .network_features import FEATURE_COLUMNS as _NETWORK_FEATURE_COLUMNS
from .network_features import extract_network_features

FEATURE_COLUMNS: List[str] = [
    # --- sampling / kinematic baselines (rolling stats) ---
    "m2_dt_s",
    "m2_dt_median_s",
    "m2_dt_ratio",
    "m2_speed_mps",
    "m2_accel_mag_mps2",
    "m2_speed_roll_std",
    "m2_speed_roll_range",
    "m2_speed_jerk_mps2",
    "m2_speed_change_rate",
    "m2_accel_change_rate",
    "m2_heading_rate_deg_s",
    # --- timestamp integrity ---
    "m2_ts_nonmono",
    "m2_ts_gap_s",
    "m2_ts_jump_forward_s",
    "m2_ts_rewind_s",
    "m2_ts_drift_s",
    "m2_ts_repeat",
    "m2_ts_stale_age_s",
    # --- sequence-number integrity ---
    "m2_seq_gap",
    "m2_seq_jump",
    "m2_seq_dup",
    "m2_seq_back",
    "m2_seq_expected_err",
    "m2_seq_dup_run",
    "m2_seq_seen_before",
    # --- replay / staleness ---
    "m2_stale_score",
    "m2_stale_active",
    # --- network/telemetry (delegated, TASK 3) ---
    "m2_pkt_rate",
    "m2_pkt_rate_ratio",
    "m2_pkt_rate_deficit",
    "m2_pkt_iat_ms",
    "m2_pkt_iat_ratio",
    "m2_pkt_iat_excess_ms",
    "m2_pkt_iat_std_ms",
    "m2_pkt_iat_burst",
    "m2_pkt_loss",
    "m2_pkt_loss_excess",
    "m2_net_disruption",
]

# Feature subsets: the temporal model trains on temporal-only features, the
# network model on network-only features (models/temporal/*.pkl, schema §4).
NETWORK_FEATURE_COLUMNS: List[str] = list(_NETWORK_FEATURE_COLUMNS)
TEMPORAL_FEATURE_COLUMNS: List[str] = [
    c for c in FEATURE_COLUMNS if c not in set(NETWORK_FEATURE_COLUMNS)
]

_STALE_EPS = 1e-9
_SEQ_TOL = 1e-9
_REWIND_SEVERITY_S = 5.0   # a clock rewind of >= 5 s saturates the severity
_STALE_AGE_SEVERITY_S = 5.0
_RESYNC_ROWS = 15          # rows of clean, fresh traffic needed to clear suspect state


def _repeat_flags(values: np.ndarray) -> np.ndarray:
    """1 where a value exactly equals the PREVIOUS row's value.

    Applies to both timestamps and sequence numbers: a "repeat" is the same
    value transmitted twice in a row. Backward steps are separate features
    (``m2_ts_rewind_s`` / ``m2_seq_back``).
    """
    n = len(values)
    if n == 0:
        return np.zeros(0)
    step = np.diff(values, prepend=values[:1])
    eq = np.abs(step) <= _STALE_EPS
    eq[0] = False
    return eq.astype(float)


def _run_length(flags: np.ndarray) -> np.ndarray:
    """Length of the current True run ending at each position (0 if False)."""
    out = np.zeros(len(flags), dtype=float)
    run = 0.0
    for i, f in enumerate(flags):
        run = run + 1.0 if f else 0.0
        out[i] = run
    return out


def _seen_before(values: np.ndarray, lookback: int = 2500) -> np.ndarray:
    """1 where the value already appeared earlier in the track.

    A replay re-broadcasts OLD messages with OLD sequence numbers, so a
    duplicate sequence number far later than one sample is the classic stale
    signature. Uses a rolling set over the previous *lookback* rows (a sliding
    window would miss long-delay replays; full history is O(n²)).
    """
    n = len(values)
    out = np.zeros(n, dtype=float)
    lookback = max(int(lookback), 2)
    for i in range(1, n):
        lo = max(0, i - lookback)
        window = values[lo:i]
        if np.any(np.abs(window - values[i]) <= _SEQ_TOL):
            out[i] = 1.0
    return out


def extract_temporal_features(df: pd.DataFrame, window: int = 21) -> pd.DataFrame:
    """Compute per-observation temporal + network features (contract function).

    Feature groups (all prefixed ``m2_``):

    * sampling/kinematics: timestamp deltas and their ratio to the rolling
      median, rolling speed std/range, jerk, windowed speed/acceleration
      change rates, heading rate
    * timestamp integrity: non-monotonic flag, gaps, forward clock jumps,
      rewinds, drift vs the median rate, repeat/stale-age (time since this
      exact timestamp was last seen — the replay "frozen clock" tell)
    * sequence integrity: gaps (dropped frames), jumps (>1 skipped),
      duplicates, backward steps, error vs the expected next number,
      duplicate-run length and seen-before flag
    * replay/staleness: combined ``m2_stale_score`` severity (0–1)
    * network/telemetry: delegated to network_features.extract_network_features

    Args:
        df: DataFrame following docs/contracts/data_schema.md §1.
        window: Rolling window (samples) for the rolling baselines.

    Returns:
        Copy of *df* with additional ``m2_*`` float columns (FEATURE_COLUMNS).
        Missing optional columns degrade to neutral values; NaN/inf never
        leak into feature columns (models and M3 depend on that).

    Raises:
        ValueError: If the timestamp column is missing.
    """
    if "timestamp" not in df.columns:
        raise ValueError("extract_temporal_features: missing required column 'timestamp'")

    out = df.copy()
    n = len(out)
    w = max(int(window), 3)

    ts = col(out, "timestamp")
    seq = col(out, "sequence_number")

    # ---- time deltas and irregularities ------------------------------------
    dt = np.diff(ts, prepend=ts[:1])
    dt[0] = 0.0
    dt_med = rolling_stat(dt, w, "median")
    dt_med_safe = np.where(dt_med > _STALE_EPS, dt_med, 0.1)
    dt_ratio = np.divide(dt, dt_med_safe, out=np.ones(n), where=dt_med_safe > _STALE_EPS)

    nonmono = (dt < -_STALE_EPS).astype(float)
    gap = (dt > 2.5 * np.maximum(dt_med_safe, _STALE_EPS)) & (dt > 0.2)
    ts_gap = np.where(gap, dt, 0.0)
    ts_fwd = np.where(dt > 2.0 * dt_med_safe, dt, 0.0)          # forward clock jump
    ts_rewind = np.where(dt < -_STALE_EPS, -dt, 0.0)            # clock moved backward

    # drift vs median-rate expectation, over the rolling window (bounded and
    # stationary — a cumulative sum would random-walk and shift distribution
    # over long tracks, which the model would misread as anomalies)
    drift = rolling_stat(dt - dt_med_safe, w, "sum") if n else np.zeros(0)

    ts_repeat = _repeat_flags(ts)
    # stale age: elapsed time between two transmissions of the SAME timestamp
    # (the replay "frozen clock" tell — a value reused ~delay_s later)
    last_seen = np.full(n, -1, dtype=int)
    index_of: dict = {}
    for i in range(n):
        last_seen[i] = index_of.get(ts[i], -1)
        index_of[ts[i]] = i
    pos_dt = dt[dt > _STALE_EPS]
    dt_med_global = float(np.median(pos_dt)) if len(pos_dt) else 0.1
    stale_age = np.where(
        last_seen >= 0, (np.arange(n) - last_seen) * dt_med_global, 0.0
    )

    # ---- sequence-number behaviour ------------------------------------------
    d_seq = np.diff(seq, prepend=seq[:1])
    d_seq[0] = 0.0
    seq_gap = np.abs(d_seq)
    seq_jump = np.where(seq_gap > 1.5, seq_gap, 0.0)
    seq_back = np.where(d_seq < -_SEQ_TOL, -d_seq, 0.0)
    # expected next number: last accepted value + 1 (robust to jitter/jumps)
    accepted = np.abs(d_seq - 1.0) <= _SEQ_TOL
    exp_next = np.empty(n)
    cur = seq[0]
    for i in range(n):
        exp_next[i] = cur
        if accepted[i] or (d_seq[i] > 0 and d_seq[i] <= 5):
            cur = seq[i] + 1.0
    expected = exp_next
    seq_err = np.abs(seq - expected)
    seq_dup = _repeat_flags(seq)
    seq_dup_run = _run_length(seq_dup > 0.5)
    seq_seen = _seen_before(seq)

    # ---- kinematic rolling stats --------------------------------------------
    speed = col(out, "velocity")
    accel_mag = np.sqrt(
        col(out, "accel_x") ** 2 + col(out, "accel_y") ** 2 + col(out, "accel_z") ** 2
    )
    speed_std = rolling_stat(speed, w, "std")
    speed_range = rolling_stat(speed, w, "max") - rolling_stat(speed, w, "min")
    jerk = np.diff(speed, prepend=speed[:1]) / np.where(dt > _STALE_EPS, dt, np.nan)
    jerk = finite(jerk, fill=0.0)
    speed_change_rate = np.abs(jerk) / np.maximum(np.abs(speed), 1.0)
    accel_rate = np.abs(np.diff(accel_mag, prepend=accel_mag[:1])) / np.where(
        dt > _STALE_EPS, dt, np.nan
    )
    accel_rate = finite(accel_rate, fill=0.0)
    hdg = col(out, "heading")
    d_hdg = np.diff(hdg, prepend=hdg[:1])
    d_hdg = (d_hdg + 180.0) % 360.0 - 180.0
    hdg_rate = d_hdg / np.where(dt > _STALE_EPS, dt, np.nan)
    hdg_rate = finite(hdg_rate, fill=0.0)

    # ---- sticky staleness within the frame -----------------------------------
    # A replayed/rewound row makes the stream suspect until it re-synchronizes
    # (sustained strictly-increasing, fresh traffic): live-looking stretches
    # BETWEEN re-delivered frames must not read as trustworthy.
    suspect_now = (
        (ts_rewind > _STALE_EPS) | (nonmono > 0.5)
        | (seq_back > _SEQ_TOL) | (seq_seen > 0.5)
    )
    stale_active = np.zeros(n, dtype=float)
    active = False
    clean_run = 0
    for i in range(n):
        if suspect_now[i]:
            active = True
            clean_run = 0
        elif active:
            clean_run += 1
            if clean_run >= _RESYNC_ROWS:
                active = False
                clean_run = 0
        stale_active[i] = 1.0 if active else 0.0

    # ---- combined replay / staleness severity (0–1) --------------------------
    rewind_sev = np.clip(ts_rewind / _REWIND_SEVERITY_S, 0.0, 1.0)
    stale_age_sev = np.clip(stale_age / _STALE_AGE_SEVERITY_S, 0.0, 1.0)
    dup_run_sev = np.clip(seq_dup_run / 10.0, 0.0, 1.0)
    seen_sev = np.where(seq_seen > 0.5, np.clip(seq_err / 10.0, 0.25, 1.0), 0.0)
    stale_score = np.clip(
        np.maximum.reduce([rewind_sev, stale_age_sev, dup_run_sev, seen_sev,
                           0.5 * stale_active]),
        0.0, 1.0,
    )

    feats = {
        "m2_dt_s": dt,
        "m2_dt_median_s": dt_med,
        "m2_dt_ratio": dt_ratio,
        "m2_speed_mps": speed,
        "m2_accel_mag_mps2": accel_mag,
        "m2_speed_roll_std": speed_std,
        "m2_speed_roll_range": speed_range,
        "m2_speed_jerk_mps2": jerk,
        "m2_speed_change_rate": speed_change_rate,
        "m2_accel_change_rate": accel_rate,
        "m2_heading_rate_deg_s": hdg_rate,
        "m2_ts_nonmono": nonmono,
        "m2_ts_gap_s": ts_gap,
        "m2_ts_jump_forward_s": ts_fwd,
        "m2_ts_rewind_s": ts_rewind,
        "m2_ts_drift_s": drift,
        "m2_ts_repeat": ts_repeat,
        "m2_ts_stale_age_s": stale_age,
        "m2_seq_gap": seq_gap,
        "m2_seq_jump": seq_jump,
        "m2_seq_dup": seq_dup,
        "m2_seq_back": seq_back,
        "m2_seq_expected_err": seq_err,
        "m2_seq_dup_run": seq_dup_run,
        "m2_seq_seen_before": seq_seen,
        "m2_stale_score": stale_score,
        "m2_stale_active": stale_active,
    }
    for c, arr in feats.items():
        out[c] = finite(arr)

    # ---- network/telemetry features (TASK 3) --------------------------------
    try:
        out = extract_network_features(out, window=window)
    except ValueError:
        # no network columns at all: add neutral placeholders so the output
        # shape is stable for the model/consumers
        for c in ("m2_pkt_rate", "m2_pkt_rate_ratio", "m2_pkt_rate_deficit",
                  "m2_pkt_iat_ms", "m2_pkt_iat_ratio", "m2_pkt_iat_excess_ms",
                  "m2_pkt_iat_std_ms", "m2_pkt_iat_burst", "m2_pkt_loss",
                  "m2_pkt_loss_excess", "m2_net_disruption"):
            out[c] = 0.0 if c != "m2_pkt_rate_ratio" else 1.0

    out[FEATURE_COLUMNS] = out[FEATURE_COLUMNS].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return out


def learned_limits(feature_df: pd.DataFrame, percentile: float = 0.999) -> dict:
    """Robust per-feature limits from clean data (used as evidence thresholds).

    Args:
        feature_df: Output of :func:`extract_temporal_features` on clean data.
        percentile: Quantile used as the historical limit per feature.

    Returns:
        Dict mapping feature name -> historical limit (float).
    """
    limits = {}
    for col_name in FEATURE_COLUMNS:
        if col_name in feature_df.columns:
            q = float(feature_df[col_name].quantile(percentile))
            limits[col_name] = q if q > 0 else float(feature_df[col_name].max())
    return limits
