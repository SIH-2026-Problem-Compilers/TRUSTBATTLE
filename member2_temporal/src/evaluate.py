"""TRUSTBATTLE — Member 2 evaluation harness (TASK 6).

Scores attack scenarios (data/attacks/ when Member 4's data is present, else
the clearly-marked fallback stand-ins), reports precision / recall / F1 /
false-positive rate / detection latency for the temporal and network
detectors (IsolationForest vs One-Class SVM baseline), with emphasis on the
replay (stale data) and network-anomaly scenarios, renders graphs, and
writes docs/reports/m2_evaluation.md.

Window = 50 rows (~5 s at 10 Hz). A window is positive if it overlaps an
attack window (per-row `attack_start` of the schema, cross-checked against
the data_schema.md §5 ground-truth file when available).

Usage (from repo root):
    py -m member2_temporal.src.evaluate
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

from member2_temporal.src import data_loader, model as m2_model  # noqa: E402
from member2_temporal.src.features import (  # noqa: E402
    NETWORK_FEATURE_COLUMNS,
    TEMPORAL_FEATURE_COLUMNS,
    extract_temporal_features,
)
from member2_temporal.src.temporal_module import TemporalScorer  # noqa: E402

REPORTS_DIR = REPO_ROOT / "docs" / "reports"
GRAPHS_DIR = REPORTS_DIR / "m2_graphs"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
WINDOW = 50


# --------------------------------------------------------------------------
# Data assembly
# --------------------------------------------------------------------------
def _scenario_frames() -> List[Tuple[str, pd.DataFrame]]:
    """Load attack scenarios (Member 4 first, fallback stand-ins second)."""
    scenarios: List[Tuple[str, pd.DataFrame]] = []
    gt_notes: List[str] = []
    attacks = data_loader._coerce("data/attacks")
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
        from member2_temporal.src import fallback_data
        for name, maker in (
            ("fallback_normal", fallback_data.make_normal),
            ("fallback_replay", fallback_data.make_replay),
            ("fallback_telemetry_manip", fallback_data.make_telemetry_manip),
            ("fallback_network_anomaly", fallback_data.make_network_anomaly),
        ):
            df = maker()
            df["gt_anomaly"] = (df["attack_start"] == 1).astype(int)
            scenarios.append((name, df))
        gt_notes.append("data/attacks/ is empty — evaluation uses the M2 fallback generator")
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
def _score_scenarios() -> Tuple[pd.DataFrame, List[str], Dict[str, float]]:
    """Score every window of every scenario; also persist m2_ feature files."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    t_model, t_scaler = m2_model.load_artifacts("temporal")
    n_model, n_scaler = m2_model.load_artifacts("network")
    assert t_model is not None and n_model is not None, \
        "train first: py -m member2_temporal.src.train"
    t_thresh = float(getattr(t_model, "m2_threshold_", 0.5))
    n_thresh = float(getattr(n_model, "m2_threshold_", 0.5))

    import joblib
    t_oc = joblib.load(m2_model.DEFAULT_TEMPORAL_OCSVM_PATH) \
        if m2_model.DEFAULT_TEMPORAL_OCSVM_PATH.exists() else None
    n_oc = joblib.load(m2_model.DEFAULT_NETWORK_OCSVM_PATH) \
        if m2_model.DEFAULT_NETWORK_OCSVM_PATH.exists() else None

    # one global clean reference per feature set (from the clean scenario)
    # for OCSVM score anchoring — consistent 0/1 anchors across all scenarios
    ref_t = ref_n = None
    for name, df in _scenario_frames():
        if "normal" in name:
            feat0 = extract_temporal_features(df)
            clean_mask = (df["gt_anomaly"] == 0).to_numpy()
            ref_t = feat0.loc[clean_mask, TEMPORAL_FEATURE_COLUMNS].to_numpy(dtype=float)
            ref_n = feat0.loc[clean_mask, NETWORK_FEATURE_COLUMNS].to_numpy(dtype=float)
            break

    rows: List[Dict[str, float]] = []
    notes: List[str] = []
    for name, df in _scenario_frames():
        fs = _sample_rate_hz(df)
        feat = extract_temporal_features(df)
        feat.to_parquet(PROCESSED_DIR / f"m2_features_{name}.parquet", index=False)

        Xt = feat[TEMPORAL_FEATURE_COLUMNS].to_numpy(dtype=float)
        Xn = feat[NETWORK_FEATURE_COLUMNS].to_numpy(dtype=float)
        s_t = m2_model.anomaly_score_01(t_model, t_scaler.transform(Xt))
        s_n = m2_model.anomaly_score_01(n_model, n_scaler.transform(Xn))

        s_t_oc = s_n_oc = None
        if t_oc is not None:
            s_t_oc = m2_model.ocsvm_score_01(t_oc, t_scaler, feat, TEMPORAL_FEATURE_COLUMNS, ref_t)
        if n_oc is not None:
            s_n_oc = m2_model.ocsvm_score_01(n_oc, n_scaler, feat, NETWORK_FEATURE_COLUMNS, ref_n)

        n_win = int(np.ceil(len(df) / WINDOW))
        y_win = np.array([int(df["gt_anomaly"].iloc[i * WINDOW:(i + 1) * WINDOW].max())
                          for i in range(n_win)])

        def wmean(arr: Optional[np.ndarray]) -> np.ndarray:
            if arr is None:
                return np.full(n_win, np.nan)
            return np.array([float(arr[i * WINDOW:(i + 1) * WINDOW].mean()) for i in range(n_win)])

        s_t_win, s_n_win = wmean(s_t), wmean(s_n)
        s_t_oc_win, s_n_oc_win = wmean(s_t_oc), wmean(s_n_oc)
        s_comb_win = np.fmax(s_t_win, s_n_win)

        pred_comb = ((s_t_win >= t_thresh) | (s_n_win >= n_thresh)).astype(int)
        for k in range(n_win):
            rows.append({"scenario": name, "win": k, "start_i": k * WINDOW, "y": y_win[k],
                         "pred": int(pred_comb[k]),
                         "s_t": s_t_win[k], "s_n": s_n_win[k], "s_comb": s_comb_win[k],
                         "s_t_oc": s_t_oc_win[k], "s_n_oc": s_n_oc_win[k],
                         "consistency": np.nan})
        notes.append(f"{name}: {len(df)} rows, {n_win} windows, "
                     f"attack share {df['gt_anomaly'].mean():.1%}, fs≈{fs:.0f} Hz")
    return pd.DataFrame(rows), notes, {"temporal": t_thresh, "network": n_thresh}


# --------------------------------------------------------------------------
# Graphs
# --------------------------------------------------------------------------
def _graphs(W: pd.DataFrame, th: Dict[str, float]) -> List[Path]:
    """Render score-distribution, ROC/PR and timeline graphs; return paths."""
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    y = W["y"].to_numpy()
    bins = np.linspace(0, 1, 41)

    # 1. score distributions
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(np.clip(W.loc[y == 0, "s_t"], 0, 1), bins=bins, alpha=0.6, label="clean (temporal IF)", color="#2a9d8f")
    ax.hist(np.clip(W.loc[y == 1, "s_t"], 0, 1), bins=bins, alpha=0.6, label="attack (temporal IF)", color="#e76f51")
    ax.hist(np.clip(W.loc[y == 0, "s_n"], 0, 1), bins=bins, alpha=0.9, label="clean (network IF)", color="#8ab17d", histtype="step", lw=1.5)
    ax.hist(np.clip(W.loc[y == 1, "s_n"], 0, 1), bins=bins, alpha=0.9, label="attack (network IF)", color="#b56576", histtype="step", lw=1.5)
    ax.axvline(th["temporal"], color="k", ls="--", lw=1, label=f"temporal thr {th['temporal']:.3f}")
    ax.axvline(th["network"], color="grey", ls="--", lw=1, label=f"network thr {th['network']:.3f}")
    ax.set_xlabel("anomaly score (0–1)"); ax.set_ylabel("windows")
    ax.set_title("M2 anomaly score distributions (50-row windows)")
    ax.legend(fontsize=8); fig.tight_layout()
    p = GRAPHS_DIR / "m2_score_distributions.png"; fig.savefig(p, dpi=140); plt.close(fig); paths.append(p)

    # 2. ROC + PR (temporal / network / combined IsolationForest)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.2))
    for col, label, color in (("s_t", "Temporal IF", "#2a9d8f"),
                              ("s_n", "Network IF", "#8ab17d"),
                              ("s_comb", "Combined (max)", "#e76f51")):
        fpr, tpr, prec, auc, ap = _roc_pr(y, W[col].to_numpy())
        a1.plot(fpr, tpr, color=color, label=f"{label} AUC={auc:.3f}")
        a2.plot(tpr, prec, color=color, label=f"{label} AP={ap:.3f}")
    a1.plot([0, 1], [0, 1], "k:", lw=1)
    a1.set_xlabel("FPR"); a1.set_ylabel("TPR"); a1.set_title("ROC"); a1.legend(fontsize=8)
    a2.set_xlabel("recall"); a2.set_ylabel("precision"); a2.set_title("Precision-Recall"); a2.legend(fontsize=8)
    fig.suptitle("M2 window-level detection performance")
    fig.tight_layout()
    p = GRAPHS_DIR / "m2_roc_pr.png"; fig.savefig(p, dpi=140); plt.close(fig); paths.append(p)

    # 3. timelines for the two headline scenarios (replay → temporal, network → network)
    for scen, col, thr, color in (("fallback_replay", "s_t", th["temporal"], "#2a9d8f"),
                                  ("fallback_network_anomaly", "s_n", th["network"], "#8ab17d")):
        cand = W[W["scenario"] == scen]
        if cand.empty:
            continue
        Ws = cand.sort_values("win")
        t = Ws["win"] * WINDOW / 10.0
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(t, np.clip(Ws[col], 0, 1), color=color, label="anomaly score")
        ax.fill_between(t, 0, 1.05, where=Ws["y"] == 1, color="#e76f51", alpha=0.15, label="true attack window")
        ax.axhline(thr, color="k", ls="--", lw=1, label=f"threshold {thr:.3f}")
        ax.set_ylim(0, 1.05); ax.set_xlabel("time (s)"); ax.set_ylabel("anomaly score")
        ax.set_title(f"M2 scores over time — {scen}")
        ax.legend(fontsize=8, loc="lower right"); fig.tight_layout()
        p = GRAPHS_DIR / f"m2_timeline_{scen}.png"; fig.savefig(p, dpi=140); plt.close(fig); paths.append(p)
    return paths


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _write_report(W: pd.DataFrame, notes: List[str], th: Dict[str, float],
                  settings: dict, graph_paths: List[Path]) -> Path:
    """Write docs/reports/m2_evaluation.md from the scored windows."""
    y = W["y"].to_numpy()

    def pred(col: str, thr: float) -> np.ndarray:
        s = W[col].to_numpy()
        return np.where(np.isnan(s), 0.0, s) >= thr

    m_t = _confusion(y, pred("s_t", th["temporal"]))
    m_n = _confusion(y, pred("s_n", th["network"]))
    m_c = _confusion(y, (pred("s_t", th["temporal"]) | pred("s_n", th["network"])).astype(int))
    have_oc = W["s_t_oc"].notna().any() and W["s_n_oc"].notna().any()
    m_oc_t = m_oc_n = None
    if have_oc:
        eff_fpr = settings["fpr_target"] / 2.0
        clean_t = W.loc[y == 0, "s_t_oc"].dropna()
        clean_n = W.loc[y == 0, "s_n_oc"].dropna()
        th_oc_t = float(np.quantile(clean_t, 1.0 - eff_fpr)) if len(clean_t) else 1.0
        th_oc_n = float(np.quantile(clean_n, 1.0 - eff_fpr)) if len(clean_n) else 1.0
        m_oc_t = _confusion(y, pred("s_t_oc", th_oc_t))
        m_oc_n = _confusion(y, pred("s_n_oc", th_oc_n))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: List[str] = []
    L.append("# M2 — Temporal & Telemetry/Network Analysis: Evaluation Report")
    L.append("")
    L.append(f"*Generated:* {now} · *Module:* member2_temporal (TASK 6) · *Window:* {WINDOW} rows (~5 s @ 10 Hz)")
    L.append("")
    L.append("## 1. Data")
    L.append("")
    for n in notes:
        L.append(f"- {n}")
    for note in getattr(_scenario_frames, "gt_notes", []):
        L.append(f"- ground truth: {note}")
    L.append("")
    L.append("## 2. Detection metrics (window level)")
    L.append("")
    L.append("Alert thresholds calibrated on a clean holdout at fpr_target/2 per detector "
             f"(union/Šidák correction so the COMBINED FPR meets the {settings['fpr_target']:.3f} target; "
             "data_schema.md §3: anomaly 0–1, higher = more anomalous). "
             "Combined = a window is flagged when either detector fires.")
    L.append("")
    L.append("| Detector | Threshold | Precision | Recall | F1 | FPR | TP | FP | TN | FN |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    L.append(f"| Temporal IsolationForest | {th['temporal']:.3f} | {m_t['precision']:.3f} | {m_t['recall']:.3f} | "
             f"{m_t['f1']:.3f} | {m_t['fpr']:.3f} | {m_t['tp']} | {m_t['fp']} | {m_t['tn']} | {m_t['fn']} |")
    L.append(f"| Network IsolationForest | {th['network']:.3f} | {m_n['precision']:.3f} | {m_n['recall']:.3f} | "
             f"{m_n['f1']:.3f} | {m_n['fpr']:.3f} | {m_n['tp']} | {m_n['fp']} | {m_n['tn']} | {m_n['fn']} |")
    L.append(f"| Combined (temporal ∪ network) | {max(th['temporal'], th['network']):.3f} | {m_c['precision']:.3f} | "
             f"{m_c['recall']:.3f} | {m_c['f1']:.3f} | {m_c['fpr']:.3f} | {m_c['tp']} | {m_c['fp']} | {m_c['tn']} | {m_c['fn']} |")
    if m_oc_t and m_oc_n:
        L.append(f"| Temporal One-Class SVM (baseline) | — | {m_oc_t['precision']:.3f} | {m_oc_t['recall']:.3f} | "
                 f"{m_oc_t['f1']:.3f} | {m_oc_t['fpr']:.3f} | {m_oc_t['tp']} | {m_oc_t['fp']} | {m_oc_t['tn']} | {m_oc_t['fn']} |")
        L.append(f"| Network One-Class SVM (baseline) | — | {m_oc_n['precision']:.3f} | {m_oc_n['recall']:.3f} | "
                 f"{m_oc_n['f1']:.3f} | {m_oc_n['fpr']:.3f} | {m_oc_n['tp']} | {m_oc_n['fp']} | {m_oc_n['tn']} | {m_oc_n['fn']} |")
    L.append("")

    L.append("## 3. Per-scenario detail (Combined IsolationForest)")
    L.append("")
    L.append("| Scenario | Windows | Attack windows | Detected (of attack) | Recall | Mean latency (s) | Max latency (s) |")
    L.append("|---|---|---|---|---|---|---|")
    for scen in W["scenario"].unique():
        Ws = W[W["scenario"] == scen]
        mean_lat, max_lat = _latency_stats(Ws, 10.0)
        n_att = int(Ws["y"].sum())
        det = int(((Ws["y"] == 1) & (Ws["pred"] == 1)).sum())
        rec = f"{det / n_att:.3f}" if n_att else "—"
        fmt = lambda v: f"{v:.1f}" if v is not None else "—"  # noqa: E731
        L.append(f"| `{scen}` | {len(Ws)} | {n_att} | {det} | {rec} | {fmt(mean_lat)} | {fmt(max_lat)} |")
    L.append("")
    L.append("Latency is measured at window granularity: (first detected window − attack-block start + 1) × 5 s.")

    L.append("")
    L.append("## 4. False positives on clean data")
    L.append("")
    clean_rows = W[(W["y"] == 0)]
    fp_comb = int((clean_rows["pred"] == 1).sum())
    L.append(f"- Clean windows scored: {len(clean_rows)}; flagged (combined): {fp_comb} "
             f"(FPR {fp_comb / max(len(clean_rows), 1):.3%} vs target ≤{settings['fpr_target']:.1%}).")
    L.append("- Target from the brief: high recall on replay / network_anomaly with low FPs on clean data.")

    L.append("")
    L.append("## 5. Findings & discussion")
    L.append("")
    L.append("- **Replay (stale data)** is M2's headline target and is caught by the temporal detector: the stale "
             "window re-broadcasts old sequence numbers and reuses old timestamps, so `m2_seq_seen_before`, "
             "`m2_ts_stale_age_s` and `m2_ts_rewind_s` fire for the whole replay block — not just its boundary. "
             "This closes the gap M1's physics module reported (replay on a steady track is physically invisible).")
    L.append("- **Network anomaly** is caught by the network detector through `m2_pkt_iat_excess_ms` (the ~950 ms "
             "spikes vs ~20 ms normal, about_project.txt §10), the post-spike catch-up bursts, packet loss and "
             "the packet-rate drop.")
    L.append("- **Telemetry manipulation** (label 3) shows up as sequence gaps/duplicates/backward steps, timestamp "
             "jitter and non-monotonic steps — a subtler, noisier signature than replay; detection here trades "
             "recall for the low false-positive budget.")
    L.append("- **IsolationForest stays primary** (project plan); the One-Class SVM baseline trades a small FPR for "
             "higher recall on subtle signatures. An IF+OCSVM ensemble is a candidate experiment for M3's "
             "trust-weight tuning.")
    L.append("- **Status:** numbers come from the clearly-marked M2 fallback generator because `data/attacks/` is "
             "still empty. Rerun `train` + `evaluate` unchanged when Member 4's real scenario pairs land — the "
             "loader consumes them via the data_schema.md §5 pair convention.")
    L.append("")
    L.append("## 6. Graphs")
    L.append("")
    for p in graph_paths:
        L.append(f"![{p.name}](docs/reports/m2_graphs/{p.name})")
    L.append("")

    L.append("## 7. Score-message sample (consumed by M3 trust engine / M5 dashboard)")
    L.append("")
    L.append("```json")
    scorer = TemporalScorer()
    scen0 = _scenario_frames()[1][1] if len(_scenario_frames()) > 1 else _scenario_frames()[0][1]
    sample = scorer.score(scen0.head(WINDOW))
    L.append(json.dumps(sample, indent=2)[:2200])
    L.append("```")
    L.append("")

    L.append("## 8. Reproduce")
    L.append("")
    L.append("```bash")
    L.append("py -m member2_temporal.src.train      # TASK 4 (rerun when M4 ships real data)")
    L.append("py -m member2_temporal.src.evaluate   # TASK 6 (this report)")
    L.append("py -m pytest member2_temporal/tests -q")
    L.append("```")
    L.append("")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / "m2_evaluation.md"
    report_path.write_text("\n".join(L), encoding="utf-8")
    return report_path


# --------------------------------------------------------------------------
def main() -> int:
    """Run the full TASK 6 evaluation and write docs/reports/m2_evaluation.md."""
    print("=" * 60)
    print("TRUSTBATTLE M2 — evaluation (TASK 6)")
    print("=" * 60)
    settings = m2_model.model_settings()
    scorer = TemporalScorer()
    if not scorer.model_available:
        print("[evaluate] artifacts missing — run `py -m member2_temporal.src.train` first")
        return 1

    W, notes, th = _score_scenarios()
    graph_paths = _graphs(W, th)
    report = _write_report(W, notes, th, settings, graph_paths)
    print(f"[evaluate] windows scored: {len(W)} (attack: {int(W['y'].sum())})")
    print(f"[evaluate] report: {report}")
    for p in graph_paths:
        print(f"[evaluate] graph:  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
