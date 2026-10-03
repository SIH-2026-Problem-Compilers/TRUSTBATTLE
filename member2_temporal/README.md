# member2_temporal — Temporal & Telemetry/Network Analysis (Member 2)

TRUSTBATTLE Layer 3 (temporal, about_project.txt §9) + Layer 4
(cyber/network, §10). Consumes Member 4's datasets (replay /
telemetry-manip / network-anomaly scenarios are M2's primary targets),
produces `temporal_consistency` + `anomaly_temporal` + `network_integrity`
scores and human-readable evidence for Member 3 (trust engine) and
Member 5 (dashboard).

## Contract surface (docs/contracts/module_interfaces.md)

```python
from member2_temporal.src.features import extract_temporal_features   # df -> df (m2_* columns)
from member2_temporal.src.temporal_module import score_observation    # -> {"scores": {...}, "evidence": [...]}
```

Both are registered automatically by `integration/pipeline.py` (as
`score_temporal`). Score conventions follow `data_schema.md` §3:
consistency/integrity 0–1 (higher = trustworthy), anomaly 0–1
(higher = anomalous). `score_observation(row_or_window, history=None)`
accepts a dict row, list of rows, or a window DataFrame; pass the
preceding rows as `history` so replay "seen-before" checks work across
window boundaries.

## Layout

```
src/
├── common.py             shared column/finite/rolling helpers
├── data_loader.py        TASK 1 — strict data_schema.md §1 validation (SchemaError on mismatch)
├── features.py           TASK 2 — extract_temporal_features(df) (exact contract signature)
├── network_features.py   TASK 3 — packet rate/IAT/loss/burst features (m2_pkt_*, m2_net_*)
├── model.py              TASK 4 — IsolationForest (primary) + One-Class SVM baseline, calibration
├── train.py              TASK 4 — training entry point (see below)
├── temporal_module.py    TASK 5 — score_observation + interpretable temporal/network checks
├── evaluate.py           TASK 6 — metrics, graphs, docs/reports/m2_evaluation.md
└── fallback_data.py      interim stand-in generator (NOT the contract dataset)
tests/                    pytest suite (44 tests)
```

## Usage (from repo root)

```bash
py -m member2_temporal.src.train       # trains + calibrates + saves models/temporal/*.pkl
py -m member2_temporal.src.evaluate    # writes docs/reports/m2_evaluation.md + m2_graphs/
py -m pytest member2_temporal/tests -q
```

## Features (all prefixed m2_)

*Temporal:* timestamp deltas vs rolling median, non-monotonic/gap/rewind/
drift/repeat/stale-age, sequence gaps/jumps/duplicates/backward steps/
expected-next error/duplicate-run/seen-before, rolling speed std/range,
jerk, speed & acceleration change rates, heading rate, and a combined
`m2_stale_score` / sticky `m2_stale_active` replay severity (0–1).

*Network (§10):* packet rate vs rolling median (deficit), inter-arrival
time + excess over rolling median×3 (the "950 ms vs 20 ms" §10 signature),
IAT std, catch-up bursts, packet loss + excess, combined `m2_net_disruption`.

## Status / integration notes for the team

- **Definition of done (prompts/member2_temporal_analysis.txt): COMPLETE.**
  Contract functions importable; `models/temporal/temporal_model.pkl` +
  `network_model.pkl` (+ scalers, OCSVM baselines, limits JSONs) saved and
  reloadable; 44/44 pytest green; evaluation report with real numbers at
  `docs/reports/m2_evaluation.md`.
- `data/synthetic/` and `data/attacks/` are **still empty** (Member 4).
  Training and evaluation use `src/fallback_data.py`, a clearly-marked
  schema-v1.0-compatible stand-in writing nothing outside
  `member2_temporal/tests/data/`. Rerun `train` + `evaluate` unchanged when
  M4's files land — the loader consumes `scenario_*.parquet` +
  `*_ground_truth.csv` pairs per `data_schema.md` §5.
- Interim results (see `docs/reports/m2_evaluation.md`): combined
  (temporal ∪ network) precision 1.000, recall 1.000, FPR 0%. Replay is
  caught via re-broadcast sequence numbers + frozen-clock stale age — this
  closes the replay gap M1's physics module reported. Per-detector thresholds
  are calibrated at fpr_target/2 (Šidák) so the UNION meets the 0.010 target.
- Tunables live in `configs/settings.yaml` under `temporal:` (added by M2;
  flagged for review in `docs/contracts/CHANGE_REQUESTS.md` #2).
- `*.pkl` artifacts are gitignored — regenerate locally with
  `py -m member2_temporal.src.train` after cloning.
