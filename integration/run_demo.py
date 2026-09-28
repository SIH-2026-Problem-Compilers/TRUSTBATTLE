"""TRUSTBATTLE — end-to-end demo runner.

Flow (project_distribution.md final demo):
normal data -> attack injection -> evidence -> trust drops ->
suspicious source down-weighted -> recovery -> trust recovers.

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
    print("=" * 60)
    print("TRUSTBATTLE — end-to-end demo")
    print("=" * 60)

    missing = sorted(interfaces.MISSING)
    if missing:
        print("\n[!] Not implemented yet (owners must register them):")
        for name in missing:
            print(f"    - {name}")
        print("\nPipeline will run with the stages that exist and skip the rest.")

    # TODO(teams): load a real window from data/synthetic/ once M4 ships:
    #   import pandas as pd
    #   df = pd.read_parquet("data/synthetic/uav_normal_v1.parquet")
    #   window = df.head(50)
    # Until then this exits after the readiness check.

    # Example (uncomment once modules are ready):
    # message = run_observation(window)
    # print(json.dumps(message, indent=2))

    print("\nDone. See docs/contracts/module_interfaces.md for next steps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
