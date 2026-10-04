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
import pandas as pd  # noqa: E402

from member1_physical.src import data_loader, model as m1_model  # noqa: E402
from member1_physical.src.features import FEATURE_COLUMNS, extract_physical_features, learned_limits  # noqa: E402

MODELS_DIR = m1_model.DEFAULT_MODEL_PATH.parent


def _clean_sources():
    """(label, DataFrame) pairs for training — REAL data first, then M4/fallback.

    data/real/ holds genuinely captured/converter-produced sensor data
    (device GPS captures, converted GeoLife traces); data/synthetic/ holds
    Member 4's generated data; the in-memory fallback stands in when neither
    exists. Each source is split 80/20 BEFORE feature extraction so rolling
    windows never span two sources and the model is calibrated on data it
    never saw.
    """
    srcs = []
    real = data_loader._coerce("data/real")
    real_files = (sorted(real.glob("*.parquet")) + sorted(real.glob("*.csv"))) if real.exists() else []
    frames = []
    for f in real_files:
        try:
            frames.append(data_loader.load_data(f))
        except Exception as exc:
            print(f"[train] skipping {f.name}: {exc}")
    if frames:
        df = pd.concat(frames, ignore_index=True)
        names = ", ".join(f.name for f in real_files)
        srcs.append((f"REAL data: data/real ({names}, {len(df)} rows)", df))

    synth = data_loader._coerce("data/synthetic")
    files = sorted(synth.glob("*.parquet")) + sorted(synth.glob("*.csv")) if synth.exists() else []
    if files:
        clean = data_loader.load_synthetic_directory(synth)
        srcs.append((f"Member 4 data: {synth} ({len(files)} file(s), {len(clean)} rows)", clean))
    else:
        from member1_physical.src.fallback_data import make_normal
        srcs.append(("FALLBACK generator (member1_physical/src/fallback_data.py) — data/synthetic/ is empty",
                     make_normal()))
    return srcs


def _load_clean_features():
    """Features from every clean source (real data preferred), 80/20 per source."""
    trains, holdouts = [], []
    for label, clean in _clean_sources():
        clean = clean.dropna(subset=["timestamp"]).reset_index(drop=True)
        if len(clean) < 10:
            print(f"[train] source too small, skipped: {label} ({len(clean)} rows)")
            continue
        # split before/after so the model never sees the rows it will be calibrated on
        split = int(len(clean) * 0.8)
        part_train = clean.iloc[:split].reset_index(drop=True)
        part_hold = clean.iloc[split:].reset_index(drop=True)
        trains.append(extract_physical_features(part_train))
        holdouts.append(extract_physical_features(part_hold))
        print(f"[train] clean source: {label}")
        print(f"[train]   -> train rows: {len(part_train)}, clean holdout rows: {len(part_hold)}")
    train = pd.concat(trains, ignore_index=True)
    holdout = pd.concat(holdouts, ignore_index=True)
    print(f"[train] TOTAL train rows: {len(train)}, clean holdout rows: {len(holdout)}")
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
