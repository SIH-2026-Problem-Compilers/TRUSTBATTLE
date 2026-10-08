# TRUSTBATTLE — Module Interfaces (Integration Contract)

> The pipeline is a chain. Each member owns one link.
> **Rule of the repo:** integration starts on Day 1, not at the end.
> If your interface changes, update this file in the SAME commit.

```
M4 (data+attacks) ──▶ M1 (physical) ──┐
                  └─▶ M2 (temporal) ──┤──▶ M3 (trust+fusion) ──▶ M5 (backend+dashboard)
```

## Owned by Member 4 → consumed by M1, M2, M3

| Item | Path / Name | Format |
|---|---|---|
| Clean synthetic dataset | `data/synthetic/uav_normal_v1.parquet` | schema v1.0 (`data_schema.md`) |
| Attack datasets | `data/attacks/scenario_*.parquet` | schema v1.0 |
| Ground truth | `data/attacks/scenario_*_ground_truth.csv` | `timestamp, sensor_id, label, attack_start` |
| Threat model doc | `member4_cyber/docs/threat_model.md` | Markdown |

## Owned by Member 1 → consumed by M3, M5

| Item | Path / Name | Format |
|---|---|---|
| Physical feature extractor | `member1_physical/src/features.py` | Python import: `extract_physical_features(df) -> df` |
| Anomaly model | `models/physical/isolation_forest.pkl` | joblib (sklearn IsolationForest) |
| Score output | JSON message `scores.physical_consistency`, `scores.anomaly_physical` | `data_schema.md` §2 |

## Owned by Member 2 → consumed by M3, M5

| Item | Path / Name | Format |
|---|---|---|
| Temporal/network feature extractor | `member2_temporal/src/features.py` | Python import: `extract_temporal_features(df) -> df` |
| Temporal score entrypoint | `member2_temporal/src/temporal_module.py` | Python import: `score_observation(window_df, history=None) -> dict` — `history` is an **additive optional** 2nd parameter: preceding rows of the same stream, needed for replay/stale "seen-before" evidence (CR #5); the 1-arg call stays valid. Via integration: `interfaces.score_temporal(window_df, history=None)` / `pipeline.score_window(window_df, prior_rows=None)` / `run_observation(window_df, prior_rows=None)` (context length: `configs/settings.yaml → temporal.context_rows`) |
| Models | `models/temporal/temporal_model.pkl`, `models/temporal/network_model.pkl` | joblib |
| Score output | JSON message `scores.temporal_consistency`, `scores.network_integrity` | `data_schema.md` §2 |

## Owned by Member 3 → consumed by M5

| Item | Path / Name | Format |
|---|---|---|
| Trust engine entrypoint | `member3_trust/src/trust_engine.py` | Python import: `compute_trust(scores: dict, history, observations=None) -> dict` — `observations` is an **additive optional** kwarg (per-sensor estimates → derives `cross_sensor_agreement`, §11); the 2-arg call stays valid. Return dict: `trust`, `alert`, `evidence` (§2, unchanged) **plus additive `scores`** = the effective §2 scores actually used incl. derived `cross_sensor_agreement` (CR #4, APPROVED 2026-10-06) |
| Fusion entrypoint | `member3_trust/src/fusion.py` | Python import: `fuse(observations, trust_scores) -> state_estimate` |
| Config | `models/trust/trust_weights.json`, `models/trust/fusion_config.json` | JSON |
| Score output | `trust.observation_trust` (0–100), `trust.sensor_weights`, `trust.state_estimate` | `data_schema.md` §2 |

## Owned by Member 5 → consumed by everyone (demo)

| Item | Path / Name | Format |
|---|---|---|
| Backend API | `backend/app/` | FastAPI |
| Trust score endpoint | `GET /api/v1/trust/current` | JSON message (§2) |
| Evidence endpoint | `GET /api/v1/evidence/{observation_id}` | JSON `evidence[]` |
| Alerts endpoint | `GET /api/v1/alerts` | JSON `alert{}` |
| Real-time stream | `WS /ws/live` | JSON message (§2) per observation |
| Dashboard | `frontend/` | React + Vite + Leaflet + Recharts |

## Cross-module Python import rule

Member modules import each other through **`integration/`** adapters only — never by reaching into another member's internals:

- `integration/pipeline.py` — connects M1+M2 scores → M3 trust → JSON for M5
- `integration/run_demo.py` — end-to-end demo runner (Normal → attack → trust drop → recovery)
- `integration/interfaces.py` — thin wrapper functions with the exact signatures above

## Change protocol

1. Propose the change in `docs/contracts/CHANGE_REQUESTS.md`.
2. Get a 👍 from the consuming member (comment in the same file).
3. Update `data_schema.md` / this file + your code in one commit.
