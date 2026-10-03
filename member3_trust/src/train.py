"""TRUSTBATTLE — Member 3 artifact seeding (TASK 1; data_schema.md §4).

Writes the two M3 contract artifacts consumed by the M5 backend:

    models/trust/trust_weights.json   — evidence weights (seeded from
        configs/settings.yaml → trust_engine.weights), per-sensor attribution
        matrix, sensor priors, learned-model upgrade hook
    models/trust/fusion_config.json   — fusion mode + min weight + hook

No ML training yet: the trust model is the agreed weighted model. When a
learned replacement (logistic/ensemble) is trained later, this script gains
the training step and sets ``model_type``/``learned_model`` — callers
(compute_trust, M5 backend) never change.

Usage (from repo root):
    py -m member3_trust.src.train
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from member3_trust.src.settings import (  # noqa: E402
    FUSION_CONFIG_PATH,
    TRUST_DIR,
    TRUST_WEIGHTS_PATH,
    _default_weights_doc,
    reset_caches,
    trust_settings,
)


def main() -> int:
    """Seed/refresh the M3 contract artifacts (idempotent)."""
    print("=" * 60)
    print("TRUSTBATTLE M3 — seeding trust artifacts (TASK 1)")
    print("=" * 60)

    TRUST_DIR.mkdir(parents=True, exist_ok=True)

    weights_doc = _default_weights_doc()
    with open(TRUST_WEIGHTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(weights_doc, fh, indent=2)

    s = trust_settings()
    fusion_doc = {
        "schema_version": "1.0",
        "mode": s["fusion_mode"],
        "min_sensor_weight": s["min_sensor_weight"],
        "model_type": "trust_proportional",
        "learned_model": None,
    }
    with open(FUSION_CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(fusion_doc, fh, indent=2)

    reset_caches()
    print(f"[seed] {TRUST_WEIGHTS_PATH}")
    print(f"       weights: {json.dumps(weights_doc['weights'])}")
    print(f"[seed] {FUSION_CONFIG_PATH}")
    print(f"       mode={fusion_doc['mode']} min_sensor_weight={fusion_doc['min_sensor_weight']}")
    print("[seed] done — compute_trust()/fuse() now load the artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
