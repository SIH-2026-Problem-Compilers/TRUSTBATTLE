"""TRUSTBATTLE — Member 1 anomaly models (Layer 2, about_project.txt §8).

Isolation Forest is the primary detector (per project plan); One-Class SVM is
kept as a comparison baseline. Artifacts (joblib) live in models/physical/
per data_schema.md §4:

    isolation_forest.pkl   — sklearn IsolationForest + M1 calibration attrs
    feature_scaler.pkl     — sklearn StandardScaler over m1_* feature columns

Score convention (data_schema.md §3): anomaly score in [0, 1], higher = more
anomalous. Normalization anchors (score floor/ceiling) and the alert threshold
(calibrated on clean holdout for a target false-positive rate) are stored as
attributes on the model object so the .pkl is fully self-describing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

try:  # pyyaml is not in the shared requirements.txt; degrade gracefully
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from .features import FEATURE_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = REPO_ROOT / "models" / "physical" / "isolation_forest.pkl"
DEFAULT_SCALER_PATH = REPO_ROOT / "models" / "physical" / "feature_scaler.pkl"
DEFAULT_BASELINE_PATH = REPO_ROOT / "models" / "physical" / "oneclass_svm_baseline.pkl"
SETTINGS_PATH = REPO_ROOT / "configs" / "settings.yaml"

_SETTINGS_CACHE: Optional[dict] = None


def load_settings() -> dict:
    """Load configs/settings.yaml (cached). Returns {} when unavailable."""
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is None:
        if yaml is not None and SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                _SETTINGS_CACHE = yaml.safe_load(fh) or {}
        else:
            _SETTINGS_CACHE = {}
    return _SETTINGS_CACHE


def _deep_get(d: dict, dotted: str, default):
    """Fetch a nested value via a dotted path, e.g. 'physical.anomaly.n_estimators'."""
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def model_settings() -> dict:
    """M1 tunables from configs/settings.yaml with code-level defaults."""
    cfg = load_settings()
    checks = _deep_get(cfg, "physical.checks", {}) or {}
    return {
        "n_estimators": int(_deep_get(cfg, "physical.anomaly.n_estimators", 200)),
        "contamination": _deep_get(cfg, "physical.anomaly.contamination", "auto"),
        "random_state": int(_deep_get(cfg, "physical.anomaly.random_state", 42)),
        "fpr_target": float(_deep_get(cfg, "physical.anomaly.fpr_target", 0.01)),
        "ocsvm_nu": float(_deep_get(cfg, "physical.ocsvm.nu", 0.02)),
        "ocsvm_kernel": str(_deep_get(cfg, "physical.ocsvm.kernel", "rbf")),
        "threshold_percentile": float(_deep_get(cfg, "physical.threshold_percentile", 0.999)),
        "checks": {
            "max_position_residual_m": float(checks.get("max_position_residual_m", 25.0)),
            "max_velocity_residual_mps": float(checks.get("max_velocity_residual_mps", 22.0)),
            "max_speed_excess_mps": float(checks.get("max_speed_excess_mps", 0.0)),
            "max_accel_inconsistency": float(checks.get("max_accel_inconsistency", 0.60)),
            "max_heading_residual_deg": float(checks.get("max_heading_residual_deg", 30.0)),
            "max_course_mismatch_deg": float(checks.get("max_course_mismatch_deg", 45.0)),
            "max_speed_component_mismatch_mps": float(checks.get("max_speed_component_mismatch_mps", 3.0)),
            "max_smoothness_deg_s": float(checks.get("max_smoothness_deg_s", 15.0)),
            "max_deviation_sigma": float(checks.get("max_deviation_sigma", 6.0)),
            "min_gnss_quality": float(checks.get("min_gnss_quality", 0.30)),
        },
        "historical_max_speed_mps": float(_deep_get(cfg, "physical.historical_max_speed_mps", 22.0)),
        "min_course_speed_mps": float(_deep_get(cfg, "physical.min_course_speed_mps", 1.5)),
        "severity_cap_multiplier": float(_deep_get(cfg, "physical.severity_cap_multiplier", 4.0)),
    }


def load_artifacts(
    model_path: Optional[Path] = None, scaler_path: Optional[Path] = None
) -> Tuple[Optional[object], Optional[object]]:
    """Load (isolation_forest, scaler) joblib artifacts if they exist.

    Returns:
        (model, scaler) — either element is None when the file is missing,
        so the module stays importable before training has run.
    """
    mp = Path(model_path) if model_path else DEFAULT_MODEL_PATH
    sp = Path(scaler_path) if scaler_path else DEFAULT_SCALER_PATH
    model = joblib.load(mp) if mp.exists() else None
    scaler = joblib.load(sp) if sp.exists() else None
    return model, scaler


def fit_scaler(feature_df: pd.DataFrame):
    """Fit a StandardScaler on the m1_* feature columns (TASK 3 artifact)."""
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(feature_df[FEATURE_COLUMNS].to_numpy(dtype=float))
    return scaler


def train_model(feature_df: pd.DataFrame, settings: Optional[dict] = None):
    """Fit the primary IsolationForest on clean features (TASK 3).

    Normalization anchors are learned from clean data and stored on the model:
    ``m1_score_floor_`` (≈0 point) and ``m1_score_ceiling_`` (≈1 point, the
    clean p99.9 — attacks saturate at 1.0).
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    s = settings or model_settings()
    model = IsolationForest(
        n_estimators=s["n_estimators"],
        contamination=s["contamination"],
        random_state=s["random_state"],
    )
    # Everything (training, scoring, both models) lives in the SAME scaled
    # space so consumers can always do scaler.transform -> model.
    X = feature_df[FEATURE_COLUMNS].to_numpy(dtype=float)
    Xs = StandardScaler().fit(X).transform(X)
    model.fit(Xs)
    raw = -model.decision_function(Xs)
    # Normalization anchors for anomaly_score_01: clean median -> 0, clean
    # p99.9 -> 1, attacks saturate at 1.0 (schema §3).
    model.m1_score_floor_ = float(np.median(raw))
    model.m1_score_ceiling_ = float(max(np.quantile(raw, s["threshold_percentile"]), model.m1_score_floor_ + 1e-9))
    return model


def anomaly_score_01(model, X: np.ndarray) -> np.ndarray:
    """IsolationForest score → [0, 1], higher = more anomalous (schema §3).

    Uses the anchors learned in :func:`train_model`; values at/above the clean
    ceiling map to 1.0, values at/below the floor map to 0.0.
    """
    raw = -model.decision_function(np.asarray(X, dtype=float))
    floor = float(getattr(model, "m1_score_floor_", np.min(raw)))
    ceiling = float(getattr(model, "m1_score_ceiling_", np.max(raw)))
    return np.clip((raw - floor) / max(ceiling - floor, 1e-9), 0.0, 1.0)


def calibrate_threshold(model, scaler, clean_holdout: pd.DataFrame, fpr_target: float) -> float:
    """Choose the alert threshold on a clean holdout for a target FPR.

    Threshold = (1 - fpr_target)-quantile of anomaly scores on clean data,
    stored on the model as ``m1_threshold_`` and returned.
    """
    X = scaler.transform(clean_holdout[FEATURE_COLUMNS].to_numpy(dtype=float))
    scores = anomaly_score_01(model, X)
    threshold = float(np.quantile(scores, 1.0 - fpr_target))
    model.m1_threshold_ = threshold
    model.m1_fpr_target_ = float(fpr_target)
    return threshold


def train_ocsvm_baseline(feature_df: pd.DataFrame, scaler, settings: Optional[dict] = None):
    """Fit the One-Class SVM comparison baseline on SCALED features."""
    from sklearn.svm import OneClassSVM

    s = settings or model_settings()
    Xs = scaler.transform(feature_df[FEATURE_COLUMNS].to_numpy(dtype=float))
    return OneClassSVM(nu=s["ocsvm_nu"], kernel=s["ocsvm_kernel"], gamma="scale").fit(Xs)
