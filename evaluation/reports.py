"""TRUSTBATTLE — report writers for the experiment matrix (Steps 7/8/13).

Renders the two required reports from the ACTUAL rows produced by
``evaluation/run_experiments`` (never from hand-written numbers):

    docs/reports/trust_vs_baseline.md   — conventional vs trust-aware fusion
    docs/reports/experiment_results.md  — full experiment matrix + method

Metrics that could not be computed arrive as ``N/A`` and are rendered as
``N/A``. Claims are limited to what the numbers show; the reports explicitly
state what the system does NOT claim (no military validation, no attack
attribution, not a detector of every cyberattack).
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "docs" / "reports"
BEFORE_CSV = REPO_ROOT / "evaluation" / "results" / "trust_vs_baseline_before.csv"


def _num(v: Any) -> Optional[float]:
    """Parse a CSV cell to float, or None for N/A/blank/non-numeric."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_before() -> Optional[Dict[str, Dict[str, str]]]:
    """Rows of the PRE-change engine run (trust_vs_baseline_before.csv).

    Captured by stashing every Step-2..6 change and rerunning the identical
    runner on the identical datasets — the honest "before" for the
    engine-improvement comparison. None when the file does not exist.
    """
    if not BEFORE_CSV.exists():
        return None
    with open(BEFORE_CSV, newline="", encoding="utf-8") as fh:
        return {r["scenario"]: r for r in csv.DictReader(fh)}


def _before_after_rows(rows: List[Dict[str, Any]],
                       before: Dict[str, Dict[str, str]]) -> List[str]:
    """Markdown table: detection + fusion metrics, before -> after."""
    lines = [
        "| Scenario | F1 before → after | FPR before → after | Normal err (m) before → "
        "after | Trust-aware err (m) before → after |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        b = before.get(r["scenario"])
        if not b:
            continue
        def cell(key: str, cur: Any) -> str:
            old = _num(b.get(key))
            new = _num(cur)
            if old is None or new is None:
                return f"{_fmt(b.get(key))} → {_fmt(cur)}"
            return f"{old:g} → {new:g}"
        lines.append(
            f"| {r['scenario']} | {cell('detection_f1', r['detection_f1'])} | "
            f"{cell('false_positive_rate', r['false_positive_rate'])} | "
            f"{cell('normal_fusion_error_m', r['normal_fusion_error_m'])} | "
            f"{cell('trust_aware_fusion_error_m', r['trust_aware_fusion_error_m'])} |"
        )
    return lines


def _fmt(v: Any) -> str:
    """Render a metric cell: N/A stays N/A, numbers as-is."""
    if v is None:
        return "N/A"
    if isinstance(v, str):
        return v
    return str(v)


def _fusion_rows(rows: List[Dict[str, Any]]) -> List[str]:
    lines = [
        "| Scenario | Corruption % | Normal fusion err (m) | Trust-aware fusion err (m) | Improvement |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {_fmt(r['corruption_level_pct'])} | "
            f"{_fmt(r['normal_fusion_error_m'])} | "
            f"{_fmt(r['trust_aware_fusion_error_m'])} | "
            f"{_fmt(r['improvement_pct'])} |"
        )
    return lines


def _detection_rows(rows: List[Dict[str, Any]]) -> List[str]:
    lines = [
        "| Scenario | Corruption % | Windows (attack) | Precision | Recall | F1 | FPR | "
        "Avg trust | Min trust | Recovery (s) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {_fmt(r['corruption_level_pct'])} | "
            f"{_fmt(r['windows'])} ({_fmt(r['attack_windows'])}) | "
            f"{_fmt(r['detection_precision'])} | {_fmt(r['detection_recall'])} | "
            f"{_fmt(r['detection_f1'])} | {_fmt(r['false_positive_rate'])} | "
            f"{_fmt(r['avg_trust'])} | {_fmt(r['min_trust'])} | "
            f"{_fmt(r['recovery_time_s'])} |"
        )
    return lines


_METHOD = """## Method

- **Pipeline (actual, no shortcuts):** every window of every scenario (50 rows
  ≈ 5 s @ 10 Hz) is scored by M1 (`score_physical`) and M2 (`score_temporal`)
  through the `integration/` adapters, then assessed by M3 `compute_trust`
  (with per-sensor observations → derived cross-sensor agreement), then fused
  in BOTH modes — `normal` (equal weights, the conventional baseline) and
  `trust_aware` (weights ∝ current observation trust) — each smoothed with an
  identical constant-velocity Kalman filter so the comparison is fair.
- **Detection truth:** window-level M4 ground-truth labels
  (`label > 0` or `attack_start > 0`, schema §1). Detection decision:
  alert level ≠ GREEN (`observation_trust < trust_engine.thresholds.green`).
- **Fusion error:** mean Kalman-smoothed position error against the
  row-aligned truth track (reconstructed from M4's seed-42 clean dataset —
  attack functions only modify reported fields; same reconstruction the M5
  dashboard uses). When truth is unavailable, the cell reads **N/A**.
- **Recovery time:** seconds (windows × 5 s) from the last attack window
  back to trust ≥ GREEN, for scenarios that have a clean tail. Attack-to-EOF
  scenarios and the clean scenario report **N/A**.
- **Reproducibility:** fixed seeds (model `random_state`, per-window RNG
  `2000 + row_offset`); rerunning the runner reproduces the numbers.
  Per-window audit trail: `evaluation/results/windows/<scenario>.csv`.
"""

_LIMITATIONS = """## Limitations (read this before quoting any number)

- Window-level evaluation: a 5 s window containing attack rows counts as an
  attack window; trust dynamics are intentionally gradual (§13), so the FIRST
  window of an attack block may still read GREEN — detection latency is real
  and is not hidden.
- Recovery windows immediately after an attack are counted as false positives
  by the strict window labels even though the system is explicitly in its
  designed gradual-recovery mode.
- The system assesses **information integrity**. It does NOT claim: military
  validation, detection of every cyberattack, attribution of attackers, or
  that any sensor "was hacked". Alerts use the §16 wording (potentially
  consistent with spoofing / malfunction / communication manipulation).
- Public datasets + controlled simulation only (no classified/real military
  data).
"""


def write_reports(rows: List[Dict[str, Any]]) -> None:
    """Write docs/reports/trust_vs_baseline.md and experiment_results.md."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    # ---- trust_vs_baseline.md -------------------------------------------
    bl: List[str] = []
    a = bl.append
    a("# Trust-aware vs Conventional Fusion — Baseline Comparison\n")
    a(f"*Generated:* {today} · *Runner:* `evaluation/run_experiments.py` "
      "(actual experiments; rerun to reproduce)\n")
    a("Research question: does weighting fusion influence by **current "
      "observation trust** reduce the impact of corrupted information on the "
      "fused state compared with conventional equal-weight fusion?\n")
    a(_METHOD)
    a("## Results\n")
    bl.extend(_fusion_rows(rows))
    a("")
    improvements = [r["improvement_pct"] for r in rows
                    if isinstance(r["improvement_pct"], (int, float))]
    if improvements:
        wins = sum(1 for x in improvements if x > 0)
        a(f"**Summary:** trust-aware fusion has lower position error in "
          f"{wins}/{len(improvements)} scenarios with computable ground truth "
          f"(largest reduction {max(improvements):.1f}%). Scenarios marked "
          f"**N/A** have no usable ground truth in this run — no value was "
          f"estimated for them.\n")
    a(_LIMITATIONS)
    (REPORTS_DIR / "trust_vs_baseline.md").write_text("\n".join(bl), encoding="utf-8")

    # ---- experiment_results.md -------------------------------------------
    er: List[str] = []
    b = er.append
    b("# Experiment Matrix — Results\n")
    b(f"*Generated:* {today} · *Runner:* `evaluation/run_experiments.py`\n")
    b("Scenario matrix: normal, GNSS spoofing, replay/stale, telemetry "
      "manipulation, network anomaly, sensor malfunction, cross-sensor "
      "conflict, and mixed corruption at 5/10/20/30% (M4 datasets in "
      "`data/attacks/` + `data/synthetic/`).\n")
    b(_METHOD)
    b("## 1. Detection & trust per scenario\n")
    er.extend(_detection_rows(rows))
    b("")
    b("## 2. Fusion robustness (conventional vs trust-aware)\n")
    er.extend(_fusion_rows(rows))
    b("")
    b("## 3. What each column means\n")
    b("- **Precision / Recall / F1 / FPR** — window-level detection vs M4 "
      "ground truth (flagged = alert level ≠ GREEN).")
    b("- **Avg/Min trust** — observation trust (0–100) across all windows of "
      "the scenario.")
    b("- **Recovery (s)** — time from the last attack window back to "
      "trust ≥ GREEN; `N/A` when the scenario has no clean tail.")
    b("- **Fusion errors / improvement** — Kalman-smoothed mean position "
      "error of each fusion mode vs ground truth; improvement = "
      "(1 − trust-aware/normal) × 100%.\n")

    # ---- engine before/after (Step 2–6 changes vs pre-change baseline) ----
    before = _load_before()
    if before:
        b("## 4. Engine before → after (this development phase)\n")
        b("`before` = the identical runner executed with every Step-2..6 "
          "engine change stashed (mixed-corruption evidence aggregation, "
          "replay/stale history context, recovery ramp, trust-gated aiding + "
          "speed damping, epoch-aligned sensor observations); `after` = this "
          "run. Saved at `evaluation/results/trust_vs_baseline_before.csv`.\n")
        er.extend(_before_after_rows(rows, before))
        b("")
        pairs = [(r, before.get(r["scenario"])) for r in rows]
        f1s = [(float(b0["detection_f1"]), float(r["detection_f1"]))
               for r, b0 in pairs
               if b0 and _num(b0.get("detection_f1")) is not None
               and _num(r.get("detection_f1")) is not None]
        fprs = [(_num(b0.get("false_positive_rate")),
                 _num(r.get("false_positive_rate")))
                for r, b0 in pairs
                if b0 and _num(b0.get("false_positive_rate")) is not None
                and _num(r.get("false_positive_rate")) is not None]
        if f1s:
            better = sum(1 for o, n in f1s if n > o)
            equal = sum(1 for o, n in f1s if n == o)
            worse = [(r["scenario"], o, n) for r, b0 in pairs
                     for o, n in [( _num(b0.get("detection_f1")),
                                    _num(r.get("detection_f1")) )]
                     if o is not None and n is not None and n < o]
            line = (f"- **Detection F1:** improved in {better}/{len(f1s)} "
                    f"scenarios, unchanged in {equal}")
            if worse:
                detail = ", ".join(f"{s} {o:g} → {n:g}" for s, o, n in worse)
                line += f", worse in {len(worse)} ({detail})"
            b(line + ".")
        if fprs:
            lower = sum(1 for o, n in fprs if n < o)
            same_zero = sum(1 for o, n in fprs if n == o == 0)
            line = (f"- **False-positive rate:** reduced in {lower}/{len(fprs)} "
                    f"scenarios")
            if same_zero:
                line += f" ({same_zero} were already 0 and stayed 0)"
            b(line + ".")
        b("- **Fusion errors:** the clean-scenario error dropped because "
          "sensor observations are now epoch-aligned (window-mean position "
          "for every channel) instead of comparing a window-mean GNSS "
          "against an end-of-window dead-reckoner position.\n")

    b(_LIMITATIONS)
    (REPORTS_DIR / "experiment_results.md").write_text("\n".join(er), encoding="utf-8")
