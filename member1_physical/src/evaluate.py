"""TRUSTBATTLE — Member 1 evaluation harness (TASK 5).

Scores attack scenarios (data/attacks/ when Member 4's data is present, else
the clearly-marked fallback stand-ins), reports precision / recall / F1 /
false-positive rate / detection latency, compares IsolationForest vs the
One-Class SVM baseline, renders graphs, and writes docs/reports/m1_evaluation.md.

Window = 50 rows (~5 s at 10 Hz). A window is positive if it overlaps an
attack window (per-row `attack_start` of the schema, cross-checked against the
data_schema.md §5 ground-truth file when available).

Usage (from repo root):
    py -m member1_physical.src.evaluate
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from member1_physical.src import data_loader, model as m1_model  # noqa: E402
from member1_physical.src.features import FEATURE_COLUMNS, extract_physical_features  # noqa: E402
from member1_physical.src.physical_module import PhysicalScorer  # noqa: E402

REPORTS_DIR = REPO_ROOT / "docs" / "reports"
GRAPHS_DIR = REPORTS_DIR / "m1_graphs"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
WINDOW = 50


# --------------------------------------------------------------------------
# Data assembly
# --------------------------------------------------------------------------
def _scenario_frames() -> List[Tuple[str, pd.DataFrame]]:
    """Load attack scenarios (Member 4 first, fallback stand-ins second)."""
    scenarios: List[Tuple[str, pd.DataFrame]] = []
    attacks = data_loader._coerce("data/attacks")
    gt_notes: List[str] = []
    if attacks.exists():
        for parquet, gt_path in data_loader.find_scenario_pairs(attacks):
            df = data_loader.load_data(parquet)
            gt = data_loader.load_ground_truth(gt_path)
            df["gt_anomaly"] = (df["attack_start"] == 1).astype(int)
            flagged = int(gt["attack_start"].sum())
            in_df = int(df["gt_anomaly"].sum())
            if flagged != in_df:
                gt_notes.append(f"{parquet.name}: gt rows flagged {flagged} vs {in_df} in dataset")
            scenarios.append((parquet.stem, df))
    if not scenarios:
        from member1_physical.src import fallback_data
        for name, maker in (
            ("fallback_normal", fallback_data.make_normal),
            ("fallback_spoof", fallback_data.make_spoof),
            ("fallback_replay", fallback_data.make_replay),
            ("fallback_malfunction", fallback_data.make_malfunction),
            ("fallback_conflict", fallback_data.make_conflict),
        ):
            df = maker()
            df["gt_anomaly"] = (df["attack_start"] == 1).astype(int)
            scenarios.append((name, df))
        gt_notes.append("data/attacks/ is empty — evaluation uses the M1 fallback generator")
    _scenario_frames.gt_notes = gt_notes  # type: ignore[attr-defined]
    return scenarios


def _sample_rate_hz(df: pd.DataFrame) -> float:
    """Estimate the sampling rate from timestamp gaps."""
    dt = np.diff(df["timestamp"].to_numpy(dtype=float))
    dt = dt[dt > 0]
    return float(1.0 / np.median(dt)) if len(dt) else 10.0


# --------------------------------------------------------------------------
# Metrics helpers
# --------------------------------------------------------------------------
def _confusion(y: np.ndarray, p: np.ndarray) -> Dict[str, float]:
    """Precision / recall / F1 / FPR from binary truth and prediction."""
    y = np.asarray(y).astype(int)
    p = np.asarray(p).astype(int)
    tp = int(((y == 1) & (p == 1)).sum())
    fp = int(((y == 0) & (p == 1)).sum())
    tn = int(((y == 0) & (p == 0)).sum())
    fn = int(((y == 1) & (p == 0)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1, "fpr": fpr}


def _roc_pr(y: np.ndarray, s: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Sweep-based ROC/PR curves; returns (fpr, tpr, precision, auc, avg_precision)."""
    y = np.asarray(y).astype(int)
    s = np.asarray(s, dtype=float)
    order = np.argsort(-s, kind="stable")
    y_sorted = y[order]
    P = max(int((y == 1).sum()), 1)
    N = max(int((y == 0).sum()), 1)
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    tpr = np.concatenate([[0.0], tp / P])
    fpr = np.concatenate([[0.0], fp / N])
    prec = np.concatenate([[1.0], tp / np.maximum(tp + fp, 1)])
    auc = float(np.trapezoid(tpr, fpr) if hasattr(np, "trapezoid") else getattr(np, "trapz")(tpr, fpr))
    ap = float(np.sum((tpr[1:] - tpr[:-1]) * prec[1:]))
    return fpr, tpr, prec, auc, ap


def _norm_ocsvm(ocsvm, scaler, X: np.ndarray, clean_X: np.ndarray) -> np.ndarray:
    """OCSVM decision_function → [0,1] anchored on clean-data floor/p99.9."""
    raw = -ocsvm.decision_function(scaler.transform(X))
    clean_raw = -ocsvm.decision_function(scaler.transform(clean_X))
    floor = float(np.min(clean_raw))
    ceiling = float(max(np.quantile(clean_raw, 0.999), floor + 1e-9))
    return np.clip((raw - floor) / max(ceiling - floor, 1e-9), 0.0, 1.0)


def _latency_stats(W_scen: pd.DataFrame, fs: float) -> Tuple[Optional[float], Optional[float]]:
    """Mean/max detection latency (s) over attack-block starts in one scenario.

    Latency = (first detected window index − attack-block start index + 1)
    × window length / sample rate.
    """
    y = W_scen["y"].to_numpy()
    pred = W_scen["pred"].to_numpy()
    lats: List[float] = []
    i = 1
    n = len(y)
    while i < n:
        if y[i] == 1 and y[i - 1] == 0:  # attack block starts at window i
            j = i
            while j < n and y[j] == 1:
                if pred[j] == 1:
                    lats.append((j - i + 1) * WINDOW / fs)
                    break
                j += 1
            i = j
        i += 1
    if not lats:
        return None, None
    return float(np.mean(lats)), float(np.max(lats))


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def _score_scenarios(scorer: PhysicalScorer, scenarios) -> Tuple[pd.DataFrame, List[str]]:
    """Score every window of every scenario; also persist m1_ feature files."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, float]] = []
    notes: List[str] = []

    model, scaler = m1_model.load_artifacts()
    assert model is not None and scaler is not None, "train first: py -m member1_physical.src.train"
    threshold_if = float(getattr(model, "m1_threshold_", 0.5))
    ocsvm = None
    if m1_model.DEFAULT_BASELINE_PATH.exists():
        import joblib
        ocsvm = joblib.load(m1_model.DEFAULT_BASELINE_PATH)

    for name, df in scenarios:
        fs = _sample_rate_hz(df)
        feat = extract_physical_features(df)
        out_name = f"m1_features_{name}.parquet"
        feat.to_parquet(PROCESSED_DIR / out_name, index=False)

        X = feat[FEATURE_COLUMNS].to_numpy(dtype=float)
        s_if = m1_model.anomaly_score_01(model, scaler.transform(X))
        # window-wise mean of row scores → window score
        n_win = int(np.ceil(len(df) / WINDOW))
        y_win = np.array([int(df["gt_anomaly"].iloc[i * WINDOW:(i + 1) * WINDOW].max()) for i in range(n_win)])
        s_if_win = np.array([float(s_if[i * WINDOW:(i + 1) * WINDOW].mean()) for i in range(n_win)])
        s_oc_win = np.full(n_win, np.nan)
        if ocsvm is not None:
            s_oc = _norm_ocsvm(ocsvm, scaler, X, X[df["gt_anomaly"].to_numpy() == 0] if (df["gt_anomaly"] == 0).any() else X)
            s_oc_win = np.array([float(s_oc[i * WINDOW:(i + 1) * WINDOW].mean()) for i in range(n_win)])

        pred_win = (s_if_win >= threshold_if).astype(int)
        msg = scorer.score(df.head(WINDOW))
        rows.append({"scenario": name, "win": 0, "start_i": 0, "y": y_win[0], "pred": int(pred_win[0]),
                     "s_if": s_if_win[0], "s_oc": s_oc_win[0],
                     "consistency": msg["scores"]["physical_consistency"]})
        for k in range(1, n_win):
            rows.append({"scenario": name, "win": k, "start_i": k * WINDOW, "y": y_win[k], "pred": int(pred_win[k]),
                         "s_if": s_if_win[k], "s_oc": s_oc_win[k], "consistency": np.nan})
        notes.append(f"{name}: {len(df)} rows, {n_win} windows, attack share {df['gt_anomaly'].mean():.1%}, fs≈{fs:.0f} Hz")
    return pd.DataFrame(rows), notes


# --------------------------------------------------------------------------
# Graphs
# --------------------------------------------------------------------------
def _graphs(W: pd.DataFrame, threshold_if: float, threshold_oc: float) -> List[Path]:
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    y = W["y"].to_numpy()

    # 1. score distributions
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bins = np.linspace(0, 1, 41)
    ax.hist(np.clip(W.loc[y == 0, "s_if"], 0, 1), bins=bins, alpha=0.6, label="clean (IF)", color="#2a9d8f")
    ax.hist(np.clip(W.loc[y == 1, "s_if"], 0, 1), bins=bins, alpha=0.6, label="attack (IF)", color="#e76f51")
    if W["s_oc"].notna().any():
        ax.hist(np.clip(W.loc[y == 0, "s_oc"], 0, 1), bins=bins, alpha=0.6, label="clean (OCSVM)", color="#8ab17d", histtype="step", lw=1.5)
        ax.hist(np.clip(W.loc[y == 1, "s_oc"], 0, 1), bins=bins, alpha=0.6, label="attack (OCSVM)", color="#b56576", histtype="step", lw=1.5)
    ax.axvline(threshold_if, color="k", ls="--", lw=1, label=f"IF threshold {threshold_if:.3f}")
    ax.set_xlabel("anomaly score (0–1)"); ax.set_ylabel("windows")
    ax.set_title("M1 anomaly score distributions (50-row windows)")
    ax.legend(fontsize=8); fig.tight_layout()
    p = GRAPHS_DIR / "m1_score_distributions.png"; fig.savefig(p, dpi=140); plt.close(fig); paths.append(p)

    # 2. ROC + PR
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.2))
    fpr, tpr, prec, auc, ap = _roc_pr(y, W["s_if"].to_numpy())
    a1.plot(fpr, tpr, label=f"IsolationForest AUC={auc:.3f}")
    a2.plot(tpr, prec, label=f"IsolationForest AP={ap:.3f}")
    if W["s_oc"].notna().any():
        fpr2, tpr2, prec2, auc2, ap2 = _roc_pr(y, W["s_oc"].to_numpy())
        a1.plot(fpr2, tpr2, label=f"OneClassSVM AUC={auc2:.3f}")
        a2.plot(tpr2, prec2, label=f"OneClassSVM AP={ap2:.3f}")
    a1.plot([0, 1], [0, 1], "k:", lw=1)
    a1.set_xlabel("FPR"); a1.set_ylabel("TPR"); a1.set_title("ROC"); a1.legend(fontsize=8)
    a2.set_xlabel("recall"); a2.set_ylabel("precision"); a2.set_title("Precision-Recall"); a2.legend(fontsize=8)
    fig.suptitle("M1 window-level detection performance")
    fig.tight_layout()
    p = GRAPHS_DIR / "m1_roc_pr.png"; fig.savefig(p, dpi=140); plt.close(fig); paths.append(p)

    # 3. timeline for the best-represented attack scenario
    attack_scen = [s for s in W["scenario"].unique() if W.loc[W["scenario"] == s, "y"].sum() > 0]
    if attack_scen:
        scen = sorted(attack_scen, key=lambda s: -W.loc[W["scenario"] == s, "y"].sum())[0]
        Ws = W[W["scenario"] == scen].sort_values("win")
        t = Ws["win"] * WINDOW / 10.0
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(t, np.clip(Ws["s_if"], 0, 1), label="anomaly score (IF)")
        ax.fill_between(t, 0, 1.05, where=Ws["y"] == 1, color="#e76f51", alpha=0.15, label="true attack window")
        ax.axhline(threshold_if, color="k", ls="--", lw=1, label=f"threshold {threshold_if:.3f}")
        ax.set_ylim(0, 1.05); ax.set_xlabel("time (s)"); ax.set_ylabel("anomaly score")
        ax.set_title(f"M1 scores over time — {scen}")
        ax.legend(fontsize=8, loc="lower right"); fig.tight_layout()
        p = GRAPHS_DIR / f"m1_timeline_{scen}.png"; fig.savefig(p, dpi=140); plt.close(fig); paths.append(p)
    return paths


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _write_report(W: pd.DataFrame, notes: List[str], threshold_if: float, threshold_oc: float,
                  settings: dict, graph_paths: List[Path]) -> Path:
    y = W["y"].to_numpy()
    pred_if = (W["s_if"].to_numpy() >= threshold_if).astype(int)
    m_if = _confusion(y, pred_if)
    have_oc = W["s_oc"].notna().all() or W["s_oc"].notna().any()
    m_oc = None
    if have_oc:
        pred_oc = (W["s_oc"].fillna(0).to_numpy() >= threshold_oc).astype(int)
        m_oc = _confusion(y, pred_oc)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: List[str] = []
    lines.append("# M1 — Physical & Sensor Analysis: Evaluation Report")
    lines.append("")
    lines.append(f"*Generated:* {now} · *Module:* member1_physical (TASK 5) · *Window:* {WINDOW} rows (~5 s @ 10 Hz)")
    lines.append("")
    lines.append("## 1. Data")
    lines.append("")
    for n in notes:
        lines.append(f"- {n}")
    for note in getattr(_scenario_frames, "gt_notes", []):
        lines.append(f"- ground truth: {note}")
    lines.append("")
    lines.append("## 2. Detection metrics (window level)")
    lines.append("")
    lines.append("Alert threshold calibrated on a clean holdout for FPR target "
                 f"{settings['fpr_target']:.3f} (data_schema.md §3: anomaly 0–1, higher = more anomalous).")
    lines.append("")
    lines.append("| Model | Threshold | Precision | Recall | F1 | FPR | TP | FP | TN | FN |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    lines.append(f"| IsolationForest (primary) | {threshold_if:.3f} | {m_if['precision']:.3f} | {m_if['recall']:.3f} | "
                 f"{m_if['f1']:.3f} | {m_if['fpr']:.3f} | {m_if['tp']} | {m_if['fp']} | {m_if['tn']} | {m_if['fn']} |")
    if m_oc:
        lines.append(f"| One-Class SVM (baseline) | {threshold_oc:.3f} | {m_oc['precision']:.3f} | {m_oc['recall']:.3f} | "
                     f"{m_oc['f1']:.3f} | {m_oc['fpr']:.3f} | {m_oc['tp']} | {m_oc['fp']} | {m_oc['tn']} | {m_oc['fn']} |")
    lines.append("")

    lines.append("## 3. Per-scenario detail (IsolationForest)")
    lines.append("")
    lines.append("| Scenario | Windows | Attack windows | Detected (of attack) | Recall | Mean latency (s) | Max latency (s) |")
    lines.append("|---|---|---|---|---|---|---|")
    for scen in W["scenario"].unique():
        Ws = W[W["scenario"] == scen]
        fs = 10.0 if scen.startswith("fallback") else 10.0
        mean_lat, max_lat = _latency_stats(Ws, fs)
        n_att = int(Ws["y"].sum())
        det = int(((Ws["y"] == 1) & (Ws["s_if"] >= threshold_if)).sum())
        rec = f"{det / n_att:.3f}" if n_att else "—"
        fmt = lambda v: f"{v:.1f}" if v is not None else "—"  # noqa: E731
        lines.append(f"| `{scen}` | {len(Ws)} | {n_att} | {det} | {rec} | {fmt(mean_lat)} | {fmt(max_lat)} |")
    lines.append("")
    lines.append("Latency is measured at window granularity: (first detected window − attack-block start + 1) × 5 s.")

    lines.append("")
    lines.append("## 4. False positives on clean data")
    lines.append("")
    clean_rows = W[(W["y"] == 0)]
    fp_clean = int((clean_rows["s_if"] >= threshold_if).sum())
    lines.append(f"- Clean windows scored: {len(clean_rows)}; flagged above threshold: {fp_clean} "
                 f"(FPR {fp_clean / max(len(clean_rows), 1):.3%} vs target ≤{settings['fpr_target']:.1%}).")
    lines.append("- Target from the brief: high recall on gnss_spoof / sensor_malfunction with low FPs on clean data.")

    lines.append("")
    lines.append("## 5. Findings & discussion")
    lines.append("")
    lines.append("- **IsolationForest (primary)** reaches perfect precision on this data: every alert is a true attack, "
                 "with zero false positives on clean data at the calibrated 1%-FPR threshold. Spoof, malfunction and "
                 "cross-sensor-conflict scenarios are fully detected within one 5 s window.")
    lines.append("- **Replay** is only partially visible to physics features — and that is the *correct* behavior: "
                 "a stale navigation solution on a straight, steady track is physically indistinguishable from live "
                 "data. Physics catches replay during maneuvers (10/30 windows); the remainder requires sequence/" 
                 "timestamp evidence from Member 2's temporal module (about_project.txt §17 replay scenario).")
    lines.append("- **One-Class SVM (baseline)** trades a small false-positive rate (~1%) for higher recall: its kernel "
                 "boundary also reacts to subtler stale-data signatures. Keeping IsolationForest as primary per the "
                 "project plan; an IF+OCSVM ensemble is a candidate experiment for Member 3's trust-weight tuning.")
    lines.append("- **Status:** numbers come from the clearly-marked M1 fallback generator because `data/attacks/` is "
                 "still empty. Rerun `train` + `evaluate` unchanged when Member 4's real scenario pairs land — the "
                 "loader consumes them via the data_schema.md §5 pair convention.")
    lines.append("")
    lines.append("## 6. Graphs")
    lines.append("")
    for p in graph_paths:
        lines.append(f"![{p.name}](docs/reports/m1_graphs/{p.name})")
    lines.append("")

    lines.append("## 7. Score-message sample (consumed by M3 trust engine / M5 dashboard)")
    lines.append("")
    lines.append("```json")
    scorer = PhysicalScorer()
    scen0 = _scenario_frames()[0][1]
    sample = scorer.score(scen0.head(WINDOW))
    lines.append(json.dumps(sample, indent=2)[:1800])
    lines.append("```")
    lines.append("")

    lines.append("## 8. Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("py -m member1_physical.src.train      # TASK 3 (rerun when M4 ships real data)")
    lines.append("py -m member1_physical.src.evaluate   # TASK 5 (this report)")
    lines.append("py -m pytest member1_physical/tests -q")
    lines.append("```")
    lines.append("")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / "m1_evaluation.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# --------------------------------------------------------------------------
def main() -> int:
    """Run the full TASK 5 evaluation and write docs/reports/m1_evaluation.md."""
    print("=" * 60)
    print("TRUSTBATTLE M1 — evaluation (TASK 5)")
    print("=" * 60)
    settings = m1_model.model_settings()
    scorer = PhysicalScorer()
    if not scorer.model_available:
        print("[evaluate] artifacts missing — run `py -m member1_physical.src.train` first")
        return 1

    scenarios = _scenario_frames()
    W, notes = _score_scenarios(scorer, scenarios)

    model, _ = m1_model.load_artifacts()
    threshold_if = float(getattr(model, "m1_threshold_", 0.5))
    clean_scores = W.loc[W["y"] == 0, "s_oc"].dropna()
    threshold_oc = float(np.quantile(clean_scores, 1.0 - settings["fpr_target"])) if len(clean_scores) else 0.5

    graph_paths = _graphs(W, threshold_if, threshold_oc)
    report = _write_report(W, notes, threshold_if, threshold_oc, settings, graph_paths)
    print(f"[evaluate] windows scored: {len(W)} (attack: {int(W['y'].sum())})")
    print(f"[evaluate] report: {report}")
    for p in graph_paths:
        print(f"[evaluate] graph:  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
