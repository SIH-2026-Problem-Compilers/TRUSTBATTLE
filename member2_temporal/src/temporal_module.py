"""TRUSTBATTLE — Member 2 temporal/network scoring (TASK 5).

Produces the per-observation score message defined in data_schema.md §2/§3:

    {"scores": {"temporal_consistency": 0-1 (higher = trustworthy),
                "anomaly_temporal":     0-1 (higher = anomalous),
                "network_integrity":    0-1 (higher = trustworthy)},
     "evidence": [{"check": ..., "pass": true/false, "detail": ...}]}

Entry point (registered by integration/pipeline.py as ``score_temporal``):
    score_observation(window_df) -> dict

Accepts a single schema-§1 row (dict or 1-row DataFrame) or a window DataFrame
(e.g. 50 rows @ 10 Hz). Evidence strings are human-readable — they appear on
the Member 5 dashboard, e.g.
    "Packet inter-arrival spike: 950 ms (normal ~20 ms) — possible
     replay/communication anomaly".

The module imports with zero side effects: models are lazily loaded and the
evidence checks work from configs/settings.yaml alone if no artifacts exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import json

import numpy as np
import pandas as pd

from . import model as _model
from .features import NETWORK_FEATURE_COLUMNS, TEMPORAL_FEATURE_COLUMNS, extract_temporal_features

RowOrWindow = Union[Dict[str, Any], List[Dict[str, Any]], pd.DataFrame]


class TemporalScorer:
    """Scores observations using trained artifacts + interpretable temporal checks.

    Instantiate once and reuse (artifact loading happens on first use).
    """

    def __init__(self, model_dir: Optional[Path] = None):
        if model_dir is None:
            model_dir = _model.MODELS_DIR
        self._model_dir = Path(model_dir)
        self._temporal_model = None
        self._temporal_scaler = None
        self._network_model = None
        self._network_scaler = None
        self._loaded = False
        self.settings = _model.model_settings()
        self._checks = self.settings["checks"]
        self._net = self.settings["network"]

    # -- lazy artifact loading ------------------------------------------
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._temporal_model, self._temporal_scaler = _model.load_artifacts(
                "temporal",
                self._model_dir / "temporal_model.pkl",
                self._model_dir / "temporal_scaler.pkl",
            )
            self._network_model, self._network_scaler = _model.load_artifacts(
                "network",
                self._model_dir / "network_model.pkl",
                self._model_dir / "network_scaler.pkl",
            )
            self._loaded = True

    @property
    def model_available(self) -> bool:
        """True when both contract artifacts (temporal+network) are present."""
        self._ensure_loaded()
        return all(m is not None and s is not None
                   for m, s in ((self._temporal_model, self._temporal_scaler),
                                (self._network_model, self._network_scaler)))

    # -- model-based anomaly scores ---------------------------------------
    def _model_score(self, model, scaler, feat_df: pd.DataFrame, columns) -> Optional[np.ndarray]:
        """IsolationForest score for one feature subset; None if untrained."""
        if model is None or scaler is None:
            return None
        cols = list(getattr(model, "m2_columns_", columns))
        X = scaler.transform(feat_df[cols].to_numpy(dtype=float))
        return _model.anomaly_score_01(model, X)

    # -- interpretable temporal checks -------------------------------------
    def temporal_evidence(self, feat_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Run the temporal/staleness checks and return evidence entries.

        Every check is human-readable; failing checks describe the measured
        value against the configured limit (dashboard-ready, schema §2).
        """
        c = self._checks
        ev: List[Dict[str, Any]] = []

        def add(check: str, passed: bool, detail: str) -> None:
            ev.append({"check": check, "pass": bool(passed), "detail": detail})

        # Clock rewind (replay "frozen clock" signature)
        rew = float(feat_df["m2_ts_rewind_s"].max())
        add("Timestamp monotonicity",
            rew <= c["max_ts_rewind_s"],
            f"max clock rewind {rew:.3f} s vs limit {c['max_ts_rewind_s']:.2f} s"
            + (" — stale/replayed stream suspected" if rew > c["max_ts_rewind_s"] else ""))

        # Timestamp gaps / irregular sampling
        gap = float(feat_df["m2_ts_gap_s"].max())
        add("Sampling regularity",
            gap <= c["max_ts_gap_s"],
            f"max timestamp gap {gap:.3f} s vs limit {c['max_ts_gap_s']:.2f} s")

        # Sequence-number integrity
        err = float(feat_df["m2_seq_expected_err"].max())
        dups = int(feat_df["m2_seq_dup"].sum())
        back = float(feat_df["m2_seq_back"].max())
        ok_seq = (err <= c["max_seq_expected_err"]) and (dups == 0) and (back <= c["max_seq_back"])
        add("Sequence-number continuity", ok_seq,
            f"max deviation from expected sequence {err:.0f}, {dups} duplicate(s), "
            f"max backward step {back:.0f} vs limits ({c['max_seq_expected_err']:.0f}, 0, {c['max_seq_back']:.0f})")

        # Previously-transmitted content (replay tell)
        seen = int(feat_df["m2_seq_seen_before"].sum())
        add("Message freshness (no re-broadcast)",
            seen == 0,
            f"{seen} row(s) re-transmit an earlier sequence number"
            + (" — replay/stale data suspected" if seen else ""))

        # Kinematic change-rate regularity
        scr = float(feat_df["m2_speed_change_rate"].max())
        add("Velocity change-rate regularity",
            scr <= c["max_speed_change_rate"],
            f"max speed change rate {scr:.2f} /s vs limit {c['max_speed_change_rate']:.1f} /s")

        # dt irregularity
        ratio = float(feat_df["m2_dt_ratio"].max())
        add("Inter-sample interval stability",
            ratio <= c["max_dt_ratio"],
            f"max dt/median-dt ratio {ratio:.2f} vs limit {c['max_dt_ratio']:.1f}")
        return ev

    # -- interpretable network checks ---------------------------------------
    def network_evidence(self, feat_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Run the §10 network/telemetry checks and return evidence entries."""
        net = self._net
        ev: List[Dict[str, Any]] = []

        def add(check: str, passed: bool, detail: str) -> None:
            ev.append({"check": check, "pass": bool(passed), "detail": detail})

        iat_med = float(np.median(feat_df["m2_pkt_iat_ms"])) if len(feat_df) else 0.0
        worst_iat = float(feat_df["m2_pkt_iat_ms"].max())
        spike = float(feat_df["m2_pkt_iat_excess_ms"].max())
        ok_spike = spike <= net["iat_spike_ms"]
        add("Packet inter-arrival spikes", ok_spike,
            f"Packet inter-arrival spike: {worst_iat:.0f} ms (normal ~{iat_med:.0f} ms)"
            + (" — possible replay/communication anomaly" if not ok_spike else ""))

        bursts = int(feat_df["m2_pkt_iat_burst"].sum())
        add("Inter-arrival burst pattern", bursts <= max(1, int(0.05 * len(feat_df))),
            f"{bursts} catch-up burst row(s) (inter-arrival < 50% of median)")

        loss = float(feat_df["m2_pkt_loss"].max())
        add("Packet loss", loss <= net["max_pkt_loss"],
            f"max packet loss {loss:.1%} vs limit {net['max_pkt_loss']:.1%}")

        deficit = float(feat_df["m2_pkt_rate_deficit"].max())
        add("Packet rate stability", deficit <= net["max_rate_drop_frac"],
            f"max packet-rate drop {deficit:.1%} below rolling median vs limit {net['max_rate_drop_frac']:.1%}")
        return ev

    # -- main entry point ---------------------------------------------------
    def score(self, row_or_window: RowOrWindow,
              history: Optional[RowOrWindow] = None) -> Dict[str, Any]:
        """Score one observation row or window → schema-§2 message (M2 part).

        Args:
            row_or_window: Single schema-§1 row (dict / 1-row DataFrame) or a
                window DataFrame (e.g. 50 rows @ 10 Hz).
            history: Optional immediately-preceding rows (same schema). When
                given, features are computed over history + window and only
                the window rows are scored. This matters for replay/stale
                detection: a re-delivered block is locally self-consistent,
                so the "seen-before" evidence needs the prior context.

        Returns:
            {"scores": {"temporal_consistency": float 0-1 (higher = trustworthy),
                        "anomaly_temporal": float 0-1 (higher = anomalous),
                        "network_integrity": float 0-1 (higher = trustworthy)},
             "evidence": [{"check", "pass", "detail"}, ...]}
        """
        df = self._as_frame(row_or_window)
        hist_len = 0
        if history is not None and len(history) > 0:
            hist = self._as_frame(history)
            df = pd.concat([hist, df], ignore_index=True)
            hist_len = len(hist)
        feat_all = extract_temporal_features(df)
        feat_df = feat_all.iloc[hist_len:].reset_index(drop=True)

        t_anom = self._model_score(self._temporal_model, self._temporal_scaler,
                                   feat_df, TEMPORAL_FEATURE_COLUMNS)
        n_anom = self._model_score(self._network_model, self._network_scaler,
                                   feat_df, NETWORK_FEATURE_COLUMNS)
        if t_anom is None:
            t_anom = self._heuristic_anomaly(feat_df, temporal=True)
        if n_anom is None:
            n_anom = self._heuristic_anomaly(feat_df, temporal=False)

        # Use max-of-mean-and-p90 to avoid window-mean dilution (§4 threat_model:
        # 50%-interleaved replay dilutes the mean while the max over the window
        # still clears the threshold). The p90 is robust to a few clean rows in
        # an otherwise-attacked window, and the max catches single extreme rows.
        def _agg(x: np.ndarray) -> float:
            x = np.clip(x, 0.0, 1.0)
            return float(max(np.mean(x), np.percentile(x, 90)))

        t_anom_val = float(np.clip(_agg(t_anom), 0.0, 1.0))
        n_anom_val = float(np.clip(_agg(n_anom), 0.0, 1.0))

        ev_t = self.temporal_evidence(feat_df)
        ev_n = self.network_evidence(feat_df)
        temporal_consistency = self._consistency_from_evidence(ev_t, t_anom_val)
        network_integrity = self._consistency_from_evidence(ev_n, n_anom_val)

        return {
            "scores": {
                "temporal_consistency": round(temporal_consistency, 4),
                "anomaly_temporal": round(t_anom_val, 4),
                "network_integrity": round(network_integrity, 4),
            },
            "evidence": ev_t + ev_n,
        }

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _as_frame(row_or_window: RowOrWindow) -> pd.DataFrame:
        """Normalize dict/row-list/DataFrame input to a DataFrame."""
        if isinstance(row_or_window, pd.DataFrame):
            df = row_or_window
        elif isinstance(row_or_window, dict):
            df = pd.DataFrame([row_or_window])
        else:  # sequence of dicts
            df = pd.DataFrame(list(row_or_window))
        if df.empty:
            raise ValueError("score_observation: empty input")
        return df

    def _heuristic_anomaly(self, feat_df: pd.DataFrame, temporal: bool) -> np.ndarray:
        """Fallback anomaly score from normalized feature excess (no model).

        Uses the configured evidence limits so behaviour matches the evidence
        checks even before artifacts exist.
        """
        c, net = self._checks, self._net
        if temporal:
            parts = [
                np.clip(feat_df["m2_ts_rewind_s"].to_numpy() / max(c["max_ts_rewind_s"], 1e-6), 0, 1),
                np.clip(feat_df["m2_ts_gap_s"].to_numpy() / max(c["max_ts_gap_s"], 1e-6), 0, 1),
                np.clip(feat_df["m2_seq_expected_err"].to_numpy() / max(c["max_seq_expected_err"], 1e-6), 0, 1),
                np.clip(feat_df["m2_seq_seen_before"].to_numpy(), 0, 1),
                np.clip(feat_df["m2_seq_dup"].to_numpy(), 0, 1),
                np.clip(feat_df["m2_speed_change_rate"].to_numpy() / max(c["max_speed_change_rate"], 1e-6), 0, 1),
            ]
        else:
            parts = [
                np.clip(feat_df["m2_pkt_iat_excess_ms"].to_numpy() / max(net["iat_spike_ms"], 1e-6), 0, 1),
                np.clip(feat_df["m2_pkt_iat_burst"].to_numpy() * 0.6, 0, 1),
                np.clip(feat_df["m2_pkt_loss_excess"].to_numpy() / max(net["max_pkt_loss"], 1e-6), 0, 1),
                np.clip(feat_df["m2_pkt_rate_deficit"].to_numpy() / max(net["max_rate_drop_frac"], 1e-6), 0, 1),
            ]
        per_row = np.clip(np.mean(np.vstack(parts), axis=0), 0.0, 1.0)
        # Blend mean with p90 to resist window-mean dilution (replay: 50% clean rows).
        return np.clip(np.maximum(np.mean(per_row), np.percentile(per_row, 90)), 0.0, 1.0)

    def _consistency_from_evidence(self, ev: List[Dict[str, Any]],
                                   anomaly_val: float) -> float:
        """*_consistency / *_integrity from failing checks + anomaly score.

        Weight: each failing check costs 0.15, then the score is blended with
        the continuous anomaly score (bounded below by 0.05).
        """
        n_fail = sum(1 for e in ev if not e["pass"])
        base = 1.0 - 0.15 * n_fail
        return float(max(0.05, 0.5 * base + 0.5 * (1.0 - float(anomaly_val))))


_MODULE_SCORER: Optional[TemporalScorer] = None


def get_scorer() -> TemporalScorer:
    """Return the module-level scorer (lazy singleton)."""
    global _MODULE_SCORER
    if _MODULE_SCORER is None:
        _MODULE_SCORER = TemporalScorer()
    return _MODULE_SCORER


def score_observation(window_df: RowOrWindow,
                      history: Optional[RowOrWindow] = None) -> Dict[str, Any]:
    """Contract function: one row/window → M2 score message (schema §2).

    See :meth:`TemporalScorer.score` for the exact output shape; *history*
    (optional prior rows) enables replay detection across window boundaries.
    """
    return get_scorer().score(window_df, history=history)


def score_message_summary(msg: Dict[str, Any]) -> str:
    """One-line human-readable summary of a score message (for logs/demo)."""
    s = msg.get("scores", {})
    fails = [e["check"] for e in msg.get("evidence", []) if not e.get("pass", True)]
    tail = f" | failing: {', '.join(fails)}" if fails else ""
    return (f"temporal_consistency={s.get('temporal_consistency', float('nan')):.2f} "
            f"anomaly_temporal={s.get('anomaly_temporal', float('nan')):.2f} "
            f"network_integrity={s.get('network_integrity', float('nan')):.2f}{tail}")
