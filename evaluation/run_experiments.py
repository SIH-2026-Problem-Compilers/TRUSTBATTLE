"""TRUSTBATTLE — reproducible experiment matrix (Steps 7+8).

Streams every M4 scenario (data/attacks/scenario_*.parquet + the M4 clean
dataset) through the REAL pipeline — M1 (`score_physical`) + M2
(`score_temporal`) via the `integration/` adapters, then M3 `compute_trust`
and both fusion modes (`trust_aware` vs `normal` baseline) — and records, per
scenario:

    scenario, corruption level, detection precision/recall/F1/FPR,
    average trust, minimum trust, recovery time (N/A when the scenario
    carries no clean tail), normal-fusion position error, trust-aware-fusion
    position error, improvement %.

Metrics that cannot be computed honestly are written as ``N/A`` — never
estimated. In particular:

* Ground-truth POSITION is unavailable inside the attack parquets (DataFrame
  attrs do not survive parquet). The runner re-attaches the seed-42 clean
  track M4 built every scenario from (``member4_cyber.src.generate_data``
  — row-aligned; attack functions only modify reported fields). This is the
  same reconstruction the M5 dashboard uses. If it is unavailable or
  row-misaligned, fusion errors are reported as N/A.
* Recovery time is N/A for scenarios whose attack runs to end-of-file
  (no clean tail) and for the clean scenario (no attack).

Outputs (all from actual runs):
    evaluation/results/trust_vs_baseline.csv     — machine-readable matrix
    evaluation/results/windows/<scenario>.csv    — per-window detail (audit trail)
    docs/reports/trust_vs_baseline.md            — baseline comparison report
    docs/reports/experiment_results.md           — full experiment report

Usage (from repo root):
    py evaluation/run_experiments.py
    py evaluation/run_experiments.py --scenarios normal,gnss_spoof --no-detail
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):  # pragma: no cover
        pass

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from integration import interfaces  # noqa: E402
from integration.pipeline import (register_available_implementations,  # noqa: E402
                                 score_window, temporal_context_rows)
from member3_trust.src import eval_scenarios  # noqa: E402
from member3_trust.src.fusion import KalmanTracker, fuse, fuse_normal, latlon_to_xy  # noqa: E402
from member3_trust.src.settings import trust_settings  # noqa: E402
from member3_trust.src.trust_engine import compute_trust  # noqa: E402

WINDOW = 50  # rows (~5 s @ 10 Hz) — same evaluation unit as M1/M2/M3
RESULTS_DIR = REPO_ROOT / "evaluation" / "results"
WINDOWS_DIR = RESULTS_DIR / "windows"
REPORTS_DIR = REPO_ROOT / "docs" / "reports"

# scenario key -> (dataset path relative to repo root, nominal corruption level)
# The nominal level is only used for labelling; ``corruption_level_pct`` in the
# CSV is the MEASURED fraction of attacked rows in the dataset.
SCENARIOS: List[Tuple[str, str]] = [
    ("normal", "data/synthetic/uav_normal_v1.parquet"),
    ("gnss_spoof", "data/attacks/scenario_gnss_spoof.parquet"),
    ("replay", "data/attacks/scenario_replay.parquet"),
    ("telemetry_manipulation", "data/attacks/scenario_telemetry_manipulation.parquet"),
    ("network_anomaly", "data/attacks/scenario_network_anomaly.parquet"),
    ("sensor_malfunction", "data/attacks/scenario_sensor_malfunction.parquet"),
    ("cross_sensor_conflict", "data/attacks/scenario_cross_sensor_conflict.parquet"),
    ("mixed_c05", "data/attacks/scenario_mixed_c05.parquet"),
    ("mixed_c10", "data/attacks/scenario_mixed_c10.parquet"),
    ("mixed_c20", "data/attacks/scenario_mixed_c20.parquet"),
    ("mixed_c30", "data/attacks/scenario_mixed_c30.parquet"),
]

CSV_COLUMNS = [
    "scenario",
    "corruption_level_pct",
    "windows",
    "attack_windows",
    "detection_precision",
    "detection_recall",
    "detection_f1",
    "false_positive_rate",
    "avg_trust",
    "min_trust",
    "avg_trust_attack",
    "recovery_time_s",
    "normal_fusion_error_m",
    "trust_aware_fusion_error_m",
    "improvement_pct",
]


def _load_truth_positions(df: pd.DataFrame) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Row-aligned truth (lat, lon) arrays for *df*, or None when unavailable.

    Prefers ``df.attrs`` (present for generator output); falls back to the
    seed-42 clean track M4 built the scenario from — the reconstruction the
    M5 dashboard already uses (``RealTrustService._build_trajectory``).
    """
    tlat, tlon = df.attrs.get("truth_latitude"), df.attrs.get("truth_longitude")
    if tlat is not None and tlon is not None and len(tlat) >= len(df):
        return np.asarray(tlat)[: len(df)], np.asarray(tlon)[: len(df)]
    try:
        from member4_cyber.src.generate_data import make_clean_dataset

        base = make_clean_dataset()
        tlat, tlon = base.attrs.get("truth_latitude"), base.attrs.get("truth_longitude")
        if tlat is None or tlon is None or len(tlat) < len(df):
            return None
        return np.asarray(tlat)[: len(df)], np.asarray(tlon)[: len(df)]
    except Exception:
        return None


def run_scenario(name: str, df: pd.DataFrame,
                 detail: bool = True) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """Stream one scenario through the full pipeline; return metrics + detail.

    Per window (50 rows): M1+M2 scores → M3 compute_trust (with observations
    → derived cross-sensor evidence) → fuse in BOTH modes with identical
    Kalman smoothing so the §20 comparison is fair.
    """
    truth = _load_truth_positions(df)
    eval_scenarios._reset_imu_state()

    history: List[Dict[str, Any]] = []
    trackers = {"trust_aware": None, "normal": None}
    rows: List[Dict[str, Any]] = []
    green = float(trust_settings()["thresholds"]["green"])

    n_windows = (len(df) - WINDOW) // WINDOW + 1
    for wi in range(n_windows):
        w0 = wi * WINDOW
        win = slice(w0, w0 + WINDOW)
        window = df.iloc[win].reset_index(drop=True)

        scores: Dict[str, float] = {}
        ev: List[Dict[str, Any]] = []
        # preceding stream rows -> M2 history (replay/stale seen-before, CR #5)
        prior = df.iloc[max(0, w0 - temporal_context_rows()):w0].reset_index(drop=True)
        out = score_window(window, prior_rows=prior)
        scores.update(out.get("scores", {}))
        ev.extend(out.get("evidence", []))

        try:
            obs = eval_scenarios.sensor_observations(df, win, rng_seed=2000 + w0,
                                                     scores=scores)
        except TypeError:
            # baseline engine (pre Step-2/4) has no scores kwarg -> no aiding
            obs = eval_scenarios.sensor_observations(df, win, rng_seed=2000 + w0)
        result = compute_trust(scores, history, observations=obs)
        history.append(result)
        if len(history) > 200:
            history = history[-200:]

        trust = result["trust"]
        flagged = result["alert"]["level"] != "GREEN"
        attack = bool((window["attack_start"] > 0).any() or (window["label"] > 0).any())
        t0 = float(window["timestamp"].iloc[0])
        dt = float(window["timestamp"].iloc[-1] - t0) or (WINDOW / 10.0)

        err_norm = err_ta = float("nan")
        if truth is not None:
            tlat_w = float(np.mean(truth[0][w0:w0 + WINDOW]))
            tlon_w = float(np.mean(truth[1][w0:w0 + WINDOW]))
            for mode, sink in (("normal", "norm"), ("trust_aware", "ta")):
                if trackers[mode] is None:
                    trackers[mode] = KalmanTracker(float(truth[0][0]),
                                                  float(truth[1][0]))
                est = (fuse(obs, trust, mode="trust_aware") if mode == "trust_aware"
                       else fuse_normal(obs))
                ex, ny = trackers[mode].step(est["lat"], est["lon"], dt)
                tx, ty = latlon_to_xy(tlat_w, tlon_w,
                                      trackers[mode].lat0, trackers[mode].lon0)
                err = float(np.hypot(ex - tx, ny - ty))
                if sink == "norm":
                    err_norm = err
                else:
                    err_ta = err

        rows.append({
            "window": wi,
            "row_start": w0,
            "attack": attack,
            "flagged": flagged,
            "level": result["alert"]["level"],
            "trust": trust["observation_trust"],
            "gnss_trust": trust["sensor_trust"].get("gnss", float("nan")),
            "imu_trust": trust["sensor_trust"].get("imu", float("nan")),
            "visual_trust": trust["sensor_trust"].get("visual", float("nan")),
            "net_trust": trust["sensor_trust"].get("net", float("nan")),
            "gnss_weight": trust["sensor_weights"].get("gnss", float("nan")),
            "physical_consistency": scores.get("physical_consistency", float("nan")),
            "anomaly_physical": scores.get("anomaly_physical", float("nan")),
            "temporal_consistency": scores.get("temporal_consistency", float("nan")),
            "anomaly_temporal": scores.get("anomaly_temporal", float("nan")),
            "network_integrity": scores.get("network_integrity", float("nan")),
            # derived INSIDE compute_trust (CR #4 returns the effective scores)
            "cross_sensor_agreement": result.get("scores", {}).get(
                "cross_sensor_agreement", float("nan")),
            "err_normal_m": err_norm,
            "err_trust_aware_m": err_ta,
        })

    detail_df = pd.DataFrame(rows)
    metrics = compute_metrics(name, detail_df, truth is not None)
    return metrics, detail_df


def compute_metrics(name: str, r: pd.DataFrame,
                    has_truth: bool) -> Dict[str, Any]:
    """Aggregate window rows into the experiment-matrix metrics (honest N/A)."""
    att = r["attack"].astype(bool)
    flg = r["flagged"].astype(bool)
    tp = int((att & flg).sum())
    fp = int((~att & flg).sum())
    fn = int((att & ~flg).sum())
    tn = int((~att & ~flg).sum())
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else float("nan")
    f1 = (2 * precision * recall / (precision + recall)) if (tp + fn) and (precision + recall) else float("nan")
    fpr = fp / (fp + tn) if fp + tn else float("nan")

    green = float(trust_settings()["thresholds"]["green"])
    recovery: Any = "N/A"
    attack_idx = r.index[att].tolist()
    if attack_idx and attack_idx[-1] < len(r) - 1:
        # scenario has a clean tail: windows from last attack window until
        # trust is back at/above GREEN (window = 5 s)
        tail = r.index[attack_idx[-1] + 1:]
        cleared = [i for i in tail if float(r.loc[i, "trust"]) >= green]
        recovery = int((cleared[0] - attack_idx[-1]) * WINDOW / 10.0) if cleared else "N/A"
    elif name == "normal":
        recovery = "N/A"

    err_norm: Any = "N/A"
    err_ta: Any = "N/A"
    improvement: Any = "N/A"
    if has_truth and bool(np.isfinite(r["err_normal_m"]).any()):
        err_norm = round(float(np.nanmean(r["err_normal_m"])), 2)
        err_ta = round(float(np.nanmean(r["err_trust_aware_m"])), 2)
        improvement = round((1 - err_ta / err_norm) * 100.0, 1) if err_norm > 0 else "N/A"

    return {
        "scenario": name,
        "windows": int(len(r)),
        "attack_windows": int(att.sum()),
        "detection_precision": round(precision, 3) if precision == precision else "N/A",
        "detection_recall": round(recall, 3) if recall == recall else "N/A",
        "detection_f1": round(f1, 3) if f1 == f1 else "N/A",
        "false_positive_rate": round(fpr, 3) if fpr == fpr else "N/A",
        "avg_trust": round(float(r["trust"].mean()), 1),
        "min_trust": round(float(r["trust"].min()), 1),
        "avg_trust_attack": round(float(r.loc[att, "trust"].mean()), 1) if att.any() else "N/A",
        "recovery_time_s": recovery,
        "normal_fusion_error_m": err_norm,
        "trust_aware_fusion_error_m": err_ta,
        "improvement_pct": improvement,
    }


def _corruption_level_pct(df: pd.DataFrame) -> float:
    """Measured % of rows carrying an attack label (never the nominal value)."""
    if "label" not in df.columns or len(df) == 0:
        return float("nan")
    return round(100.0 * float((df["label"] > 0).sum()) / len(df), 1)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="TRUSTBATTLE experiment matrix")
    ap.add_argument("--scenarios", default=None,
                    help="comma-separated subset of scenario keys")
    ap.add_argument("--no-detail", action="store_true",
                    help="skip per-window CSV dumps")
    ap.add_argument("--no-reports", action="store_true",
                    help="skip writing docs/reports/*.md")
    args = ap.parse_args(argv)

    wanted = [s.strip() for s in args.scenarios.split(",")] if args.scenarios else None
    register_available_implementations()
    missing = sorted(interfaces.MISSING)
    if missing:
        print(f"[runner] pipeline not ready, missing: {missing}")
        return 1

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_detail:
        WINDOWS_DIR.mkdir(parents=True, exist_ok=True)

    started = time.time()
    results: List[Dict[str, Any]] = []
    for key, rel in SCENARIOS:
        if wanted and key not in wanted:
            continue
        path = REPO_ROOT / rel
        if not path.exists():
            print(f"[runner] {key}: SKIP (missing {rel})")
            results.append({c: ("N/A" if c not in ("scenario", "windows",
                                                   "attack_windows") else
                                (key if c == "scenario" else 0))
                            for c in CSV_COLUMNS})
            continue
        df = pd.read_parquet(path)
        t0 = time.time()
        metrics, detail = run_scenario(key, df, detail=not args.no_detail)
        metrics["corruption_level_pct"] = _corruption_level_pct(df)
        results.append(metrics)
        if not args.no_detail:
            detail.to_csv(WINDOWS_DIR / f"{key}.csv", index=False, quoting=csv.QUOTE_MINIMAL)
        print(f"[runner] {key:24s} P={metrics['detection_precision']} "
              f"R={metrics['detection_recall']} F1={metrics['detection_f1']} "
              f"FPR={metrics['false_positive_rate']} "
              f"avg_trust={metrics['avg_trust']} min={metrics['min_trust']} "
              f"rec={metrics['recovery_time_s']}s "
              f"err n/t={metrics['normal_fusion_error_m']}/{metrics['trust_aware_fusion_error_m']} "
              f"({time.time() - t0:.0f}s)")

    ordered = [{c: r.get(c, "N/A") for c in CSV_COLUMNS} for r in results]
    out_csv = RESULTS_DIR / "trust_vs_baseline.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(ordered)
    print(f"[runner] wrote {out_csv.relative_to(REPO_ROOT)}")

    if not args.no_reports:
        from evaluation.reports import write_reports
        write_reports(ordered)
    print(f"[runner] done in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
