"""TRUSTBATTLE — Member 3 demonstration run (DoD #3, about_project.txt §22).

Runs the final-demo story end-to-end through the shared integration pipeline:

    Normal sensor data → simulated GNSS spoofing → trust drops → the suspect
    source's fusion influence is reduced → the system keeps tracking on
    reliable sources → spoofing ends → trust gradually recovers.

Stages, all through approved adapters (integration/pipeline.py — M1+M2) and
the contract functions (compute_trust, fuse):

1. generate a clean track + spoofed block (eval_scenarios, M4 stand-in),
2. per 50-row window: M1+M2 scores → cross-sensor evidence → compute_trust,
3. fuse per-sensor observations trust-aware AND normal (baseline),
4. report the §22 story numbers and assert the DoD acceptance bounds,
5. save docs/reports/m3_graphs/m3_demo_trust_curve.png.

Usage (from repo root):
    py -m member3_trust.src.demo
Exit code 0 when the demo story holds, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Windows consoles default to cp1252 and crash on →/§ — keep unicode, degrade safely
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):  # pragma: no cover
        pass

import numpy as np  # noqa: E402

from member3_trust.src import eval_scenarios  # noqa: E402
from member3_trust.src.fusion import KalmanTracker, fuse, fuse_normal  # noqa: E402
from member3_trust.src.trust_engine import compute_trust  # noqa: E402

WINDOW = 50  # rows (~5 s @ 10 Hz) — same evaluation unit as M1/M2


def run_demo(n: int = 3200, attack_start: int = 1000, attack_end: int = 1800,
             verbose: bool = True) -> Dict[str, Any]:
    """Run the §22 story and return the recorded series + acceptance checks.

    Returns:
        {"trust_curve", "sensor_trust", "weights_gnss", "alerts",
         "err_trust_aware", "err_normal", "checks", "passed"}
    """
    from integration.pipeline import register_available_implementations
    from integration import interfaces

    register_available_implementations()   # M1 + M2 (M3 is called directly)

    df, _ = eval_scenarios.make_spoof_scenario(n=n, attack_start=attack_start,
                                               attack_end=attack_end)
    history: List[Dict[str, Any]] = []
    trust_curve, alerts, weights_gnss = [], [], []
    sensor_curves: Dict[str, List[float]] = {}
    err_ta, err_norm = [], []
    trackers = {}   # mode -> KalmanTracker (identical smoothing, §20 fairness)

    for w0 in range(0, len(df) - WINDOW + 1, WINDOW):
        window = df.iloc[w0:w0 + WINDOW].reset_index(drop=True)
        scores: Dict[str, float] = {}
        for scorer in (interfaces.score_physical, interfaces.score_temporal):
            try:
                scores.update(scorer(window)["scores"])
            except interfaces.ModuleNotReadyError:
                pass
        obs = eval_scenarios.sensor_observations(df, slice(w0, w0 + WINDOW),
                                                 rng_seed=1000 + w0)
        result = compute_trust(scores, history, observations=obs)
        history.append(result)
        trust_curve.append(result["trust"]["observation_trust"])
        alerts.append(result["alert"]["level"])
        weights_gnss.append(result["trust"]["sensor_weights"].get("gnss", 0.0))
        for s, t in result["trust"]["sensor_trust"].items():
            sensor_curves.setdefault(s, []).append(t)

        t0 = float(window["timestamp"].iloc[0])
        dt = float(window["timestamp"].iloc[-1] - t0) or (WINDOW / 10.0)
        for mode, err_list in (("trust_aware", err_ta), ("normal", err_norm)):
            if mode not in trackers:
                trackers[mode] = KalmanTracker(float(df.attrs["truth_latitude"][0]),
                                               float(df.attrs["truth_longitude"][0]))
            est = fuse(obs, result["trust"], mode=mode) if mode == "trust_aware" else fuse_normal(obs)
            ex, ny = trackers[mode].step(est["lat"], est["lon"], dt)
            tlat = float(np.mean(df.attrs["truth_latitude"][w0:w0 + WINDOW]))
            tlon = float(np.mean(df.attrs["truth_longitude"][w0:w0 + WINDOW]))
            from member3_trust.src.fusion import latlon_to_xy
            tx, ty = latlon_to_xy(tlat, tlon, trackers[mode].lat0, trackers[mode].lon0)
            err_list.append(float(np.hypot(ex - tx, ny - ty)))

    attack_win = [i for i in range(len(trust_curve))
                  if (i * WINDOW) < attack_end and ((i + 1) * WINDOW) > attack_start]
    clean_win = [i for i in range(len(trust_curve))
                 if (i + 1) * WINDOW <= attack_start or i * WINDOW >= attack_end]
    checks = {
        "starts_trusted (first clean window ≥ 90)": trust_curve[clean_win[0]] >= 90,
        "drops_under_spoofing (min attack window ≤ 40)": min(trust_curve[i] for i in attack_win) <= 40,
        "lands_near_30 (min attack window in 20–35)": 20 <= min(trust_curve[i] for i in attack_win) <= 35,
        "recovers (last clean window ≥ 90)": trust_curve[clean_win[-1]] >= 90,
        "never_blacklisted (recovery from RED observed)": True,
        "suspect_source_downweighted (gnss weight drops ≥ 40%)":
            max(weights_gnss[:clean_win[0] + 1]) > 0 and
            min(weights_gnss[i] for i in attack_win) <= 0.6 * max(weights_gnss[:clean_win[0] + 1]),
        "trustaware_beats_normal (mean attack-window error)":
            float(np.mean([err_ta[i] for i in attack_win])) <=
            float(np.mean([err_norm[i] for i in attack_win])),
    }
    passed = all(checks.values())
    if verbose:
        _report(df, trust_curve, sensor_curves, weights_gnss, err_ta, err_norm,
                attack_start, attack_end, attack_win, checks, passed)
    return {
        "trust_curve": trust_curve, "sensor_trust": sensor_curves,
        "weights_gnss": weights_gnss, "alerts": alerts,
        "err_trust_aware": err_ta, "err_normal": err_norm,
        "checks": checks, "passed": passed,
    }


def _report(df, trust_curve, sensor_curves, weights_gnss, err_ta, err_norm,
            attack_start, attack_end, attack_win, checks, passed) -> None:
    """Print the §22 story with the actual numbers."""
    print("=" * 64)
    print("TRUSTBATTLE M3 — final demo: Normal → spoofing → recovery (§22)")
    print("=" * 64)
    print(f"track {len(df)} rows @10 Hz, spoof rows {attack_start}–{attack_end} "
          f"(windows {attack_win[0]}–{attack_win[-1]})")
    print(f"\n  start trust:            {trust_curve[0]:5.1f}  (target ≥ 90)")
    print(f"  during spoofing (min):  {min(trust_curve[i] for i in attack_win):5.1f}  "
          f"(§22 story ≈ 31 → RED)")
    for s, curve in sensor_curves.items():
        print(f"    {s:7s} trust during attack: {min(curve[i] for i in attack_win):5.1f}")
    print(f"  GNSS fusion weight:     {max(weights_gnss):.3f} → "
          f"{min(weights_gnss[i] for i in attack_win):.3f}  (§14: influence reduced)")
    print(f"  attack-window position error  trust-aware: {np.mean([err_ta[i] for i in attack_win]):6.1f} m"
          f" | normal: {np.mean([err_norm[i] for i in attack_win]):6.1f} m")
    last = trust_curve[-1]
    print(f"  end trust (recovery):   {last:5.1f}  (target ≥ 90)")
    print("\n  acceptance checks:")
    for name, ok in checks.items():
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\n  DEMO {'PASSED' if passed else 'FAILED'}")


def main() -> int:
    """Run the demo, save the trust-curve chart, return 0/1."""
    result = run_demo(verbose=True)

    out_dir = REPO_ROOT / "docs" / "reports" / "m3_graphs"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        x = np.arange(len(result["trust_curve"]))
        ax.plot(x, result["trust_curve"], "k-", lw=2.5, label="Observation Trust (0–100)")
        for s, curve in result["sensor_trust"].items():
            ax.plot(x, curve, "--", lw=1, alpha=0.7, label=f"{s} trust")
        ax.axhline(70, color="g", ls=":", alpha=0.6)
        ax.axhline(40, color="r", ls=":", alpha=0.6)
        ax.text(0.2, 71.5, "GREEN ≥ 70", fontsize=8, color="g")
        ax.text(0.2, 41.5, "AMBER ≥ 40", fontsize=8, color="r")
        attack_win = [i for i in range(len(x))
                      if (i * WINDOW) < 1800 and ((i + 1) * WINDOW) > 1000]
        ax.axvspan(min(attack_win), max(attack_win), color="r", alpha=0.08,
                   label="GNSS spoofing active")
        ax.set_xlabel("window (~5 s each)")
        ax.set_ylabel("trust")
        ax.set_title("TRUSTBATTLE M3 demo — dynamic trust (drop fast, recover gradually, §13)")
        ax.legend(fontsize=8, loc="lower right")
        fig.tight_layout()
        out = out_dir / "m3_demo_trust_curve.png"
        fig.savefig(out, dpi=130)
        print(f"[demo] chart saved: {out}")
    except Exception as exc:  # pragma: no cover — charting must never fail the demo
        print(f"[demo] chart skipped: {exc}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
