"""TRUSTBATTLE — Member 4 dataset validation utility (TASK 5).

Validates telemetry datasets against data_schema.md §1 and emits sanity
plots + a team-readable report. Members 1–3 run this on M4's data before
training; exit code 0 = all files valid, 1 = at least one failure.

Hard FAILURES (schema violations — the dataset is unusable):

* missing/extra §1 columns, wrong dtypes (float/int/string),
* ``label`` codes outside {0..6}, NaN anywhere, quality/loss outside [0,1],
* ground-truth pairs misaligned (row counts differ, labels mismatch),
* attack_start=1 without any attacked row in the file (and vice versa).

Warnings (expected *attack signatures*, not defects — reported so nobody
mistakes them for corruption):

* non-monotonic timestamps / duplicated sequence numbers (replay,
  telemetry-manipulation signatures),
* sequence gaps (telemetry manipulation),
* GNSS position far from the truth reference in ``attrs`` (spoof/conflict).

Usage (from repo root)::

    py -m member4_cyber.src.validate_dataset            # data/synthetic + data/attacks
    py -m member4_cyber.src.validate_dataset FILE...    # specific files

Writes docs/reports/m4_dataset_reports.md (+ docs/reports/m4_graphs/).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from member4_cyber.src.schema import (
    COLUMNS,
    FLOAT_COLUMNS,
    INT_COLUMNS,
    LABEL_NAMES,
    VALID_LABELS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "m4_dataset_reports.md"
GRAPHS_DIR = REPO_ROOT / "docs" / "reports" / "m4_graphs"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def validate_dataframe(df: pd.DataFrame, context: str,
                       ground_truth: Optional[pd.DataFrame] = None
                       ) -> Tuple[List[str], List[str]]:
    """Validate one dataset frame → (failures, warnings).

    Failures are schema violations (data unusable); warnings are behavioral
    signatures that legitimate attacks are EXPECTED to produce.
    """
    failures: List[str] = []
    warnings: List[str] = []

    missing = [c for c in COLUMNS if c not in df.columns]
    extra = [c for c in df.columns if c not in COLUMNS]
    if missing:
        failures.append(f"missing columns: {missing}")
    if extra:
        warnings.append(f"extra (non-contract) columns present: {extra}")
        df = df.drop(columns=extra)
    if missing:
        return failures, warnings

    for c in FLOAT_COLUMNS:
        if not pd.api.types.is_numeric_dtype(df[c]):
            failures.append(f"'{c}' must be numeric, got {df[c].dtype}")
    for c in INT_COLUMNS:
        if not pd.api.types.is_integer_dtype(df[c]):
            failures.append(f"'{c}' must be integer dtype, got {df[c].dtype}")
    if not (pd.api.types.is_object_dtype(df["sensor_id"])
            or pd.api.types.is_string_dtype(df["sensor_id"])):
        failures.append(f"'sensor_id' must be string, got {df['sensor_id'].dtype}")
    if failures:
        return failures, warnings

    n_nan = int(df[list(COLUMNS)].isna().sum().sum())
    if n_nan:
        cols = [c for c in COLUMNS if df[c].isna().any()]
        failures.append(f"NaN values in {cols} ({n_nan} total) — schema allows none")

    bad_labels = sorted(set(df["label"].unique()) - VALID_LABELS)
    if bad_labels:
        failures.append(f"unknown label codes {bad_labels}; valid {sorted(VALID_LABELS)}")

    for c in ("gnss_quality", "packet_loss"):
        n_bad = int(((df[c] < 0) | (df[c] > 1)).sum())
        if n_bad:
            failures.append(f"'{c}' has {n_bad} value(s) outside [0, 1]")

    if (df["velocity"] < 0).any():
        failures.append("'velocity' has negative value(s)")

    # ---- ground-truth alignment (§5) ---------------------------------------
    if ground_truth is not None:
        gt = ground_truth
        if len(gt) != len(df):
            failures.append(f"ground truth has {len(gt)} rows but data has {len(df)}")
        else:
            if list(gt.columns) != ["timestamp", "sensor_id", "label", "attack_start"]:
                failures.append(f"ground truth columns {list(gt.columns)} != §5")
            mism = int((gt["label"].to_numpy() != df["label"].to_numpy()).sum())
            if mism:
                failures.append(f"ground truth labels mismatch data on {mism} row(s)")
            mism2 = int((gt["attack_start"].to_numpy() != df["attack_start"].to_numpy()).sum())
            if mism2:
                failures.append(f"ground truth attack_start mismatch on {mism2} row(s)")

    # ---- internal consistency ----------------------------------------------
    attacked = df["label"] > 0
    flagged = df["attack_start"] == 1
    if (flagged & ~attacked).any():
        failures.append(f"{int((flagged & ~attacked).sum())} row(s) have attack_start=1 but label=0")
    if attacked.sum() > 0 and not flagged.any():
        failures.append("attacked rows exist but no attack_start=1 anywhere")

    # ---- behavioral warnings (expected attack signatures) -------------------
    ts = df["timestamp"].to_numpy()
    rewind = int((np.diff(ts) < -1e-9).sum())
    if rewind:
        warnings.append(f"{rewind} timestamp rewind(s) — expected for replay scenarios")
    seq = df["sequence_number"].to_numpy()
    dups = int((np.diff(seq) == 0).sum())
    if dups:
        warnings.append(f"{dups} duplicated sequence step(s) — expected for replay/telemetry_manip")
    gaps = int((np.abs(np.diff(seq)) > 1).sum())
    if gaps:
        warnings.append(f"{gaps} sequence jump(s) — expected for telemetry_manip")

    tlat = df.attrs.get("truth_latitude")
    if tlat is not None and len(tlat) == len(df):
        mlat = 111_320.0
        d = (df["latitude"].to_numpy() - np.asarray(tlat)) * mlat
        dlon = (df["longitude"].to_numpy()
                - np.asarray(df.attrs["truth_longitude"])) * mlat * np.cos(np.radians(float(tlat[0])))
        dev = np.hypot(d, dlon)
        p99 = float(np.quantile(dev, 0.99))
        if p99 > 100.0:
            warnings.append(
                f"GNSS position deviates up to {dev.max():.0f} m from the truth reference "
                "(attrs) — expected for spoof/conflict scenarios")
    return failures, warnings


def validate_file(path: Path) -> Tuple[str, List[str], List[str], Dict[str, Any]]:
    """Validate one dataset file (+ its ground-truth sibling if present)."""
    name = path.name
    try:
        df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    except Exception as exc:  # unreadable file = failure
        return name, [f"cannot read file: {exc}"], [], {}

    gt_path = path.with_name(path.stem + "_ground_truth.csv")
    gt = None
    if gt_path.exists():
        gt = pd.read_csv(gt_path)
    failures, warnings = validate_dataframe(df, name, gt)

    stats: Dict[str, Any] = {
        "rows": int(len(df)),
        "labels": {LABEL_NAMES.get(int(k), str(k)): int(v)
                   for k, v in df["label"].value_counts().sort_index().items()},
        "duration_s": round(float(df["timestamp"].max() - df["timestamp"].min()), 1),
        "ground_truth": bool(gt_path.exists()),
        "speed_mps": [round(float(df["velocity"].min()), 1), round(float(df["velocity"].max()), 1)],
        "n_sensors": int(df["sensor_id"].nunique()),
    }
    return name, failures, warnings, stats


# ---------------------------------------------------------------------------
# sanity plots
# ---------------------------------------------------------------------------
def make_plots(df: pd.DataFrame, name: str, out_dir: Path) -> List[str]:
    """Trajectory map, velocity profile, packet-interval plot → file names."""
    out_dir.mkdir(parents=True, exist_ok=True)
    made: List[str] = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        attacked = df["label"] > 0
        fig, ax = plt.subplots(figsize=(7, 6))
        ax.plot(df["longitude"], df["latitude"], "-", lw=0.7, alpha=0.6, label="track")
        if attacked.any():
            ax.plot(df.loc[attacked, "longitude"], df.loc[attacked, "latitude"],
                    ".", ms=2, color="red", label="attacked rows")
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.set_title(f"{name} — trajectory (red = attacked)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = out_dir / f"m4_{name}_trajectory.png"
        fig.savefig(p, dpi=110)
        plt.close(fig)
        made.append(p.name)

        fig, ax = plt.subplots(figsize=(9, 3))
        ax.plot(df["timestamp"] - df["timestamp"].iloc[0], df["velocity"], lw=0.7)
        if attacked.any():
            ax.plot((df["timestamp"] - df["timestamp"].iloc[0])[attacked],
                    df["velocity"][attacked], ".", ms=2, color="red")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("velocity (m/s)")
        ax.set_title(f"{name} — velocity profile")
        fig.tight_layout()
        p = out_dir / f"m4_{name}_velocity.png"
        fig.savefig(p, dpi=110)
        plt.close(fig)
        made.append(p.name)

        fig, ax = plt.subplots(figsize=(9, 3))
        ax.plot(df["timestamp"] - df["timestamp"].iloc[0], df["packet_delay_ms"],
                lw=0.5, alpha=0.8)
        ax.set_xlabel("time (s)")
        ax.set_ylabel("packet delay (ms)")
        ax.set_title(f"{name} — packet inter-arrival delay")
        fig.tight_layout()
        p = out_dir / f"m4_{name}_packets.png"
        fig.savefig(p, dpi=110)
        plt.close(fig)
        made.append(p.name)
    except Exception as exc:  # plotting must never fail validation
        print(f"[validate] plots skipped for {name}: {exc}")
    return made


# ---------------------------------------------------------------------------
# report + CLI
# ---------------------------------------------------------------------------
def write_report(results: List[Tuple[str, List[str], List[str], Dict[str, Any]]],
                 plot_map: Optional[Dict[str, List[str]]] = None) -> None:
    """Write docs/reports/m4_dataset_reports.md from the validation results."""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plot_map = plot_map or {}
    lines: List[str] = []
    lines.append("# M4 — Dataset Validation Reports\n")
    lines.append("*Generated by* `member4_cyber/src/validate_dataset.py` — "
                 "run after any dataset change; Members 1–3: re-run before training.\n")
    n_fail = sum(1 for _, f, _, _ in results if f)
    lines.append(f"**{len(results)} dataset(s) validated — "
                 f"{'ALL VALID' if n_fail == 0 else f'{n_fail} FAILURE(S)'}**\n")
    for name, failures, warnings, stats in results:
        status = "✅ VALID" if not failures else "❌ INVALID"
        lines.append(f"## {name} — {status}\n")
        lines.append(f"- rows: {stats.get('rows')} · duration: {stats.get('duration_s')} s · "
                     f"speed: {stats.get('speed_mps')} m/s · ground-truth pair: {stats.get('ground_truth')}")
        labels = stats.get("labels", {})
        lines.append(f"- rows per label: " + ", ".join(f"{k}={v}" for k, v in labels.items()))
        if failures:
            lines.append("- **FAILURES:**")
            for f in failures:
                lines.append(f"  - ❌ {f}")
        for w in warnings:
            lines.append(f"- ⚠️ {w}")
        for plot in plot_map.get(name, []):
            lines.append(f"![{plot}](m4_graphs/{plot})")
        lines.append("")
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main(argv: List[str]) -> int:
    """Validate the given files/dirs (defaults: data/synthetic + data/attacks)."""
    paths: List[Path] = []
    if argv:
        for a in argv:
            p = Path(a)
            if not p.is_absolute():
                p = REPO_ROOT / a
            if p.is_dir():
                paths.extend(sorted(p.glob("*.parquet")))
            else:
                paths.append(p)
    else:
        for d in ("data/synthetic", "data/attacks"):
            dd = REPO_ROOT / d
            if dd.exists():
                paths.extend(sorted(dd.glob("*.parquet")))
    if not paths:
        print("[validate] no dataset files found — generate them first:")
        print("           py -m member4_cyber.src.build_datasets")
        return 1

    results: List[Tuple[str, List[str], List[str], Dict[str, Any]]] = []
    plot_map: Dict[str, List[str]] = {}
    any_failure = False
    for p in paths:
        name, failures, warnings, stats = validate_file(p)
        results.append((name, failures, warnings, stats))
        if failures:
            any_failure = True
            print(f"[validate] ❌ {name}")
            for f in failures:
                print(f"           - {f}")
        else:
            print(f"[validate] ✅ {name} ({stats['rows']} rows, labels {stats['labels']})"
                  + (f" — {len(warnings)} signature warning(s)" if warnings else ""))
        if not failures:
            try:
                df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
                plot_map[name] = make_plots(df, Path(name).stem, GRAPHS_DIR)
            except Exception as exc:
                print(f"[validate] plot failure for {name}: {exc}")

    write_report(results, plot_map)
    print(f"[validate] report: {REPORT_PATH}")
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
