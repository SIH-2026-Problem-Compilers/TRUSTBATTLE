# member1_physical — Physical & Sensor Analysis (Member 1)

TRUSTBATTLE Layer 1 (physics) + Layer 2 (anomaly detection) per
`about_project.txt` §7–8. Consumes Member 4's datasets, produces
`physical_consistency` + `anomaly_physical` scores and human-readable evidence
for Member 3 (trust engine) and Member 5 (dashboard).

## Contract surface (docs/contracts/module_interfaces.md)

```python
from member1_physical.src.features import extract_physical_features   # df -> df (m1_* columns)
from member1_physical.src.physical_module import score_observation    # -> {"scores": {...}, "evidence": [...]}
```

Both are registered automatically by `integration/pipeline.py`. Score
conventions follow `data_schema.md` §3: consistency 0–1 (higher = trustworthy),
anomaly 0–1 (higher = anomalous).

## Layout

```
src/
├── data_loader.py      TASK 1 — strict data_schema.md §1 validation (SchemaError on mismatch)
├── features.py         TASK 2 — extract_physical_features(df) (exact contract signature)
├── model.py            TASK 3 — IsolationForest (primary) + One-Class SVM baseline, calibration
├── train.py            TASK 3 — training entry point (see below)
├── physical_module.py  TASK 4 — score_observation + interpretable physics checks
├── evaluate.py         TASK 5 — metrics, graphs, docs/reports/m1_evaluation.md
└── fallback_data.py    interim stand-in generator (NOT the contract dataset)
tests/                  pytest suite (25 tests)
```

## Usage (from repo root)

```bash
py -m member1_physical.src.train       # trains + calibrates + saves models/physical/*.pkl
py -m member1_physical.src.evaluate    # writes docs/reports/m1_evaluation.md + m1_graphs/
py -m pytest member1_physical/tests -q
```

## Physics features (all prefixed m1_)

position residual (GNSS vs velocity-propagated), velocity residual (reported vs
**leak-anchored** IMU dead reckoning — the anchor is gated on acceleration
agreement so spoof/malfunction survives instead of being absorbed),
acceleration consistency, heading consistency (per-step gyro innovation),
course-vs-heading, speed-component consistency, trajectory smoothness/deviation,
GNSS quality, plus normalized GNSS-vs-IMU and sensor-to-sensor disagreement.

The historical speed limit (§7 "GNSS says 120 km/h, IMU says 55 km/h, historical
max 80 km/h") is re-learned from clean data (p99.9) into
`models/physical/physical_limits.json` and feeds the `m1_speed_excess_mps`
feature and the "Historical speed envelope" evidence check.

## Status / integration notes for the team

- `data/synthetic/` and `data/attacks/` are **still empty** (Member 4). Training
  and evaluation currently use `src/fallback_data.py`, a clearly-marked
  schema-v1.0-compatible stand-in writing **nothing** outside
  `member1_physical/tests/data/`. Rerun `train` + `evaluate` unchanged when M4's
  files land — the loader consumes `scenario_*.parquet` + `*_ground_truth.csv`
  pairs per `data_schema.md` §5 and raises `SchemaError` on any mismatch.
- Interim results (see `docs/reports/m1_evaluation.md`): precision 1.000,
  FPR 0%, spoof/malfunction/conflict recall 1.000. Replay is partially visible
  to physics by design (stale nav on a straight track is physically
  undetectable) — that residual belongs to Member 2's temporal layer.
- Tunables live in `configs/settings.yaml` under `physical:` (added by M1;
  flagged for review in `docs/contracts/CHANGE_REQUESTS.md`).
