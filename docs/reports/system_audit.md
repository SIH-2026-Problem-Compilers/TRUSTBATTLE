# TRUSTBATTLE — System Audit Report

> **Generated:** 2026-10-05 · **Scope:** audit, test, harden and document the *existing* end-to-end system (M1–M5 + integration).
> Nothing was rebuilt, no architecture was changed, no metrics were invented. Every number below is
> produced by an actual run recorded in this audit; commands to reproduce each item are given inline.

**TL;DR — headline results after the audit**

| Check | Result |
|---|---|
| Root test suite (`py -m pytest -q`) | **152 passed, 0 failed, 0 skipped, 1 warning** |
| End-to-end demo (`py integration/run_demo.py`) | **exit 0, 16/16 acceptance checks**, byte-identical across 2 runs |
| Scenario playback via the API | was **hardcoded mock data for all 8 buttons** → now real M4 → M1 → M2 → M3 pipeline (fixed) |
| `/ws/live` | was a **fixed mock story, ignoring scenario selection** → now follows the selected scenario (fixed) |
| ML usage (M1) | IsolationForest produced scores but **did not reach trust** → now influences `physical_consistency` (fixed, white-box test) |
| M3 §22 demo script | 6/7 — the 1 failure (`lands_near_30`) **pre-exists this audit** (verified by stashing) |

---

## 1. Architecture verification

Verified against `docs/contracts/module_interfaces.md`, `README.md` §6 and the actual code:

```
M4 (data/attacks/*.parquet + *_ground_truth.csv)
        ├─▶ M1 member1_physical  ─ physical_consistency, anomaly_physical + evidence
        └─▶ M2 member2_temporal  ─ temporal_consistency, anomaly_temporal, network_integrity + evidence
                    └─▶ M3 member3_trust ─ observation_trust(0–100), sensor_weights, state_estimate
                                └─▶ M5 backend (FastAPI) ─ REST + /ws/live ─▶ frontend (React/Vite)
```

* **Adapters:** `integration/interfaces.py` + `integration/pipeline.py` register **M1 + M2 + M3** at import time; verified by `tests/test_end_to_end.py::test_integration_adapters_are_registered` (`interfaces.MISSING` empty).
* **Cross-module import rule:** backend and integration reach member modules only through `integration/` adapters for scoring/trust (`score_physical`, `score_temporal`, `compute_trust`, `fuse`); direct member imports in the backend are limited to M3 eval helpers already used before this audit.
* **Schema:** `data_schema.md` §1/§2/§3 field sets honoured everywhere checked (see §4, §7). No schema change was made; the one additive interface extension is filed as **CR #4** in `docs/contracts/CHANGE_REQUESTS.md`.
* **Score conventions:** all `*_consistency/*_integrity/cross_sensor_agreement` observed in [0,1]; `anomaly_*` in [0,1] higher=anomalous; `observation_trust` in [0,100]. Asserted by backend + e2e tests.

## 2. Module verification

| Module | Entry points verified present | Tests |
|---|---|---|
| M1 `member1_physical/src/` | `features.extract_physical_features`, `physical_module.score_observation`, `train`, `evaluate`, `model.load_artifacts` | 25 ✅ |
| M2 `member2_temporal/src/` | `features`, `temporal_module.score_observation`, network model, `train`, `evaluate` | 44 ✅ |
| M3 `member3_trust/src/` | `trust_engine.compute_trust`, `fusion.fuse`, `train`, `demo`, `evaluate` | 34 ✅ |
| M4 `member4_cyber/src/` | `generate_data`, `attack_simulator`, `build_datasets`, `validate_dataset` | 15 ✅ |
| M5 `backend/app/` + `frontend/` | FastAPI v1 router, `/ws/live`, services, React dashboard (builds ✅) | 17 ✅ |
| Cross-module `tests/` | `tests/test_end_to_end.py` (new this audit) | 17 ✅ |

Note: `member4_cyber/tests` existed but was **not in `pytest.ini` testpaths** — M4's 15 tests never ran from the root suite. Added (this audit); they pass.

## 3. Data-flow verification

* `data/attacks/` contains **10 scenario parquet + 10 ground-truth CSV pairs** (6 pure: gnss_spoof, replay, telemetry_manipulation, network_anomaly, sensor_malfunction, cross_sensor_conflict; 4 mixed c05/c10/c20/c30), all 6000 rows, labels {0..6}, `attack_start` marking, validated by M4's suite.
* `data/synthetic/uav_normal_v1.parquet` — clean base track (labels {0}); M4 scenarios are row-aligned with it (parquet drops `DataFrame.attrs`, truth is reconstructible from seed 42 via `generate_data.simulate_truth` — documented in `build_datasets.py`).
* `data/real/` — `geolife.csv` (59 094 real GPS rows) + `device_capture.csv`; exposed via `/api/v1/real/*`.
* Pipeline message flow (verified by running it): window → `run_observation` → `scores` + `evidence` (M1 physics checks + M2 temporal/network checks) → `compute_trust(scores, history, observations)` → `trust`/`alert`/`evidence`/`scores` → `fuse(obs, trust)` → `state_estimate` → `TrustMessage` → REST/WS → dashboard.
* After the fix, M1/M2 evidence is **no longer overwritten** by M3's evidence block (the old backend `result.update(trust_out)` replaced it); API messages now carry **28 evidence entries** (M1 physics + M2 network + M3 aggregation entries).

## 4. API verification

Endpoints exercised with a live `TestClient` (all 200/202):

| Endpoint | Status | Notes |
|---|---|---|
| `GET /api/v1/health`, `/api/v1/health` | ✅ | schema_version 1.0 |
| `GET /api/v1/trust/current` | ✅ | real pipeline message (scores incl. derived `cross_sensor_agreement`, `state_estimate{lat,lon,velocity,mode,weights_used,sensors_used}`, 28 evidence entries) |
| `GET /api/v1/trust/history` | ✅ | falls back to DB rows, then service |
| `GET /api/v1/evidence/{id}` | ✅ | **fixed:** returns `[]` instead of mock evidence for unknown ids in real mode |
| `GET /api/v1/alerts` | ✅ | same mock-leak fix applied |
| `GET /api/v1/trajectory?scenario=…` | ✅ | now scenario-specific (was always the same spoof story); true track reconstructed from M4's clean base |
| `POST /api/v1/demo/attack/{scenario}` | ✅ | returns `source: "pipeline"` for all 12 valid scenarios (`source: "mock_story"` only as labelled fallback) |
| `POST /api/v1/demo/advance/{id}` | ✅ | scores the next 50-row window through M1+M2→M3→fusion (~0.1 s/window) |
| `POST /api/v1/demo/stop/{id}`, `/real/session`, `/real/ingest`, `/real/trajectory`, `/real/datasets` | ✅ | real-data paths untouched and healthy |
| `WS /ws/live` | ✅ | verified live: streams real pipeline messages, **and re-opens its session when a scenario is selected** (epoch bump) |

**Frontend → API → service → pipeline → response → frontend trace** (`DashboardPage.jsx`):
`api.startScenario(key)` → `POST /demo/attack/{key}` (pipeline session) → `/ws/live` switches to that scenario → messages `applyMessage()` → `TrustGauge` (observation trust + historical reliability + consensus), `SensorStatusCards` (per-sensor observation trust + weights), `EvidencePanel` (evidence list + recommended action), `AlertBanner` (“Possible causes: …”), `TrustChart` / `SensorWeightsChart` (history), `MapView` (true/reported/fused). `npm run build` passes (only a >500 kB chunk-size warning). No frontend-computed trust values — all scores come from the backend (frontend only clamps/colors).

## 5. Model verification

| Artifact | Present | Loaded in scoring path | Prediction reaches trust? |
|---|---|---|---|
| `models/physical/isolation_forest.pkl` (+scaler, limits) | ✅ | ✅ (`PhysicalScorer.model_available`, test) | **was ❌ → now ✅** (see H3) |
| `models/physical/oneclass_svm_baseline.pkl` | ✅ | evaluation baseline only (by design) | n/a (baseline) |
| `models/temporal/temporal_model.pkl`, `network_model.pkl` (+scalers, limits) | ✅ | ✅ (test loads all four objects) | ✅ — M2 already blends model p90 into `temporal_consistency`/`network_integrity` (`0.5·base + 0.5·(1−anomaly)`) |
| `models/trust/trust_weights.json`, `fusion_config.json` | ✅ | ✅ (`compute_trust`/`fuse` read them) | trust model is the agreed weighted-geometric evidence model (not ML) — see §6 |

Calibrated thresholds observed in the artifacts: M1 `m1_threshold_ = 0.459`, M2 network `m2_threshold_ = 0.630` (both calibrated at `fpr_target 0.01` on clean holdout during training, `random_state 42`).

**Which parts are AI/ML vs deterministic vs trust math (Step 6):**

| Stage | Nature | Evidence |
|---|---|---|
| M1 physics checks (position/velocity residual, heading, course, smoothness…) | **deterministic physics/limits** (config + learned percentile limits) | `physics_evidence()` |
| M1 `anomaly_physical` | **ML** — IsolationForest p90 over window | `model_anomaly_score()` |
| M1 `physical_consistency` | deterministic evidence blend **+ ML contribution** (`max(heuristic severity, model excess above calibrated threshold)`) | `score()` + white-box test |
| M2 temporal/network evidence (rewind, seq continuity, IAT spikes, loss…) | **deterministic** | `temporal_evidence()`, `network_evidence()` |
| M2 `anomaly_temporal` / model part of `*_consistency` | **ML** — two IsolationForests p90 | `temporal_module.score()` |
| M3 `compute_trust` | **trust mathematics** — weighted geometric mean + attribution matrix + §13 dynamics (drop 0.6 / recover 0.25) + weakest-link headline | `trust_engine.py` |
| M3 `fuse` | **trust-aware weighted average** (weights ∝ trust, floor 0.05, Σ=1); Kalman baseline for §20 | `fusion.py` |
| M4 | **deterministic seeded simulation** | `build_datasets` seed 42 |

No deep learning is used and none was added. Nothing deterministic is presented as an AI model.

## 6. Integration verification

`python integration/run_demo.py` → **exit 0, 16/16 checks** (9 §22 story checks + 7 M4 dataset checks):

```
story:  start 93.5 → min 5.0 (RED) → end 93.0
        GNSS weight 0.249 → 0.017 → 0.244
        per-sensor trust at attack peak: gnss 5.0, imu 92.8, visual 93.5, net 95.7
        attack windows 16, flagged 15  (§13 detection latency: 1st attack window still GREEN)
M4 data: scenario_gnss_spoof.parquet 6000 rows / 3000 attack rows + ground-truth CSV
        clean windows 60: trust 73.2–87.7 | attack windows 60: trust 5.0–76.8
        GNSS weight clean 0.206–0.241 → attack 0.017–0.211 | flagged 59/60 attack windows
        fused estimate emitted during attack (lat 28.605798, lon 77.215516)
```

The demo now runs **two sections**: the §22 clean→spoof→recovery story on the M3 scenario generator
(M4's pure scenarios run attack-to-end-of-file and therefore contain no recovery stretch — this is stated in the
output), plus a genuine end-to-end pass over M4's own dataset. **No value in the story is hardcoded** —
trust, weights, alerts and the fused estimate are computed per window (verified by reading `run_demo.py`
and by the differential behaviour across scenarios in §12-E).

`py -m member3_trust.src.demo` → **6/7** (see issue **M2** below; the failure pre-exists this audit).

## 7. Test coverage summary

`py -m pytest -q` from repo root (after this audit):

| Suite | Tests | Result |
|---|---|---|
| `member1_physical/tests` | 25 | ✅ |
| `member2_temporal/tests` | 44 | ✅ |
| `member3_trust/tests` | 34 | ✅ |
| `member4_cyber/tests` | 15 | ✅ (now wired into root `pytest.ini`) |
| `backend/tests` | 17 | ✅ |
| `tests/test_end_to_end.py` (new) | 17 | ✅ |
| **Total** | **152** | **152 passed, 1 warning** (upstream `starlette.testclient` httpx deprecation — not ours) |

New cross-module tests cover exactly the requested behaviours with **relational/contract assertions**
(no invented constants): normal runs; spoof runs; M1 evidence; M2 evidence; M3 observation trust;
weights produced and Σ=1; fusion output finite; `trust_after_attack < trust_before_attack`;
`gnss_weight_after_attack < gnss_weight_before_attack`; IMU/visual stay > GREEN during spoofing;
fused error < reported error against M4's true track; `trust_after_recovery > trust_during_attack`
and ≥ GREEN threshold (read from `configs/settings.yaml`, not hardcoded); adapter registration;
message shape incl. derived `cross_sensor_agreement`; plus a white-box test proving the M1 model
prediction changes `physical_consistency`.

Known coverage gaps: no browser/E2E UI test (Node build only); `/real/ingest` path covered by code but not automated tests; backend WS covered by manual TestClient trace (documented above), not by a pytest.

## 8. Reproducibility check

| Item | Finding |
|---|---|
| Seed config | `configs/settings.yaml → simulation.random_seed: 42`; M1/M2 IF `random_state: 42`; M4 `build_datasets` seed 42 |
| Integration reproducibility | `py integration/run_demo.py` run **twice → byte-identical stdout**, exit 0 both times, 16/16 |
| Data generation | M4 test `test_reproducible_same_seed` ✅; spot-checked `make_spoof_scenario(seed=42)` twice = identical, `seed=43` differs (intended randomness preserved) |
| Model reproducibility | training deterministic (`random_state 42`); artifacts present and reload-verified by tests |
| Scenario scoring | deterministic: fixed `rng_seed` per window (`1000 + w0` …); no wall-clock or unordered randomness in the pipeline |
| Where randomness is intentional | M4 noise seeds, `sensor_observations` noise draws (seeded per window), mock story jitter (`random.uniform` in `MockTrustService` — mock path only) — left untouched |

## 9. Potential bugs / issues found

Severity = CRITICAL / HIGH / MEDIUM / LOW / INFO. “Fixed” means fixed and re-verified in this audit.

### Fixed — HIGH

* **H1 — Dashboard scenario playback was entirely hardcoded mock data.**
  `RealTrustService.start_attack_scenario()` served `self._mock._demo_story` for **every** scenario
  (fabricated curve: `obs_trust = 92.0 − 0.65·i`, weights `0.33 − (93−trust)·0.0035`, evidence detail
  strings like `"GNSS reliability = 94% (last 30 days)"`), and `ws.py` opened a **fixed `"gnss_spoof"`**
  mock session regardless of selection — so all 8 buttons showed the same fabricated story.
  *Fix:* pipeline-backed sessions that stream the requested M4 dataset window-by-window through
  M1→M2→M3→fusion; WS follows the selected scenario via a scenario/epoch signal; mock story remains
  only as a **labelled** fallback (`source: "mock_story"`) when pipeline/dataset is unavailable.
* **H2 — Integration stub dropped M3's `observations` argument; backend swallowed the `TypeError`.**
  `interfaces.compute_trust(scores, history)` never forwarded `observations`, and `_run_pipeline` wrapped
  the call in `except Exception: pass` — so **every** backend trust message was computed cold
  (empty history → no §13 dynamics; no cross-sensor agreement).
  *Fix:* optional passthrough in the adapter (filed as **CR #4**), exceptions now logged once
  (`_warn_once`) instead of silently swallowed; M1/M2 evidence no longer overwritten; derived
  `cross_sensor_agreement` surfaced in `scores`.
* **H3 — M1's IsolationForest never influenced downstream trust.**
  `physical_consistency` blended only the deterministic heuristic severity, and M3's weight file has no
  `anomaly_*` entries — the model output only reached the raw `anomaly_physical` field and cause wording,
  while `trust_engine`'s docstring claimed `anomaly_*` were terms of the mean.
  *Fix (minimal, no trust-model change):* M1 now uses
  `severity = max(heuristic, (anomaly_p90 − m1_threshold_)/(1 − m1_threshold_))` in
  `physical_consistency` — the model adds evidence whenever it is more alarmed than the heuristic and
  above its calibrated FPR target; the clean baseline is unchanged (M1 report metrics identical, only
  the example consistency value + timestamp changed). Mirrors the pattern M2 already implemented.
  Proven by `test_m1_model_prediction_influences_physical_consistency` (white-box: forcing the model to
  output ones vs zeros changes the score).
  *Note:* M3's docstring wording about `anomaly_*` as direct mean terms was corrected.
* **H4 — `run_demo.py` claimed “Loading M4 spoof scenario” but used M3's fallback generator, and its
  acceptance checks only reflected the **last** attack window (values were overwritten each iteration).
  *Fix:* honest data-source labels + checks aggregated over **all** attack windows (with an explicit,
  documented 1-window §13 detection-latency allowance) + a new real M4 dataset section (7 extra checks).
* **H5 (test integrity) — `test_output_shape` asserted the exact return-key set of `compute_trust`;**
  updated to the extended contract (`trust/alert/evidence/scores`) and strengthened with an assertion
  that the derived cross-sensor score is surfaced.

### Fixed — MEDIUM / LOW

* **M6 — mock values leaking into real mode:** `get_current_trust` fell back to the mock story after the
  scenario ended; `get_evidence`/`get_alerts` could return mock content for real ids (ids even overlapped,
  e.g. `obs_000050`). *Fix:* once real messages exist they are always served; real mode returns `[]`
  rather than fabricated evidence/alerts; mock only as last resort when the pipeline is unavailable.
* **L7 — duplicate scorer execution:** `run_observation` called each scorer **twice** per window
  (once for scores, once for evidence) — 2× cost on the heaviest stage. *Fix:* single call.
* **L8 — UI wording (data labelling):** “Battlefield Position” → “Position Estimate”; “Scenario Playback”
  → “Scenario Playback — controlled simulation (not real battlefield data)”; “Real Data …” → “Real public
  GPS data — model predicts live”; “Sensor Status” → “Sensor Observation Trust (current)” (+ comment that
  these are dynamic observation-trust values, not historical reliability). Header/project title unchanged.
* **L9 — unused import** (`Tuple` in `trust_engine.py`) removed; `asyncio` import dropped from
  `trust_service.py` when its use disappeared.

### Open — MEDIUM (documented, deliberately not auto-fixed)

* **M1 (open) — Network-anomaly scenario barely moves observation trust.**
  Measured on `scenario_network_anomaly.parquet`: model p90 0.58–0.71 ≥ threshold 0.63 (so M2's own
  detector fires — consistent with its reported R=1.0), `network_integrity` 0.99 → 0.63, net sensor trust
  89 → 80, failing evidence “Packet inter-arrival spikes / burst / loss” shown on the dashboard — but the
  alert stays **GREEN** during the first attack windows (obs trust 85.5 → 76.0, floor ~69 late in the run).
  Cause: the weakest-link headline is dominated by the slowly-drifting GNSS term; `network_integrity`
  (weight 0.15) never makes `net` the weakest sensor, and a floor of ~80 is above the GREEN threshold.
  *Recommendation (team decision, needs a CR):* retune `trust_engine.weights`/attribution for the network
  family and/or add a “critical evidence family failing” alert path — changing weights would alter
  reported M3 metrics, so it was not done unilaterally.
* **M2 (open, pre-existing) — `py -m member3_trust.src.demo` fails 1/7 checks: `lands_near_30`
  (expects min attack trust in 20–35; actual 5.0 = engine floor `consistency_floor 0.05`).**
  **Verified pre-existing:** with every audit change to M1 stashed, the check still fails with min 5.0.
  It is a stale §22 narrative expectation (README example says “→ 24”) left behind by the 2026-10-04
  real-data retrain. The other 6 checks pass (start 93.5 → 5.0 → end 93.0). *Recommendation:* the team
  either updates the expected range to the current engine floor or re-tunes `_CROSS_SCALE_M`; do **not**
  silently widen the check.
* **M3 (open, pre-existing) — clean-phase drift on M4 data.** The no-truth observation model dead-reckons
  IMU/visual from accel; over 300 s the derived IMU drifts ~50 m from GNSS, so GNSS cross-sensor quality
  decays 0.75 → 0.51 and clean trust slides (≈88 → ≈73 over the clean prefix). All clean windows stay
  GREEN in the final configuration, but the trend is a modelling artifact, not a data problem.
  *Recommendation:* light trust-region correction or periodic re-anchoring in `sensor_observations`.
* **M4 (open, pre-existing) — M3 evaluation on mixed scenarios:** `py -m member3_trust.src.evaluate`
  regenerated this audit: gnss_spoof **P 1.000 / R 0.983 / F1 0.992 / FPR 0.000** (unchanged); mixed
  c05–c30 recall 0.500–0.722, F1 0.136–0.500, FPR 0.307–0.500 vs pre-audit baseline
  (F1 0.143–0.510, FPR 0.289–0.476) — deltas ≤ 0.024 caused by deeper replay/telemetry severity (H3)
  extending the §13 recovery tail past sparse attack windows. §20 position errors are `nan` on M4 data
  (parquet drops truth attrs) — pre-existing and already noted in AGENTS.md; the **backend** now
  reconstructs the true track for the trajectory panel instead of drawing “true = reported”.
* **M5 (open) — README/AGENTS staleness:** README §12 “currently 103 passed” and §13 “end-to-end demo
  remaining” are outdated (root suite is 152; demo is done). Counts updated where this audit owns them;
  the README roadmap section is left to the team.

### Open — LOW / INFO

* **L10** — Frontend fallback constants when a field is absent (`sensor_reliability ?? 94`,
  `consensus ?? value+2`) and duplicated GREEN/AMBER thresholds (40/70) in `api.js`; values match
  `settings.yaml`, but they can drift. *Recommendation:* expose thresholds from `/api/v1/health`.
* **L11** — SQLAlchemy `echo=settings.debug` logs every query at INFO (noisy dev logs; `DEBUG=1` default).
* **L12** — `MockTrustService` demo story is intentionally fabricated (clearly class-named “Mock”, now
  labelled `source: "mock_story"`); it is only served when the pipeline or dataset is missing.
* **L13** — Vite build warns the main chunk is 716 kB (>500 kB); `frontend/dist/` and `node_modules/`
  are correctly gitignored.
* **L14** — Backend/API latency: first pipeline call pays a one-time sklearn/joblib import + model load
  (≈2–20 s machine-dependent), then ≈0.1 s per 5 s window. Scenario start is instant (windows are scored
  on advance, not precomputed); trajectories for a full 6000-row scenario take ≈8–10 s on first request
  and are cached per scenario.
* **INFO** — `sensor_reliability` is computed as Σ(prior × current weight), i.e. it moves slightly with
  dynamic weights; since all priors are 0.92–0.95 the variation is ≪1 point, so the
  **reliability ≠ observation-trust** distinction holds in practice (they are also displayed separately:
  “Historical reliability” vs the gauge value).
* **INFO** — “possible cause” wording verified everywhere: `alert.possible_causes` are hedged
  (“GNSS spoofing”, “replay / stale data”, …) with `recommended_action`; tests
  `test_never_claims_hacked` / `test_spoof_causes_are_hedged` pass; the dashboard shows them under
  “Possible causes:”. No attack-attribution or “production-ready” claims found in code or UI.

## 10. Recommended fixes (remaining, priority order)

1. **Team CR for network-family trust weight** (M1-open) so network anomalies can reach AMBER/RED —
   then re-run `member3_trust.src.evaluate` and update the report in the same commit.
2. **Decide the §22 depth expectation** (M2-open): update `lands_near_30` range *or* re-tune
   `_CROSS_SCALE_M`; then `py -m member3_trust.src.demo` returns to 7/7.
3. **Re-anchor the simulated IMU** (M3-open) to stop the clean-phase trust slide on M4 data.
4. Refresh README §12/§13 numbers (152 tests, demo status) — owner call.
5. Surface alert thresholds via `/api/v1/health` and drop the frontend fallback constants (L10).
6. Add a pytest for `/ws/live` scenario switching and `/real/ingest` (coverage gap, §7).

## 11. Items that are already complete (verified from code/tests, not from READMEs)

* Contracts (`data_schema.md`, `module_interfaces.md`), shared config, threat model, prompts.
* M1: features + physics evidence + IF/OCSVM + calibration + evaluation report + 25 tests; artifacts load.
* M2: temporal + network features, two IFs + OCSVM, evidence, evaluation + 44 tests; artifacts load.
* M3: weighted-geometric trust engine, per-sensor attribution, §13 dynamics, alert wording, trust-aware +
  normal fusion, floor/normalisation, 34 tests (down-weighting, recovery, Σ=1, min-weight floor, no
  “hacked” claims), evaluation report regenerated on M4 data.
* M4: 10 dataset/ground-truth pairs + validate script + 15 tests incl. same-seed reproducibility.
* M5: FastAPI REST + WS + SQLite persistence + mock/real services; React dashboard (gauge, sensor cards,
  evidence, alerts, trust/weight charts, map, scenario buttons, real-data modes); 17 backend tests; build passes.
* Integration: adapters registered, `run_demo.py` end-to-end (16/16 incl. real M4 data), cross-module
  e2e tests (17).

## 12. Items that were NOT actually complete (before this audit)

1. **Dashboard scenario playback (synthetic mode) used no real computation** — all buttons + the live WS
   stream served one fabricated mock story (H1). *Now fixed and verified per scenario.*
2. **Backend trust messages carried no §13 dynamics and no cross-sensor evidence** (silent `TypeError`, H2).
3. **The M1 ML model had no effect on trust/fusion** (H3) although docs/README presented it as the
   “ML anomaly detection layer” feeding the trust engine.
4. **`run_demo.py` did not use M4 data** despite its banner and AGENTS.md saying so, and its acceptance
   checks only evaluated the final attack window (H4).
5. **Root `pytest` never ran M4's 15 tests** (`pytest.ini` testpaths omission).
6. **Root `tests/` was empty** — no cross-module assertions existed (now 17).
7. **Trajectory “true” track was wrong for M4 data** (parquet has no truth attrs → “true” silently became
   the spoofed reported line); now reconstructed from the seed-42 clean base (or omitted if unavailable).
8. **README/AGENTS claims that were stale:** “103/120 tests”, “full flow once M4 lands” (demo exists),
   “m3 demo 7/7” (actually 6/7 before and after this audit — see M2-open).

---

# Final results (Step 18)

### A. Files changed

| File | Change |
|---|---|
| `backend/app/services/trust_service.py` | pipeline-backed scenario sessions, session caching, real/mock separation, scenario-specific trajectory builder, warning-once logging, lock around advances |
| `backend/app/api/ws.py` | WS follows selected scenario (epoch), no hard-coded scenario |
| `integration/interfaces.py` | `compute_trust(..., observations=None)` passthrough (CR #4) |
| `integration/pipeline.py` | single scorer call per stage (was 2×) |
| `integration/run_demo.py` | honest labels, aggregated checks, new M4 dataset section (16 checks) |
| `member1_physical/src/physical_module.py` | ML severity contributes to `physical_consistency` (max of heuristic + calibrated model excess) |
| `member3_trust/src/trust_engine.py` | returns effective `scores` block; docstring corrected; unused import removed |
| `member3_trust/tests/test_trust_engine.py` | `test_output_shape` extended + strengthened (CR #4) |
| `pytest.ini` | `member4_cyber/tests` added to testpaths |
| `frontend/src/pages/DashboardPage.jsx`, `components/ScenarioControl.jsx`, `components/SensorStatusCards.jsx` | wording only (data-labelling + trust-semantics clarity) |
| `docs/contracts/CHANGE_REQUESTS.md` | CR #4 filed (additive interface extension) |
| `docs/reports/m1_evaluation.md`, `m3_evaluation.md` + `m3_graphs/*` | regenerated by the modules' own evaluate scripts (no hand-edited numbers) |
| `tests/test_end_to_end.py` | **new** — 17 cross-module tests |

### B. Tests executed

`py -m pytest -q` (root, all suites) · `py -m pytest member4_cyber/tests -q` (pre-wiring check) ·
`py integration/run_demo.py` ×4 (incl. 2× reproducibility diff) · `py -m member3_trust.src.demo` ×4
(incl. stashed-baseline comparison) · `py -m member1_physical.src.evaluate` ·
`py -m member3_trust.src.evaluate` · live API/WS traces via `TestClient` (trust, evidence, alerts,
trajectory, 8 scenario streams, WS switch) · `npm run build` (frontend).

### C. Tests passed/failed

**152 passed / 0 failed / 0 skipped / 1 warning** (upstream starlette deprecation). `run_demo` 16/16.
M3 §22 demo 6/7 (1 pre-existing failure, unchanged by this audit).

### D. End-to-end pipeline status

**Working and reproducible:** M4 parquet → M1 (physics + IF) → M2 (temporal + network IF) → M3 trust
(0–100, per-sensor attribution, §13 dynamics) → sensor weights → trust-aware fusion → REST/WS →
dashboard. Byte-identical output across runs; all values computed at runtime.

### E. Scenario verification table (measured through the API, `source=pipeline`)

| Scenario | Data | M1 | M2 | M3 | Fusion | Status |
|---|---|---|---|---|---|---|
| Normal | ✅ `uav_normal_v1` | ✅ evidence, trust ≥ 73.3 | ✅ | ✅ GREEN | ✅ | ✅ GREEN throughout |
| GNSS spoofing | ✅ `scenario_gnss_spoof` | ✅ velocity/position residual fails | ✅ | ✅ 73.3 → **5.3 RED**, GNSS weight 0.25 → 0.017 | ✅ | ✅ |
| Replay / stale | ✅ `scenario_replay` | ✅ | ✗→✅ timestamp/seq/freshness fails | ✅ → **29.7 RED** | ✅ | ✅ |
| Telemetry manip | ✅ `scenario_telemetry_manipulation` | ✅ | ✅ seq/rate/freshness fails | ✅ → **66.0 AMBER** | ✅ | ✅ |
| Network anomaly | ✅ `scenario_network_anomaly` | ➖ | ✅ IAT/loss/burst fails, `network_integrity` → 0.63 | ⚠️ trust 75.4, stays GREEN (M1-open) | ✅ | ⚠️ evidence-level only |
| Sensor malfunction | ✅ `scenario_sensor_malfunction` | ✅ accel inconsistency | ➖ | ✅ → **5.8 RED** | ✅ | ✅ |
| Cross-sensor conflict | ✅ `scenario_cross_sensor_conflict` | ✅ | ➖ | ✅ → **69.9 AMBER** | ✅ | ✅ |
| Mixed 20% | ✅ `scenario_mixed_c20` | ✅ | ✅ | ✅ → **28.9 RED** | ✅ | ✅ |

(✅ verified by run · ➖ not the primary detector for that family · every row also returned 28 evidence
entries, all six score keys incl. derived `cross_sensor_agreement`, and a fused `state_estimate`.)

### F. AI components actually used

IsolationForest (M1 physical) + 2× IsolationForest (M2 temporal, network) — all loaded from `models/`,
scored at runtime, thresholds calibrated at FPR ≤ 1%; One-Class SVM = evaluation baseline only;
M3 trust/fusion = deterministic weighted mathematics (documented as such); M4 = seeded simulation.
M1's model now demonstrably influences `physical_consistency` → trust → fusion (white-box test).

### G. Hardcoded / mock data found

1. **`MockTrustService._build_demo_story`** — fully fabricated trust/weight/evidence curve; was served
   for every scenario button and the WS stream → **now restricted to a labelled fallback** (`source: mock_story`).
2. **WS hard-coded `"gnss_spoof"`** → **removed** (scenario-driven).
3. **Frontend fallback constants** (`94`, `consensus+2`, thresholds 40/70) — kept (absent-field defaults),
   documented as L10.
4. **`run_demo` banner** claimed M4 data while using the fallback generator → **fixed + real M4 section added**.
5. No fake precision/F1 anywhere: all reported metrics come from the modules' evaluate scripts
   (regenerated this audit); no scenario-specific UI values found.

### H. Issues fixed

H1 mock playback · H2 swallowed `TypeError`/cold trust · H3 ML not reaching trust · H4 demo label + weak
checks · H5 contract test extended · M6 mock leakage in real mode · L7 double scoring · L8 UI wording ·
L9 unused imports · M4-root: M4 tests excluded from root suite · empty root `tests/`.

### I. Issues remaining

M1 network-family trust sensitivity · M2 stale `lands_near_30` expectation (pre-existing) ·
M3 clean-phase drift artifact (pre-existing) · M4 mixed-scenario FPR + §20 `nan` errors (pre-existing) ·
M5 README/AGENTS number staleness · L10–L14 (fallback constants, SQL echo logs, chunk size, cold-start
latency, WS/real-ingest test gaps).

### J. Exact next steps for the AITHON demo

1. **Start backend + frontend:** `uvicorn backend.app.main:app --reload` then `cd frontend && npm run dev`.
2. **Open the dashboard** — live WS streams the GNSS-spoof scenario computed by the real pipeline
   (trust ~93 → RED ~5 → recovers; GNSS weight 0.25 → 0.017; per-sensor cards: gnss collapses,
   imu/visual/net stay ~93–96).
3. **Click through the 8 scenario buttons** — each now streams its own M4 dataset through M1+M2→M3
   (use GNSS Spoofing for the main story; Replay → RED ~30; Sensor Malfunction → RED ~6;
   Mixed 20% → RED ~29). Mention Network Anomaly shows **evidence-level** detection only (open item M1).
4. **Show the Evidence panel + “Possible causes” wording** — 28 live checks, hedged causes, recommended action.
5. **Show the map** — true vs reported vs fused trajectories (true track reconstructed from M4's clean base).
6. **Optional live-data flex:** “Live Device GPS” and “Real Dataset (GPS traces)” buttons run real public
   GPS data through the same models.
7. **If asked about numbers:** `py -m pytest -q` → 152 passed; `py integration/run_demo.py` → 16/16;
   `py -m member3_trust.src.evaluate` → gnss_spoof F1 0.992; all reproducible with seed 42.
8. **Do not claim:** attack attribution, production readiness, real military data, or the §22
   “lands near 30” depth (actual floor is 5 — open item M2).
