"""TRUSTBATTLE LIVE — terminal demo driver.

Drives the controlled live simulation through the REAL pipeline
(M1 -> M2 -> M3 -> trust-aware fusion) and prints the ACTUAL computed values.
It never fabricates a score: it only controls the INPUT scenario; every trust
number, sensor weight and evidence line below is M3's computed output.

Usage (from repo root, backend running or not — the script works standalone):

    py scripts/run_live_demo.py              # full NORMAL -> SPOOF -> RECOVERY
    py scripts/run_live_demo.py --api        # drive a RUNNING backend instead
                                             # (http://localhost:8000)

Fixed seed 42 -> approximately the same story every run. Offline, no external
services.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPOOF_WINDOWS = 26       # ~13 s of spoofing at 0.5 s/step
RECOVERY_WINDOWS = 20    # ~10 s of recovery


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _print_msg(label: str, t: dict, alert_level: str, scores: dict) -> None:
    st = t.get("sensor_trust") or {}
    w = t.get("sensor_weights") or {}
    print(f"[{_ts()}] {label}")
    print(f"  Trust: {t['observation_trust']:.1f}  ({alert_level})  "
          f"GNSS w: {w.get('gnss', 0):.3f}")
    print(f"  GNSS: {st.get('gnss', 0):.1f}  IMU: {st.get('imu', 0):.1f}  "
          f"VISUAL: {st.get('visual', 0):.1f}  NET: {st.get('net', 0):.1f}")
    print(f"  phys={scores.get('physical_consistency', 0):.2f} "
          f"cross={scores.get('cross_sensor_agreement', 0):.2f} "
          f"temp={scores.get('temporal_consistency', 0):.2f} "
          f"net={scores.get('network_integrity', 0):.2f}")


def _print_evidence(evidence: list) -> None:
    """Evidence items arrive as dicts (API mode) or pydantic models
    (standalone mode) — normalize to attribute access."""
    def _get(e, k, default=None):
        return e.get(k, default) if isinstance(e, dict) else getattr(e, k, default)

    fails = [e for e in evidence if not _get(e, "pass", True)]
    if fails:
        print("  TRUST REDUCED BECAUSE:")
        for e in fails[:4]:
            print(f"    - {_get(e, 'check')}: {str(_get(e, 'detail', ''))[:90]}")


def run_standalone() -> int:
    from backend.app.services.live_demo import get_live_controller

    ctl = get_live_controller()
    ctl.reset()

    print("=" * 64)
    print("TRUSTBATTLE LIVE — controlled simulation through the REAL")
    print("pipeline M1 -> M2 -> M3 -> trust-aware fusion (seed 42)")
    print("=" * 64)

    def phase(name: str, scenario: str, steps: int) -> None:
        ctl.set_scenario(scenario)
        for i in range(steps):
            msg = ctl.step()
            t = msg.trust.model_dump()
            _print_msg(f"{name}" + (f" ({i + 1}/{steps})" if steps > 1 else ""),
                       t, msg.alert.level, msg.scores.model_dump())
            _print_evidence(msg.evidence)
            time.sleep(0.15)

    phase("NORMAL", "normal", 4)
    phase("GNSS SPOOFING", "gnss_spoof", SPOOF_WINDOWS)
    phase("RECOVERY", "normal", RECOVERY_WINDOWS)

    print("-" * 64)
    print("Event log (state transitions derived from computed values):")
    for e in ctl.events(20):
        print(f"  {e['time']}  {e['text']}")
    print("Done. All values above were computed by M1/M2/M3 — none hardcoded.")
    return 0


def run_via_api(base: str) -> int:
    def post(path: str) -> dict:
        req = urllib.request.Request(base + path, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def get(path: str) -> dict:
        with urllib.request.urlopen(base + path, timeout=60) as r:
            return json.loads(r.read())

    print(f"TRUSTBATTLE LIVE via API at {base}")
    post("/api/v1/live/scenario/reset")
    time.sleep(0.3)

    def phase(name: str, scenario: str, steps: int) -> None:
        if scenario:
            post(f"/api/v1/live/scenario/{scenario}")
        for i in range(steps):
            msg = post("/api/v1/live/step")
            t = msg["trust"]
            _print_msg(name + (f" ({i + 1}/{steps})" if steps > 1 else ""),
                       t, msg["alert"]["level"], msg["scores"])
            _print_evidence(msg["evidence"])
            time.sleep(0.15)

    phase("NORMAL", "normal", 4)
    phase("GNSS SPOOFING", "gnss_spoof", SPOOF_WINDOWS)
    phase("RECOVERY", "normal", RECOVERY_WINDOWS)

    print("-" * 64)
    ev = get("/api/v1/live/events?limit=20")["events"]
    print("Event log:")
    for e in ev:
        print(f"  {e['time']}  {e['text']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", action="store_true",
                    help="drive a running backend at --base instead of standalone")
    ap.add_argument("--base", default="http://localhost:8000",
                    help="backend base URL when --api is used")
    args = ap.parse_args()
    try:
        return run_via_api(args.base) if args.api else run_standalone()
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
