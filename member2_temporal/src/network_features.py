"""TRUSTBATTLE — Member 2 network/telemetry feature extraction (TASK 3).

Layer 4 of about_project.txt §10: communication-behaviour features computed
from the shared telemetry schema (data_schema.md §1):

    packet_rate, packet_delay_ms (inter-arrival time), packet_loss
    (+ sequence_number / timestamp behaviour live in features.py)

Contract (module_interfaces.md, "Owned by Member 2"):
    extract_network_features(df) -> df
Delegated to from features.extract_temporal_features (the single import
surface M3's tooling uses), but importable standalone.

Design notes
------------
* All added columns are prefixed ``m2_`` so M2 output columns can never
  collide with another member's columns in data/processed/.
* Pure function: never mutates the input frame, no side effects.
* The §10 example is the guiding signature — normal inter-arrival
  ~20 ms vs anomaly ``... 950 ms ... 4 ms ...`` (delay spike + catch-up
  burst), plus rate drop and packet loss.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from .common import col, finite, rolling_stat

FEATURE_COLUMNS: List[str] = [
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

_SPIKE_FACTOR = 3.0    # IAT above median * this = delay spike
_BURST_FACTOR = 0.5    # IAT below median * this = catch-up burst
_SPIKE_SCALE_MS = 200.0  # ms above the spike line mapping to severity 1.0


def extract_network_features(df: pd.DataFrame, window: int = 21) -> pd.DataFrame:
    """Compute per-observation network/telemetry features (contract function).

    Features (all prefixed ``m2_``):

    * packet-rate level, ratio to the rolling median and deficit below it
    * inter-arrival time (IAT): level, ratio/excess vs the rolling median
      (delay spikes), rolling std (jitter) and catch-up-burst flag
    * packet loss: level and excess above the rolling median
    * combined ``m2_net_disruption`` severity (0–1) for evidence/scoring

    Args:
        df: DataFrame following docs/contracts/data_schema.md §1.
        window: Rolling window (samples) for the robust baselines.

    Returns:
        Copy of *df* with additional ``m2_pkt_*`` / ``m2_net_*`` float columns
        (FEATURE_COLUMNS). Missing network columns degrade to neutral values.

    Raises:
        ValueError: If none of the network columns exist at all.
    """
    net_cols = ["packet_rate", "packet_delay_ms", "packet_loss"]
    if not any(c in df.columns for c in net_cols):
        raise ValueError(
            "extract_network_features: none of the network columns "
            f"{net_cols} are present in the input"
        )

    out = df.copy()
    n = len(out)
    w = max(int(window), 3)

    rate = col(out, "packet_rate")
    iat = np.abs(col(out, "packet_delay_ms"))  # delay is a magnitude
    loss = np.clip(col(out, "packet_loss"), 0.0, 1.0)

    # ---- robust rolling baselines -----------------------------------------
    rate_med = rolling_stat(rate, w, "median")
    iat_med = rolling_stat(iat, w, "median")
    loss_med = rolling_stat(loss, w, "median")

    rate_ratio = np.divide(rate, rate_med, out=np.ones(n), where=rate_med > 1e-9)
    iat_ratio = np.divide(iat, iat_med, out=np.ones(n), where=iat_med > 1e-9)

    # ---- delay spikes and catch-up bursts (the §10 signature) --------------
    iat_excess = np.maximum(iat - _SPIKE_FACTOR * iat_med, 0.0)      # ms above spike line
    burst = (iat < _BURST_FACTOR * iat_med) & (iat_med > 1e-9)       # abnormally fast row

    rate_deficit = np.maximum(rate_med - rate, 0.0)
    rate_deficit_norm = np.divide(
        rate_deficit, rate_med, out=np.zeros(n), where=rate_med > 1e-9
    )
    loss_excess = np.maximum(loss - loss_med - 0.02, 0.0)

    # ---- combined disruption severity (0–1, higher = worse link) -----------
    spike_sev = np.clip(iat_excess / _SPIKE_SCALE_MS, 0.0, 1.0)
    burst_sev = np.where(burst, 0.6, 0.0)
    rate_sev = np.clip(rate_deficit_norm / 0.4, 0.0, 1.0)   # >40% rate drop = 1.0
    loss_sev = np.clip(loss_excess / 0.25, 0.0, 1.0)        # >25 pp loss = 1.0
    disruption = np.clip(
        np.maximum.reduce([spike_sev, burst_sev, rate_sev, loss_sev]), 0.0, 1.0
    )

    feats = {
        "m2_pkt_rate": rate,
        "m2_pkt_rate_ratio": rate_ratio,
        "m2_pkt_rate_deficit": rate_deficit_norm,
        "m2_pkt_iat_ms": iat,
        "m2_pkt_iat_ratio": iat_ratio,
        "m2_pkt_iat_excess_ms": iat_excess,
        "m2_pkt_iat_std_ms": rolling_stat(iat, w, "std"),
        "m2_pkt_iat_burst": burst.astype(float),
        "m2_pkt_loss": loss,
        "m2_pkt_loss_excess": loss_excess,
        "m2_net_disruption": disruption,
    }
    for c, arr in feats.items():
        out[c] = finite(arr)
    return out
