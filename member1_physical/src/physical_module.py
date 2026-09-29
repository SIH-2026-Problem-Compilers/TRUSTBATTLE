"""TRUSTBATTLE — Member 1 physical scoring (TASK 4).

Produces the per-observation score message defined in data_schema.md §2/§3:

    {"scores": {"physical_consistency": 0-1 (higher = trustworthy),
                "anomaly_physical":    0-1 (higher = anomalous)},
     "evidence": [{"check": ..., "pass": true/false, "detail": ...}]}

Entry point (registered by integration/pipeline.py as ``score_physical``):
    score_observation(row_or_window) -> dict

Accepts a single schema-§1 row (dict or 1-row DataFrame) or a window DataFrame
(e.g. 50 rows @ 10 Hz). Evidence strings are human-readable — they appear on
the Member 5 dashboard, e.g.
    "GNSS/IMU velocity disagreement: 65 m/s vs historical max 22 m/s".

The module imports with zero side effects: models are lazily loaded and the
evidence checks work from configs/settings.yaml alone if no artifacts exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from .features import FEATURE_COLUMNS, extract_physical_features
from . import model as _model

RowOrWindow = Union[Dict[str, Any], List[Dict[str, Any]], pd.DataFrame]


class PhysicalScorer:
    """Scores observations using trained artifacts + interpretable physics checks.

    Instantiate once and reuse (artifact loading happens on first use).
    """

    def __init__(self, model_path: Optional[Path] = None, scaler_path: Optional[Path] = None):
        self._model_path = model_path
        self._scaler_path = scaler_path
        self._model = None
        self._scaler = None
        self._loaded = False
        self._hist_speed: Optional[float] = None
        self.settings = _model.model_settings()
        self._checks = self.settings["checks"]

    # -- lazy artifact loading ------------------------------------------
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._model, self._scaler = _model.load_artifacts(self._model_path, self._scaler_path)
            self._hist_speed = self._load_hist_speed()
            self._loaded = True

    def _load_hist_speed(self) -> Optional[float]:
        """Re-learned historical max speed from models/physical/physical_limits.json."""
        path = _model.DEFAULT_MODEL_PATH.parent / "physical_limits.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return float(json.load(fh).get("historical_max_speed_mps"))
            except (ValueError, OSError):
                return None
        return None

    @property
    def model_available(self) -> bool:
        """True when models/physical/isolation_forest.pkl is present."""
        self._ensure_loaded()
        return self._model is not None and self._scaler is not None

    # -- model-based anomaly score ---------------------------------------
    def model_anomaly_score(self, feat_df: pd.DataFrame) -> Optional[np.ndarray]:
        """IsolationForest anomaly score in [0,1]; None if untrained."""
        self._ensure_loaded()
        if self._model is None or self._scaler is None:
            return None
        X = self._scaler.transform(feat_df[FEATURE_COLUMNS].to_numpy(dtype=float))
        return _model.anomaly_score_01(self._model, X)

    # -- interpretable physics checks -------------------------------------
    def physics_evidence(self, feat_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Run the §7 physics checks and return evidence entries.

        Every check is human-readable; failing checks describe the measured
        value against the historical/configured limit.
        """
        c = self._checks
        ev: List[Dict[str, Any]] = []
        cap = self.settings["severity_cap_multiplier"]

        def add(check: str, passed: bool, detail: str) -> None:
            ev.append({"check": check, "pass": bool(passed), "detail": detail})

        # Position residual: GNSS vs velocity-propagated position
        pos = feat_df["m1_position_residual_m"]
        worst_pos = float(pos.max())
        add("GNSS/IMU position residual",
            worst_pos <= c["max_position_residual_m"],
            f"max position residual {worst_pos:.1f} m vs limit {c['max_position_residual_m']:.0f} m")

        # Velocity residual — the §7 example: "65 m/s vs historical max 22 m/s"
        vel = feat_df["m1_velocity_residual_mps"]
        worst_vel = float(vel.max())
        i_vel = int(np.argmax(vel.to_numpy()))
        add("GNSS/IMU velocity disagreement",
            worst_vel <= c["max_velocity_residual_mps"],
            f"GNSS/IMU velocity disagreement: {worst_vel:.0f} m/s vs historical max {c['max_velocity_residual_mps']:.0f} m/s"
            f" (reported speed {float(feat_df['m1_speed_mps'].iloc[i_vel]):.0f} m/s)")

        # Speed beyond historical max (about_project §7)
        exc = feat_df["m1_speed_excess_mps"]
        worst_exc = float(exc.max())
        hist = self._hist_speed if self._hist_speed is not None else self.settings["historical_max_speed_mps"]
        if worst_exc > 0:
            i_exc = int(np.argmax(exc.to_numpy()))
            reported = float(feat_df["m1_speed_mps"].iloc[i_exc])
            add("Historical speed envelope",
                worst_exc <= max(c["max_speed_excess_mps"], 0.0),
                f"GNSS reports {reported:.0f} m/s vs historical max {hist:.0f} m/s (+{worst_exc:.0f} m/s)")
        else:
            add("Historical speed envelope", True,
                f"GNSS speed within historical max ({hist:.0f} m/s)")

        # Acceleration consistency (median-smoothed: raw derivative noise from
        # GNSS jitter would otherwise fail clean windows; sustained
        # inconsistency survives the filter)
        acc_r = feat_df["m1_accel_residual_mps2"].rolling(5, center=True, min_periods=1).median()
        worst_acc = float(acc_r.max())
        add("Acceleration consistency",
            worst_acc <= c["max_accel_inconsistency"],
            f"accel inconsistency {worst_acc:.2f} m/s² vs limit {c['max_accel_inconsistency']:.2f} m/s²")

        # Heading consistency
        hdg = feat_df["m1_heading_residual_deg"]
        worst_hdg = float(hdg.max())
        add("Heading consistency (gyro-integrated)",
            worst_hdg <= c["max_heading_residual_deg"],
            f"max heading residual {worst_hdg:.1f}° vs limit {c['max_heading_residual_deg']:.0f}°")

        # Course vs heading
        crs = feat_df["m1_course_heading_residual_deg"]
        moving = feat_df["m1_speed_mps"] >= self.settings["min_course_speed_mps"]
        worst_crs = float(crs[moving].max()) if moving.any() else 0.0
        add("Course vs heading agreement",
            worst_crs <= c["max_course_mismatch_deg"],
            f"max course/heading mismatch {worst_crs:.1f}° vs limit {c['max_course_mismatch_deg']:.0f}°")

        # GNSS internal consistency (velocity magnitude vs components)
        comp = feat_df["m1_speed_component_residual_mps"]
        worst_comp = float(comp.max())
        add("GNSS velocity-component consistency",
            worst_comp <= c["max_speed_component_mismatch_mps"],
            f"velocity vs (vx,vy,vz) mismatch {worst_comp:.1f} m/s vs limit {c['max_speed_component_mismatch_mps']:.1f} m/s")

        # Trajectory smoothness & deviation
        sm_h = float(feat_df["m1_smoothness_heading_deg_s"].max())
        add("Trajectory smoothness (heading rate)",
            sm_h <= c["max_smoothness_deg_s"],
            f"heading-rate dispersion {sm_h:.1f}°/s vs limit {c['max_smoothness_deg_s']:.0f}°/s")
        dev = float(feat_df["m1_traj_deviation_sigma"].max())
        add("Trajectory deviation",
            dev <= c["max_deviation_sigma"],
            f"max track deviation {dev:.1f}σ vs limit {c['max_deviation_sigma']:.1f}σ")

        # GNSS signal quality
        q = float(feat_df["m1_gnss_quality"].min())
        add("GNSS signal quality",
            q >= c["min_gnss_quality"],
            f"min GNSS quality {q:.2f} vs floor {c['min_gnss_quality']:.2f}")

        # annotate severity (0..1) for the trust engine — attached via detail only,
        # the contract evidence dict stays exactly {check, pass, detail}.
        return ev

    # -- main entry point --------------------------------------------------
    def score(self, row_or_window: RowOrWindow) -> Dict[str, Any]:
        """Score one observation row or window → schema-§2 message (M1 part).

        Returns:
            {"scores": {"physical_consistency": float 0-1 (higher = trustworthy),
                        "anomaly_physical": float 0-1 (higher = anomalous)},
             "evidence": [{"check", "pass", "detail"}, ...]}
        """
        df = self._as_frame(row_or_window)
        feat_df = extract_physical_features(df)

        # Fill the historical-envelope feature with the learned limit so the
        # model sees it exactly as calibrated during training.
        self._ensure_loaded()
        if self._hist_speed is not None:
            feat_df["m1_speed_excess_mps"] = np.maximum(
                0.0, feat_df["m1_speed_mps"].to_numpy(dtype=float) - self._hist_speed
            )

        anomaly = self.model_anomaly_score(feat_df)
        if anomaly is None:
            # No trained artifacts yet: fall back to a transparent weighted
            # normalized-disagreement score so scoring always works.
            anomaly = self._heuristic_anomaly(feat_df)
        anomaly_val = float(np.clip(np.mean(anomaly), 0.0, 1.0))

        ev = self.physics_evidence(feat_df)
        consistency = self._consistency_from_evidence(ev, feat_df)

        return {
            "scores": {
                "physical_consistency": round(consistency, 4),
                "anomaly_physical": round(anomaly_val, 4),
            },
            "evidence": ev,
        }

    # -- helpers ------------------------------------------------------------
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

    def _heuristic_anomaly(self, feat_df: pd.DataFrame) -> np.ndarray:
        """Fallback anomaly score from normalized disagreements (no model)."""
        scale = self.settings["severity_cap_multiplier"]
        parts = [
            np.clip(feat_df["m1_position_residual_m"] / (self._checks["max_position_residual_m"] * scale), 0, 1),
            np.clip(feat_df["m1_velocity_residual_mps"] / (self._checks["max_velocity_residual_mps"] * scale), 0, 1),
            np.clip(feat_df["m1_accel_residual_mps2"] / (self._checks["max_accel_inconsistency"] * scale), 0, 1),
            np.clip(feat_df["m1_heading_residual_deg"] / (self._checks["max_heading_residual_deg"] * scale), 0, 1),
            np.clip(feat_df["m1_traj_deviation_sigma"] / (self._checks["max_deviation_sigma"] * scale), 0, 1),
        ]
        return np.clip(np.mean(np.vstack(parts), axis=0), 0.0, 1.0)

    def _consistency_from_evidence(self, ev: List[Dict[str, Any]], feat_df: pd.DataFrame) -> float:
        """physical_consistency from failing checks + continuous severity.

        Weight: each failing check costs 0.15, then the score is blended with
        the continuous normalized-disagreement severity (bounded below by 0.05).
        """
        n_fail = sum(1 for e in ev if not e["pass"])
        base = 1.0 - 0.15 * n_fail
        sev = float(np.clip(self._heuristic_anomaly(feat_df).mean(), 0.0, 1.0))
        return float(max(0.05, 0.5 * base + 0.5 * (1.0 - sev)))


_MODULE_SCORER: Optional[PhysicalScorer] = None


def get_scorer() -> PhysicalScorer:
    """Return the module-level scorer (lazy singleton)."""
    global _MODULE_SCORER
    if _MODULE_SCORER is None:
        _MODULE_SCORER = PhysicalScorer()
    return _MODULE_SCORER


def score_observation(row_or_window: RowOrWindow) -> Dict[str, Any]:
    """Contract function: one row/window → M1 score message (schema §2).

    See :meth:`PhysicalScorer.score` for the exact output shape.
    """
    return get_scorer().score(row_or_window)
