"""TRUSTBATTLE — Member 2 training script (TASK 4).

Trains the temporal and network anomaly detectors on clean data and
calibrates the alert thresholds on a clean holdout, then saves the contract
artifacts (data_schema.md §4):

    models/temporal/temporal_model.pkl     (primary — sklearn IsolationForest)
    models/temporal/network_model.pkl      (primary — sklearn IsolationForest)
    models/temporal/temporal_scaler.pkl / network_scaler.pkl
    models/temporal/temporal_ocsvm_baseline.pkl / network_ocsvm_baseline.pkl
    models/temporal/temporal_limits.json / network_limits.json

Data source: data/synthetic/ (Member 4). Until M4 ships, a clearly-marked
in-memory fallback generator (src/fallback_data.py) stands in — rerun this
script when real data lands.

Usage (from repo root):
    py -m member2_temporal.src.train
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from member2_temporal.src import data_loader, model as m2_model  # noqa: E402
from member2_temporal.src.features import (  # noqa: E402
    FEATURE_COLUMNS,
    NETWORK_FEATURE_COLUMNS,
    TEMPORAL_FEATURE_COLUMNS,
    extract_temporal_features,
    learned_limits,
)

MODELS_DIR = m2_model.MODELS_DIR


def _load_clean_features():
    """Features from data/synthetic/ if available, else the fallback generator.

    Threshold calibration happens on WINDOW-MEAN scores, so the clean holdout
    must contain enough windows (~200) for a stable tail estimate.
    """
    synth = data_loader._coerce("data/synthetic")
    files = sorted(synth.glob("*.parquet")) + sorted(synth.glob("*.csv")) if synth.exists() else []
    if files:
        clean = data_loader.load_synthetic_directory(synth)
        source = f"Member 4 data: {synth} ({len(files)} file(s), {len(clean)} rows)"
    else:
        from member2_temporal.src.fallback_data import make_normal
        clean = make_normal(n=48_000)
        source = "FALLBACK generator (member2_temporal/src/fallback_data.py) — data/synthetic/ is empty"
    clean = clean.dropna(subset=["timestamp"]).reset_index(drop=True)
    # split before/after so the model never sees the rows it will be calibrated on
    split = int(len(clean) * 0.8)
    train = extract_temporal_features(clean.iloc[:split].reset_index(drop=True))
    holdout = extract_temporal_features(clean.iloc[split:].reset_index(drop=True))
    print(f"[train] clean source: {source}")
    print(f"[train] train rows: {len(train)}, clean holdout rows: {len(holdout)} "
          f"(~{len(holdout) // 50} calibration windows)")
    return train, holdout


def main() -> int:
    """Train both detectors, calibrate thresholds, save artifacts."""
    print("=" * 60)
    print("TRUSTBATTLE M2 — training temporal + network detectors (TASK 4)")
    print("=" * 60)

    settings = m2_model.model_settings()
    train, holdout = _load_clean_features()

    artifacts = {
        "temporal": m2_model.train_temporal_model(train, settings),
        "network": m2_model.train_network_model(train, settings),
    }
    thresholds = {}
    ocsvms = {}
    # The runtime alert rule is the UNION of the two detectors, so each one is
    # calibrated at fpr_target/2 (Šidák correction) to land the COMBINED
    # false-positive rate at the configured target.
    eff_fpr = settings["fpr_target"] / 2.0
    for kind, (iso, scaler) in artifacts.items():
        threshold = m2_model.calibrate_threshold(iso, scaler, holdout,
                                                 fpr_target=eff_fpr, skip_windows=2)
        thresholds[kind] = threshold
        columns = TEMPORAL_FEATURE_COLUMNS if kind == "temporal" else NETWORK_FEATURE_COLUMNS
        # One-Class SVM (SMO) scales ~quadratically — subsample for the baseline
        ocsvm_train = train.sample(n=min(6000, len(train)), random_state=settings["random_state"])
        ocsvm = m2_model.train_ocsvm_baseline(ocsvm_train, scaler, columns, settings)
        ocsvms[kind] = ocsvm
        ocsvm_scores = m2_model.ocsvm_score_01(ocsvm, scaler, holdout, columns,
                                                    train[columns].to_numpy(dtype=float))
        # Skip first 2 windows (startup transients) for OCSVM calibration too
        ocsvm_win = np.array([float(ocsvm_scores[i * 50:(i + 1) * 50].mean())
                              for i in range(len(ocsvm_scores) // 50)])
        ocsvm_win = ocsvm_win[2:] if len(ocsvm_win) > 2 else ocsvm_win
        thresholds[kind + "_ocsvm"] = float(np.quantile(ocsvm_win, 1.0 - eff_fpr))

        scores_train = m2_model.anomaly_score_01(
            iso, scaler.transform(train[iso.m2_columns_].to_numpy(dtype=float)))
        scores_hold = m2_model.anomaly_score_01(
            iso, scaler.transform(holdout[iso.m2_columns_].to_numpy(dtype=float)))
        # Also show window-aggregated stats (the alert unit) for transparency
        wavgs = m2_model.window_agg_scores(iso, scaler, holdout)
        print(f"[train] {kind}: clean train mean={scores_train.mean():.3f} "
              f"p99={np.quantile(scores_train, 0.99):.3f} | "
              f"holdout row mean={scores_hold.mean():.3f} max={scores_hold.max():.3f} | "
              f"window agg mean={wavgs.mean():.3f} max={wavgs.max():.3f}")
        print(f"[train] {kind}: alert threshold for per-detector FPR<={eff_fpr:.4f} "
              f"(union target {settings['fpr_target']:.3f}): {threshold:.4f} "
              f"(ocsvm {thresholds[kind + '_ocsvm']:.4f})")

    limits = {
        "temporal": learned_limits(train, percentile=settings["threshold_percentile"]),
        "network": learned_limits(train[NETWORK_FEATURE_COLUMNS], percentile=settings["threshold_percentile"]),
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(artifacts["temporal"][0], m2_model.DEFAULT_TEMPORAL_MODEL_PATH)
    joblib.dump(artifacts["temporal"][1], m2_model.DEFAULT_TEMPORAL_SCALER_PATH)
    joblib.dump(artifacts["network"][0], m2_model.DEFAULT_NETWORK_MODEL_PATH)
    joblib.dump(artifacts["network"][1], m2_model.DEFAULT_NETWORK_SCALER_PATH)
    joblib.dump(ocsvms["temporal"], m2_model.DEFAULT_TEMPORAL_OCSVM_PATH)
    joblib.dump(ocsvms["network"], m2_model.DEFAULT_NETWORK_OCSVM_PATH)
    with open(m2_model.DEFAULT_TEMPORAL_LIMITS_PATH, "w", encoding="utf-8") as fh:
        json.dump(limits["temporal"], fh, indent=2)
    with open(m2_model.DEFAULT_NETWORK_LIMITS_PATH, "w", encoding="utf-8") as fh:
        json.dump(limits["network"], fh, indent=2)

    print(f"[train] artifacts saved to {MODELS_DIR}:")
    for p in sorted(MODELS_DIR.glob("*")):
        print(f"        - {p.name} ({p.stat().st_size / 1024:.1f} KB)")
    print("[train] done. Rerun after Member 4's real data lands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
