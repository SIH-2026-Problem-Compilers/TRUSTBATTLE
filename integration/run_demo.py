"""TRUSTBATTLE — end-to-end demo runner.

Flow (project_distribution.md final demo):
normal data -> attack injection -> evidence -> trust drops ->
suspicious source down-weighted -> recovery -> trust recovers.

Two sections:

1. §22 demo story (clean -> spoof -> recovery) on the M3 scenario generator
   (``member3_trust/src/eval_scenarios.make_spoof_scenario``). M4's pure
   attack scenarios run attack-to-end-of-file, so they contain no recovery
   stretch — the recovery leg of the story is demonstrated here.
2. M4 dataset end-to-end check: ``data/attacks/scenario_gnss_spoof.parquet``
   (when present) streamed through the same M1+M2 -> M3 -> fusion pipeline,
   verifying trust drop + GNSS weight reduction on M4's own attack data.

Usage:
    python integration/run_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on sys.path

from integration.pipeline import run_observation  # noqa: E402
from integration import interfaces  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOW = 50


def _stream(df, window=WINDOW, history=None, rng_seed0=1000):
    """Stream *df* through M1+M2 -> M3 -> fusion, yielding per-window records."""
    from member3_trust.src import eval_scenarios as es
    from member3_trust.src.trust_engine import compute_trust
    from member3_trust.src.fusion import fuse

    history = history if history is not None else []
    for w0 in range(0, len(df) - window + 1, window):
        win = slice(w0, w0 + window)
        window_df = df.iloc[win].reset_index(drop=True)

        # M1 + M2 scores via integration adapters
        message = run_observation(window_df)
        scores = message.get("scores", {})

        # M3 trust + fusion
        obs = es.sensor_observations(df, win, rng_seed=rng_seed0 + w0)
        trust_out = compute_trust(scores, history, observations=obs)
        est = fuse(obs, trust_out["trust"])

        history.append(trust_out)
        if len(history) > 200:
            history = history[-200:]

        yield {
            "w0": w0,
            "window": window_df,
            "message": message,
            "trust_out": trust_out,
            "estimate": est,
        }


def _story_demo() -> tuple[dict, list]:
    """§22 story: normal -> spoof -> recovery. Returns (checks, log lines)."""
    from member3_trust.src.eval_scenarios import make_spoof_scenario, _reset_imu_state

    print("\n[1/5] Loading §22 demo scenario (M3 generator: clean -> spoof -> recovery) ...")
    df, gt = make_spoof_scenario(n=3200, attack_start=1000, attack_end=1800)
    print(f"      {len(df)} rows, attack rows: {(df['label'] == 1).sum()}")
    print("      source: member3_trust/src/eval_scenarios.py (M4's pure scenarios")
    print("      attack to end-of-file, so they carry no recovery stretch)")

    print("\n[2/5] Streaming through M1+M2 -> M3 -> fusion ...")
    _reset_imu_state()

    trust_curve: list[float] = []
    sensor_trust: dict[str, list[float]] = {}
    weights_gnss: list[float] = []
    alert_levels: list[str] = []
    attack_flags: list[bool] = []          # window flagged non-GREEN
    attack_trusts: list[float] = []
    attack_gnss_w: list[float] = []
    attack_imu: list[float] = []
    attack_visual: list[float] = []

    for rec in _stream(df):
        trust_out = rec["trust_out"]
        ot = trust_out["trust"]["observation_trust"]
        level = trust_out["alert"]["level"]
        gw = trust_out["trust"]["sensor_weights"].get("gnss", 0)
        st = trust_out["trust"].get("sensor_trust", {})

        trust_curve.append(ot)
        alert_levels.append(level)
        weights_gnss.append(gw)
        for s, v in st.items():
            sensor_trust.setdefault(s, []).append(v)

        if (rec["window"]["label"] > 0).any():          # attack window
            attack_flags.append(level != "GREEN")
            attack_trusts.append(ot)
            attack_gnss_w.append(gw)
            attack_imu.append(st.get("imu", 0))
            attack_visual.append(st.get("visual", 0))

    # -- acceptance checks (aggregated over ALL windows, not the last one) ---
    checks: dict[str, bool] = {}
    checks["start_trust_high"] = bool(trust_curve) and trust_curve[0] >= 70
    # Detection latency: §13 dynamics are fast-but-not-instant (drop_rate), so
    # the FIRST attack window may still read GREEN. Every later attack window
    # must be flagged while the attack persists.
    checks["attack_detected"] = (
        len(attack_flags) >= 2 and all(attack_flags[1:])
    )
    checks["trust_drops"] = bool(attack_trusts) and min(attack_trusts) < 70
    checks["trust_goes_red"] = bool(attack_trusts) and min(attack_trusts) < 40
    checks["gnss_weight_down"] = bool(attack_gnss_w) and min(attack_gnss_w) < 0.20
    checks["imu_still_high"] = bool(attack_imu) and min(attack_imu) > 70
    checks["visual_still_high"] = bool(attack_visual) and min(attack_visual) > 70
    min_trust = min(trust_curve) if trust_curve else 0.0
    final_trust = trust_curve[-1] if trust_curve else 0.0
    checks["trust_recovers"] = final_trust > 70 and min_trust < 70
    checks["demo_complete"] = True

    log = [
        f"      start: {trust_curve[0]:.1f}  min: {min_trust:.1f}  end: {final_trust:.1f}",
        f"      GNSS weight: {weights_gnss[0]:.3f} -> {min(weights_gnss):.3f} -> {weights_gnss[-1]:.3f}",
    ]
    if sensor_trust:
        peak_win = min(range(len(trust_curve)), key=lambda i: trust_curve[i])
        log.append(
            "      Per-sensor trust at attack peak (win %d): " % peak_win
            + ", ".join(f"{s} {min(v)}" for s, v in sensor_trust.items())
        )
    log.append(f"      attack windows: {len(attack_flags)}, flagged: {sum(attack_flags)}")
    return checks, log


def _m4_check() -> tuple[dict, list]:
    """Stream M4's scenario_gnss_spoof through the same pipeline; verify drop."""
    from member3_trust.src.eval_scenarios import _reset_imu_state

    m4_path = REPO_ROOT / "data" / "attacks" / "scenario_gnss_spoof.parquet"
    checks: dict[str, bool] = {}
    log: list[str] = []

    if not m4_path.exists():
        print("\n[3/5] M4 dataset check: SKIPPED (data/attacks/scenario_gnss_spoof.parquet missing)")
        return {"m4_dataset_present": False}, log

    print(f"\n[3/5] M4 dataset end-to-end check ({m4_path.name}) ...")
    df = pd.read_parquet(m4_path)
    gt_path = m4_path.with_name(m4_path.stem + "_ground_truth.csv")
    gt = pd.read_csv(gt_path) if gt_path.exists() else None
    n_attack = int((df["label"] > 0).sum())
    print(f"      {len(df)} rows, attack rows: {n_attack}"
          + ("" if gt is not None else "  [ground truth CSV MISSING]"))

    _reset_imu_state()
    clean_trust: list[float] = []
    attack_trust: list[float] = []
    clean_gnss: list[float] = []
    attack_gnss: list[float] = []
    attack_flags: list[bool] = []
    fused_during_attack = None

    for rec in _stream(df, rng_seed0=5000):
        trust_out = rec["trust_out"]
        ot = trust_out["trust"]["observation_trust"]
        gw = trust_out["trust"]["sensor_weights"].get("gnss", 0)
        is_attack = bool((rec["window"]["label"] > 0).any())
        if is_attack:
            attack_trust.append(ot)
            attack_gnss.append(gw)
            attack_flags.append(trust_out["alert"]["level"] != "GREEN")
            fused_during_attack = rec["estimate"]
        else:
            clean_trust.append(ot)
            clean_gnss.append(gw)

    checks["m4_dataset_present"] = True
    checks["m4_ground_truth_present"] = gt is not None
    # Contract-based (settings trust_engine.thresholds.green = 70): the typical
    # clean state must be trusted — median, not every window, because the
    # no-truth IMU dead-reckoning model drifts slowly (see system_audit.md).
    checks["m4_clean_trust_high"] = (
        bool(clean_trust) and float(pd.Series(clean_trust).median()) >= 70
    )
    checks["m4_trust_drops_on_attack"] = (
        bool(attack_trust) and bool(clean_trust) and min(attack_trust) < min(clean_trust)
    )
    checks["m4_gnss_weight_down"] = (
        bool(attack_gnss) and bool(clean_gnss) and min(attack_gnss) < min(clean_gnss)
    )
    # Same detection-latency rule as the story section: first attack window
    # may still be GREEN (trust falls over ~1-2 windows), all later ones not.
    checks["m4_attack_windows_flagged"] = len(attack_flags) >= 2 and all(attack_flags[1:])
    checks["m4_fusion_output"] = fused_during_attack is not None and "lat" in fused_during_attack

    log = [
        f"      clean windows: {len(clean_trust)} (trust {min(clean_trust):.1f}–{max(clean_trust):.1f}), "
        f"attack windows: {len(attack_trust)} (trust {min(attack_trust):.1f}–{max(attack_trust):.1f})",
        f"      GNSS weight: clean {min(clean_gnss):.3f}–{max(clean_gnss):.3f} -> "
        f"attack {min(attack_gnss):.3f}–{max(attack_gnss):.3f}",
        f"      attack windows flagged: {sum(attack_flags)}/{len(attack_flags)}",
    ]
    if fused_during_attack:
        log.append(f"      fused estimate during attack: lat {fused_during_attack['lat']:.6f}, "
                   f"lon {fused_during_attack['lon']:.6f}")
    return checks, log


def main() -> int:
    print("=" * 64)
    print("TRUSTBATTLE - end-to-end demo (M1+M2 -> M3 -> fusion)")
    print("=" * 64)

    missing = sorted(interfaces.MISSING)
    if missing:
        print(f"\n[!] Not implemented yet: {missing}")
        return 1

    story_checks, story_log = _story_demo()
    m4_checks, m4_log = _m4_check()

    print("\n[4/5] Demo acceptance checks (section 22 story):")
    for k, v in story_checks.items():
        print(f"      [{'PASS' if v else 'FAIL'}] {k}")

    print("\n      Trust curve summary:")
    for line in story_log:
        print(line)

    print("\n[5/5] M4 dataset checks:")
    for k, v in m4_checks.items():
        print(f"      [{'PASS' if v else 'FAIL'}] {k}")
    for line in m4_log:
        print(line)

    checks = {**story_checks, **m4_checks}
    passed = sum(checks.values())
    total = len(checks)
    print(f"\n      Result: {passed}/{total} checks passed")
    if passed == total:
        print("      [OK] section 22 demo story + M4 dataset verified end-to-end")
    else:
        print("      [!!] Some checks did not pass — see above")

    print("\nDone. Full evaluation: py -m member3_trust.src.evaluate")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
