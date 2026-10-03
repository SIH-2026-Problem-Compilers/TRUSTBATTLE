"""TRUSTBATTLE — end-to-end demo runner.

Flow (project_distribution.md final demo):
normal data -> attack injection -> evidence -> trust drops ->
suspicious source down-weighted -> recovery -> trust recovers.

Replays M4 datasets through M1+M2 -> M3 -> fusion, printing the §22 story.

Usage:
    python integration/run_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on sys.path

from integration.pipeline import run_observation  # noqa: E402
from integration import interfaces  # noqa: E402


def main() -> int:
    print("=" * 64)
    print("TRUSTBATTLE - end-to-end demo (M4 data -> M1+M2 -> M3 -> fusion)")
    print("=" * 64)

    missing = sorted(interfaces.MISSING)
    if missing:
        print(f"\n[!] Not implemented yet: {missing}")
        return 1

    print("\n[1/4] Loading M4 spoof scenario ...")
    from member3_trust.src.eval_scenarios import make_spoof_scenario
    df, gt = make_spoof_scenario(n=3200, attack_start=1000, attack_end=1800)
    print(f"      {len(df)} rows, attack rows: {(df['label'] == 1).sum()}")

    print("\n[2/4] Streaming through M1+M2 -> M3 -> fusion ...")
    from member3_trust.src import eval_scenarios as es
    from member3_trust.src.trust_engine import compute_trust
    from member3_trust.src.fusion import fuse

    WINDOW = 50
    n = len(df)
    trust_history: list[dict] = []
    trust_curve: list[float] = []
    sensor_trust: dict[str, list[float]] = {}
    weights_gnss: list[float] = []
    alerts: list[str] = []
    checks: dict[str, bool] = {}

    for w0 in range(0, n - WINDOW + 1, WINDOW):
        win = slice(w0, w0 + WINDOW)
        window = df.iloc[win].reset_index(drop=True)

        # M1 + M2 scores via integration adapters
        message = run_observation(window)
        scores = message.get("scores", {})

        # M3 trust + fusion
        obs = es.sensor_observations(df, win, rng_seed=1000 + w0)
        trust_out = compute_trust(scores, trust_history, observations=obs)
        est = fuse(obs, trust_out["trust"])

        trust_history.append(trust_out)
        if len(trust_history) > 200:
            trust_history = trust_history[-200:]

        ot = trust_out["trust"]["observation_trust"]
        trust_curve.append(ot)
        alerts.append(trust_out["alert"]["level"])

        for s, v in trust_out["trust"].get("sensor_trust", {}).items():
            sensor_trust.setdefault(s, []).append(v)
        weights_gnss.append(trust_out["trust"]["sensor_weights"].get("gnss", 0))

        attack = (window["label"] > 0).any()
        flagged = trust_out["alert"]["level"] != "GREEN"
        if attack and not flagged:
            checks["attack_detected"] = False
        elif attack and flagged:
            checks["attack_detected"] = True

        if w0 == 0:
            checks["start_trust_high"] = ot >= 70
        if attack:
            checks["trust_drops"] = ot < 70
            if ot < 40:
                checks["trust_goes_red"] = True
            else:
                checks["trust_goes_red"] = False
            checks["gnss_weight_down"] = weights_gnss[-1] < 0.20
            checks["imu_still_high"] = sensor_trust.get("imu", [0])[-1] > 70
            checks["visual_still_high"] = sensor_trust.get("visual", [0])[-1] > 70

    # recovery check
    final_trust = trust_curve[-1]
    min_trust = min(trust_curve)
    checks["trust_recovers"] = final_trust > 70 and min_trust < 70
    checks["demo_complete"] = True

    print("\n[3/4] Demo acceptance checks (section 22 story):")
    for k, v in checks.items():
        status = "PASS" if v else "FAIL"
        print(f"      [{status}] {k}")

    print("\n[4/4] Trust curve summary:")
    print(f"      start: {trust_curve[0]:.1f}  min: {min_trust:.1f}  end: {final_trust:.1f}")
    print(f"      GNSS weight: {weights_gnss[0]:.3f} -> {min(weights_gnss):.3f} -> {weights_gnss[-1]:.3f}")
    if sensor_trust:
        peak_win = min(range(len(alerts)), key=lambda i: trust_curve[i])
        print(f"      Per-sensor trust at attack peak (win {peak_win}): "
              + ", ".join(f"{s} {min(v)}" for s, v in sensor_trust.items()))

    passed = sum(checks.values())
    total = len(checks)
    print(f"\n      Result: {passed}/{total} checks passed")
    if passed == total:
        print("      [OK] section 22 demo story verified end-to-end")
    else:
        print("      [!!] Some checks did not pass — see above")

    print("\nDone. Full evaluation: py -m member3_trust.src.evaluate")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
