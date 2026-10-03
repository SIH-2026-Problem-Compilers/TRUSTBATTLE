# member3_trust — Trust Engine & Trust-Aware Fusion (Member 3)

The core of TRUSTBATTLE (about_project.txt §12–§16): combines physical,
temporal, network, cross-sensor and historical evidence into a dynamic
**Observation Trust Score (0–100)**, redistributes fusion influence per
sensor, and explains every alert to a human operator.

## Contract surface (docs/contracts/module_interfaces.md)

```python
from member3_trust.src.trust_engine import compute_trust   # scores -> trust message
from member3_trust.src.fusion import fuse                  # observations -> state_estimate
```

Both are registered automatically by `integration/pipeline.py` (as
`compute_trust`/`fuse`). Message shapes follow `data_schema.md` §2/§3:

* `compute_trust(scores, history=None, observations=None)` →
  `{"trust": {...}, "alert": {...}, "evidence": [...]}`. `observations`
  is an *additive* third parameter (per-sensor estimates for the derived
  §11 cross-sensor evidence); the two-argument contract call stays valid.
* `fuse(observations, trust_scores)` → `{"lat", "lon", "velocity", ...}`
  (+ `mode`/`weights_used`/`sensors_used` diagnostics).
* Alert levels (settings `trust_engine.thresholds`): GREEN ≥ 70,
  AMBER 40–70, RED < 40. Wording rule §16: hypotheses only
  ("potentially consistent with spoofing/malfunction/…") — never "hacked".

## Layout

```
src/
├── settings.py         config loader (trust_engine/fusion sections + artifacts)
├── trust_engine.py     TASKS 1+2+4 — compute_trust: weighted geometric evidence model,
│                       per-sensor attribution, §13 dynamic trust, alerts, explainability
├── fusion.py           TASK 3 — fuse() trust-aware vs normal + KalmanTracker baseline
├── train.py            seeds models/trust/trust_weights.json + fusion_config.json
├── eval_scenarios.py   TASK 5 data — M4 loader preference + clearly-marked stand-in generator
├── demo.py             DoD #3 — the §22 final-demo story with acceptance checks
└── evaluate.py         TASK 5 — corruption sweep, metrics, docs/reports/m3_evaluation.md
tests/                  pytest suite (34 tests)
```

## Usage (from repo root)

```bash
py -m member3_trust.src.train        # (re)seed the two contract artifacts
py -m member3_trust.src.demo         # §22 story; exit 0 iff all checks pass
py -m member3_trust.src.evaluate     # corruption sweep -> m3_evaluation.md + graphs
py -m pytest member3_trust/tests -q
```

## Design (see module docstrings for details)

* **Weighted geometric mean over evidence** ("no-absolution"): all evidence
  must agree for high trust; one catastrophic red flag pulls a sensor's
  quality down proportionally to its attribution instead of being averaged
  away (§1's threat model). Historical reliability is one evidence term (§12).
* **Attribution matrix** routes observation-level evidence to sensors: low
  physical consistency implicates GNSS, not the self-contained IMU →
  §22's "GNSS 28% while IMU 94%" emerges from the data.
* **Derived cross-sensor agreement (Layer 5, §11)**: nobody emits the
  contract field yet, so M3 derives it from the per-sensor estimates with
  consensus-based blame routing (the best-agreeing pair defines the
  consensus; the outlier is implicated proportionally to its distance).
  Once upstream emits `cross_sensor_agreement`, the derived value steps aside.
* **§13 dynamics**: per-sensor trust moves toward its evidence target with
  `drop_rate` 0.6 (fast) / `recovery_rate` 0.25 (gradual) from settings —
  never a permanent blacklist. State is *pure*: continued from `history`.
* **Weakest-link observation trust** + separate `consensus_trust` diagnostic.
* **Learned-model hook**: `trust_weights.json` carries `model_type` /
  `learned_model`; a future logistic/ensemble model slots in without
  changing callers.

## Status / integration notes for the team

- **Definition of done (prompts/member3_trust_engine.txt): COMPLETE.**
  1. `compute_trust` + `fuse` importable and pipeline-registered ✓
  2. `models/trust/trust_weights.json` + `fusion_config.json` seeded ✓
  3. Demo run: trust **92.3 → 21.1 (RED) → 92.2**, all 7 acceptance checks
     pass (`py -m member3_trust.src.demo`); GNSS weight 0.252 → 0.068 ✓
  4. `docs/reports/m3_evaluation.md` with the Normal-vs-Trust-Aware
     robustness table (trust-aware wins at every corruption level:
     e.g. 30% → 6.7 m vs 9.2 m; F1 0.80–1.00, FPR ≤ 0.036) ✓
  5. `py -m pytest member3_trust/tests -q` → 34 passed ✓
- **Data caveat (M4):** all numbers come from the clearly-marked
  `src/eval_scenarios.py` generator (schema-§1-compatible; conventions
  matched to M1/M2's fallback tracks so the interim models are
  in-distribution). `load_scenarios()` prefers M4's real
  `data/attacks/scenario_*.parquet` + `*_ground_truth.csv` pairs the moment
  they exist — rerun `evaluate` unchanged.
- **Cross-module infra (announced):** added root `pytest.ini`
  (`--import-mode=importlib`) so M1/M2/M3 test suites collect together
  despite shared test-file basenames. Repo-wide `py -m pytest -q` → 103 passed.
- M1's artifacts were regenerated via its documented entry point
  (`py -m member1_physical.src.train`) so the demo runs real models; all
  `models/**/*.pkl` stay gitignored — regenerate locally after cloning.
- Tunables: `configs/settings.yaml` → `trust_engine:` / `fusion:` sections
  (M3-owned); artifact seed mirrors them.
