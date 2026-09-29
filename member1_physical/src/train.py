"""TRUSTBATTLE — Member 1 training script (TASK 3).

Trains the physical anomaly detector on clean data and calibrates the alert
threshold on a clean holdout, then saves the contract artifacts (data_schema §4):

    models/physical/isolation_forest.pkl      (primary — sklearn IsolationForest)
    models/physical/feature_scaler.pkl        (StandardScaler over m1_* features)
    models/physical/oneclass_svm_baseline.pkl (One-Class SVM comparison baseline)
    models/physical/physical_limits.json      (learned historical limits, evidence)

Data source: data/synthetic/ (Member 4). Until M4 ships, a clearly-marked
in-memory fallback generator (src/fallback_data.py) stands in — rerun this
script when real data lands.

Usage (from repo root):
    py -m member1_physical.src.train
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from member1_physical.src import data_loader, model as m1_model  # noqa: E402
from member1_physical.src.features import FEATURE_COLUMNS, extract_physical_features, learned_limits  # noqa: E402

MODELS_DIR = m1_model.DEFAULT_MODEL_PATH.parent


def _load_clean_features():
    """Features from data/synthetic/ if available, else the fallback generator."""
    synth = data_loader._coerce("data/synthetic")
    files = sorted(synth.glob("*.parquet")) + sorted(synth.glob("*.csv")) if synth.exists() else []
    if files:
        clean = data_loader.load_synthetic_directory(synth)
        source = f"Member 4 data: {synth} ({len(files)} file(s), {len(clean)} rows)"
    else:
        from member1_physical.src.fallback_data import make_normal
        clean = make_normal()
        source = "FALLBACK generator (member1_physical/src/fallback_data.py) — data/synthetic/ is empty"
    clean = clean.dropna(subset=["timestamp"]).reset_index(drop=True)
    # split before/after so the model never sees the rows it will be calibrated on
    split = int(len(clean) * 0.8)
    train = extract_physical_features(clean.iloc[:split].reset_index(drop=True))
    holdout = extract_physical_features(clean.iloc[split:].reset_index(drop=True))
    print(f"[train] clean source: {source}")
    print(f"[train] train rows: {len(train)}, clean holdout rows: {len(holdout)}")
    return train, holdout


def main() -> int:
    print("=" * 60)
    print("TRUSTBATTLE M1 — training physical anomaly detector (TASK 3)")
    print("=" * 60)

    settings = m1_model.model_settings()
    train, holdout = _load_clean_features()

    scaler = m1_model.fit_scaler(train)
    iso = m1_model.train_model(train, settings)
    ocsvm = m1_model.train_ocsvm_baseline(train, scaler, settings)

    threshold = m1_model.calibrate_threshold(
        iso, scaler, holdout, fpr_target=settings["fpr_target"]
    )
    train_scores = m1_model.anomaly_score_01(
        iso, scaler.transform(train[FEATURE_COLUMNS].to_numpy(dtype=float))
    )
    hold_scores = m1_model.anomaly_score_01(
        iso, scaler.transform(holdout[FEATURE_COLUMNS].to_numpy(dtype=float))
    )
    print(f"[train] anomaly score on clean train: mean={train_scores.mean():.3f} p99={np.quantile(train_scores, 0.99):.3f}")
    print(f"[train] anomaly score on clean holdout: mean={hold_scores.mean():.3f} max={hold_scores.max():.3f}")
    print(f"[train] alert threshold for FPR<={settings['fpr_target']:.3f}: {threshold:.4f}")

    limits = learned_limits(train, percentile=settings["threshold_percentile"])
    # historical max speed: robust 99.9th percentile of clean reported speed
    limits["historical_max_speed_mps"] = float(train["m1_speed_mps"].quantile(settings["threshold_percentile"]))

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump(iso, m1_model.DEFAULT_MODEL_PATH)
    joblib.dump(scaler, m1_model.DEFAULT_SCALER_PATH)
    joblib.dump(ocsvm, m1_model.DEFAULT_BASELINE_PATH)
    with open(MODELS_DIR / "physical_limits.json", "w", encoding="utf-8") as fh:
        json.dump(limits, fh, indent=2)
    print(f"[train] artifacts saved to {MODELS_DIR}:")
    for p in sorted(MODELS_DIR.glob("*")):
        print(f"        - {p.name} ({p.stat().st_size / 1024:.1f} KB)")
    print("[train] done. Rerun after Member 4's real data lands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
