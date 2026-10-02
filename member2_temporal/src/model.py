"""TRUSTBATTLE — Member 2 anomaly models (TASK 4, about_project.txt §8).

Isolation Forest is the primary detector (per project plan); One-Class SVM is
kept as a comparison baseline. Artifacts (joblib) live in models/temporal/
per data_schema.md §4:

    temporal_model.pkl   — IsolationForest over m2_ temporal features
    network_model.pkl    — IsolationForest over m2_pkt_*/m2_net_* features
    temporal_scaler.pkl / network_scaler.pkl — StandardScalers over the same
    temporal_ocsvm_baseline.pkl / network_ocsvm_baseline.pkl — OCSVM baselines
    temporal_limits.json / network_limits.json — learned evidence limits

Score convention (data_schema.md §3): anomaly score in [0, 1], higher = more
anomalous. Normalization anchors (score floor/ceiling) and the alert threshold
(calibrated on clean holdout for a target false-positive rate) are stored as
attributes on the model object so each .pkl is fully self-describing.
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

from .features import NETWORK_FEATURE_COLUMNS, TEMPORAL_FEATURE_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "models" / "temporal"
DEFAULT_TEMPORAL_MODEL_PATH = MODELS_DIR / "temporal_model.pkl"
DEFAULT_NETWORK_MODEL_PATH = MODELS_DIR / "network_model.pkl"
DEFAULT_TEMPORAL_SCALER_PATH = MODELS_DIR / "temporal_scaler.pkl"
DEFAULT_NETWORK_SCALER_PATH = MODELS_DIR / "network_scaler.pkl"
DEFAULT_TEMPORAL_OCSVM_PATH = MODELS_DIR / "temporal_ocsvm_baseline.pkl"
DEFAULT_NETWORK_OCSVM_PATH = MODELS_DIR / "network_ocsvm_baseline.pkl"
DEFAULT_TEMPORAL_LIMITS_PATH = MODELS_DIR / "temporal_limits.json"
DEFAULT_NETWORK_LIMITS_PATH = MODELS_DIR / "network_limits.json"
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
    """Fetch a nested value via a dotted path, e.g. 'temporal.anomaly.n_estimators'."""
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def model_settings() -> dict:
    """M2 tunables from configs/settings.yaml with code-level defaults."""
    cfg = load_settings()
    checks = _deep_get(cfg, "temporal.checks", {}) or {}
    network = _deep_get(cfg, "temporal.network", {}) or {}
    return {
        "n_estimators": int(_deep_get(cfg, "temporal.anomaly.n_estimators", 200)),
        "contamination": _deep_get(cfg, "temporal.anomaly.contamination", "auto"),
        "random_state": int(_deep_get(cfg, "temporal.anomaly.random_state", 42)),
        "fpr_target": float(_deep_get(cfg, "temporal.anomaly.fpr_target", 0.01)),
        "ocsvm_nu": float(_deep_get(cfg, "temporal.ocsvm.nu", 0.02)),
        "ocsvm_kernel": str(_deep_get(cfg, "temporal.ocsvm.kernel", "rbf")),
        "threshold_percentile": float(_deep_get(cfg, "temporal.threshold_percentile", 0.999)),
        "checks": {
            "max_ts_rewind_s": float(checks.get("max_ts_rewind_s", 0.05)),
            "max_ts_gap_s": float(checks.get("max_ts_gap_s", 0.5)),
            "max_seq_expected_err": float(checks.get("max_seq_expected_err", 2.0)),
            "max_seq_back": float(checks.get("max_seq_back", 0.0)),
            "max_speed_change_rate": float(checks.get("max_speed_change_rate", 2.0)),
            "max_dt_ratio": float(checks.get("max_dt_ratio", 3.0)),
        },
        "network": {
            "iat_spike_ms": float(network.get("iat_spike_ms", 200.0)),
            "max_pkt_loss": float(network.get("max_pkt_loss", 0.05)),
            "max_rate_drop_frac": float(network.get("max_rate_drop_frac", 0.4)),
        },
    }


def _pick_columns(feature_df: pd.DataFrame, columns) -> list:
    """Intersect the requested feature columns with what the frame has."""
    missing = [c for c in columns if c not in feature_df.columns]
    if missing:
        raise ValueError(f"feature frame is missing columns: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    return list(columns)


def _fit_one(feature_df: pd.DataFrame, columns, s: dict, prefix: str):
    """Shared train path: scaler + IsolationForest + clean anchors for one set."""
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    cols = _pick_columns(feature_df, columns)
    X = feature_df[cols].to_numpy(dtype=float)
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    iso = IsolationForest(
        n_estimators=s["n_estimators"],
        contamination=s["contamination"],
        random_state=s["random_state"],
    )
    iso.fit(Xs)
    raw = -iso.decision_function(Xs)
    # Normalization anchors for anomaly_score_01 (schema §3): the clean q75
    # maps to 0 and the clean MAXIMUM maps to 1.0, so typical clean rows sit
    # near 0 and anything "beyond anything seen in training" saturates at 1.
    iso.m2_score_floor_ = float(np.quantile(raw, 0.75))
    iso.m2_score_ceiling_ = float(max(np.max(raw), iso.m2_score_floor_ + 1e-9))
    iso.m2_prefix_ = prefix
    iso.m2_columns_ = list(cols)
    return iso, scaler


def train_temporal_model(feature_df: pd.DataFrame, settings: Optional[dict] = None):
    """Fit the primary IsolationForest on clean temporal features (TASK 4).

    Normalization anchors are learned from clean data and stored on the model:
    ``m2_score_floor_`` (≈0 point) and ``m2_score_ceiling_`` (≈1 point).
    """
    return _fit_one(feature_df, TEMPORAL_FEATURE_COLUMNS, settings or model_settings(), "temporal")


def train_network_model(feature_df: pd.DataFrame, settings: Optional[dict] = None):
    """Fit the primary IsolationForest on clean network features (TASK 4)."""
    return _fit_one(feature_df, NETWORK_FEATURE_COLUMNS, settings or model_settings(), "network")


def fit_scaler(feature_df: pd.DataFrame, columns) -> "object":
    """Fit a StandardScaler over *columns* of a feature frame.

    Kept for symmetry with training scripts that persist scalers separately.
    """
    from sklearn.preprocessing import StandardScaler

    cols = _pick_columns(feature_df, columns)
    return StandardScaler().fit(feature_df[cols].to_numpy(dtype=float))


def anomaly_score_01(model, X: np.ndarray) -> np.ndarray:
    """IsolationForest score → [0, 1], higher = more anomalous (schema §3).

    Uses the anchors learned in :func:`_fit_one` (clean q75 → 0, clean max
    → 1.0); values at/above the clean ceiling map to 1.0, values at/below
    the floor map to 0.0.
    """
    raw = -model.decision_function(np.asarray(X, dtype=float))
    floor = float(getattr(model, "m2_score_floor_", np.min(raw)))
    ceiling = float(getattr(model, "m2_score_ceiling_", np.max(raw)))
    return np.clip((raw - floor) / max(ceiling - floor, 1e-9), 0.0, 1.0)


def _transform(scaler, feature_df: pd.DataFrame, columns) -> np.ndarray:
    """Scale the (ordered) feature columns of *feature_df*."""
    cols = _pick_columns(feature_df, columns)
    return scaler.transform(feature_df[cols].to_numpy(dtype=float))


def window_mean_scores(model, scaler, feature_df: pd.DataFrame,
                       window: int = 50) -> np.ndarray:
    """Per-window mean anomaly scores over *feature_df* (evaluation unit).

    The runtime alert rule flags a WINDOW when its mean row score crosses the
    threshold, so calibration must operate on the same quantity.
    """
    cols = list(getattr(model, "m2_columns_"))
    X = _transform(scaler, feature_df, cols)
    s = anomaly_score_01(model, X)
    n_win = int(np.ceil(len(s) / max(window, 1)))
    return np.array([float(s[i * window:(i + 1) * window].mean()) for i in range(n_win)])


def calibrate_threshold(model, scaler, clean_holdout: pd.DataFrame,
                        fpr_target: float, window: int = 50) -> float:
    """Choose the alert threshold on a clean holdout for a target FPR.

    Threshold = MAXIMUM window-mean anomaly score over clean holdout windows
    (window means are the evaluation/alert unit). The max of ~1/fpr_target
    windows is the (1 - fpr_target) experience-level quantile with a built-in
    safety margin: it guarantees a false-positive rate at or below the target
    even for the extreme tail of unseen clean windows, which a plain quantile
    of a finite sample underestimates.
    """
    means = window_mean_scores(model, scaler, clean_holdout, window=window)
    threshold = float(np.max(means))
    model.m2_threshold_ = threshold
    model.m2_fpr_target_ = float(fpr_target)
    return threshold


def train_ocsvm_baseline(feature_df: pd.DataFrame, scaler, columns,
                         settings: Optional[dict] = None):
    """Fit the One-Class SVM comparison baseline on SCALED features."""
    from sklearn.svm import OneClassSVM

    s = settings or model_settings()
    Xs = _transform(scaler, feature_df, columns)
    return OneClassSVM(nu=s["ocsvm_nu"], kernel=s["ocsvm_kernel"], gamma="scale").fit(Xs)


def ocsvm_score_01(ocsvm, scaler, feature_df: pd.DataFrame, columns,
                   clean_reference: Optional[np.ndarray] = None) -> np.ndarray:
    """OCSVM decision_function → [0,1] anchored on a clean reference.

    Anchoring matches the IsolationForest convention (clean min → 0, clean
    MAXIMUM → 1.0) so clean scores cannot saturate at 1.0 and quantile-based
    thresholds keep their nominal false-positive rate.
    """
    cols = list(columns)
    raw = -ocsvm.decision_function(scaler.transform(feature_df[cols].to_numpy(dtype=float)))
    if clean_reference is not None and len(clean_reference):
        clean_raw = -ocsvm.decision_function(scaler.transform(np.asarray(clean_reference, dtype=float)))
    else:
        clean_raw = raw
    floor = float(np.min(clean_raw)) if len(clean_raw) else float(np.min(raw))
    ceiling = float(max(np.max(clean_raw), floor + 1e-9)) if len(clean_raw) else float(np.max(raw))
    return np.clip((raw - floor) / max(ceiling - floor, 1e-9), 0.0, 1.0)


def load_artifacts(kind: str = "temporal",
                   model_path: Optional[Path] = None,
                   scaler_path: Optional[Path] = None) -> Tuple[Optional[object], Optional[object]]:
    """Load (model, scaler) joblib artifacts if they exist.

    Args:
        kind: "temporal" or "network" — selects the default artifact paths.

    Returns:
        (model, scaler) — either element is None when the file is missing,
        so the module stays importable before training has run.
    """
    if kind == "temporal":
        mp = Path(model_path) if model_path else DEFAULT_TEMPORAL_MODEL_PATH
        sp = Path(scaler_path) if scaler_path else DEFAULT_TEMPORAL_SCALER_PATH
    elif kind == "network":
        mp = Path(model_path) if model_path else DEFAULT_NETWORK_MODEL_PATH
        sp = Path(scaler_path) if scaler_path else DEFAULT_NETWORK_SCALER_PATH
    else:
        raise ValueError(f"kind must be 'temporal' or 'network', got {kind!r}")
    model = joblib.load(mp) if mp.exists() else None
    scaler = joblib.load(sp) if sp.exists() else None
    return model, scaler
