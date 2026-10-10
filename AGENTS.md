# AGENTS.md — TRUSTBATTLE

> Context file for AI coding agents. Read this before touching any code.
> Last updated: 2026-10-10 (**full-project scan + push** — `main` = `195e7a8` pushed to GitHub; suite **211 passed**, 11 `node --test` frontend tests, `vite build` OK, backend live with `/api/v1/pipeline/status` self-check green (source `pipeline`, trust ~91) and `/docs` 200; `data/trustbattle.db` untracked after GH001 100 MB rejection; previously 2026-10-09 **TRUSTBATTLE LIVE judge demo** `67c18c6` + **LIVE SENSOR INTEGRITY COMPARISON**; remaining items are **non-blocking hardening** only — see §6)

## 1. What this project is

**TRUSTBATTLE** — *AI-Driven Battlefield Information Integrity & Trust Assessment Engine*.

It is NOT a normal sensor-fusion system and NOT a simple cyberattack detector. It is an **information-integrity layer** that answers one question per observation:

> "Can we trust this particular sensor observation **right now** — and why?"

**Pipeline:** Sensor Data → Analysis → Evidence → Trust Score → Trust-Aware Fusion → Explainable Dashboard.

Full concept & design rationale: `about_project.txt` (the authoritative brief). Team split: `project_distribution.md`.

### Non-negotiable domain rules
- The system assesses **trust/integrity**, never claims *"this sensor was hacked"* without sufficient evidence. It is an integrity-assessment system, **not an attack-attribution system** (`about_project.txt` §16).
- **Sensor reliability** (historical, e.g. 94%) is separate from **observation trust** (this measurement right now, e.g. 31%).
- Trust is **dynamic**: it drops during anomalies and recovers gradually afterwards (§13).
- Everything uses **public datasets + controlled simulation only** (no classified/real military data).
- The output must be **explainable**: scores + evidence list + possible causes + recommended action, not just "anomaly = 96%" (§15).

## 2. Architecture (5-member pipeline)

```
M4 (attack/data) ──▶ M1 (physical) ──┐
                 └──▶ M2 (temporal) ──┼──▶ M3 (trust+fusion) ──▶ M5 (backend+dashboard)
```

| Module | Folder | Owner role | Contract output |
|---|---|---|---|
| M1 | `member1_physical/` | AI/ML | `physical_consistency` + `anomaly_physical` scores, evidence |
| M2 | `member2_temporal/` | AI/ML | `temporal_consistency` + `network_integrity` scores, evidence |
| M3 | `member3_trust/` | AI/ML | `observation_trust` (0–100), `sensor_weights`, `state_estimate` |
| M4 | `member4_cyber/` | Cyber | Attack scenarios + synthetic data + ground truth (schema v1.0) |
| M5 | `backend/` + `frontend/` | Software | FastAPI + React real-time dashboard |

**MVP scenario:** UAV navigation integrity — GNSS + IMU + visual estimate + telemetry/network metadata, with attacks: normal / GNSS spoofing / replay-stale / telemetry manipulation / network anomaly / sensor malfunction / cross-sensor conflict.

## 3. Repo map

```
member{1,2,3,4,5}_*/    # one module per member — only edit the one you're told to
backend/app/            # M5: FastAPI (api, core, models, services, db)
frontend/               # M5: React + Vite + Leaflet + Recharts
integration/            # ONLY cross-module wiring: interfaces.py, pipeline.py, run_demo.py
data/
  raw/                  # public datasets (never modified; gitignored)
  synthetic/            # M4 clean trajectories
  attacks/              # M4 scenario_*.parquet + scenario_*_ground_truth.csv pairs
  processed/            # feature outputs written by M1/M2
models/                 # trained artifacts: physical/ temporal/ trust/ (*.pkl gitignored)
configs/settings.yaml   # shared config — all tunables live here
docs/contracts/         # data_schema.md + module_interfaces.md — READ FIRST
docs/reports/           # m1_evaluation.md, m2_evaluation.md + graphs
prompts/                # the 5 per-member AI-tool prompts
scripts/                # presentation/misc utilities
tests/                  # cross-module tests (test_end_to_end.py, 17 tests)
```

## 4. Hard rules for agents

1. **Read `docs/contracts/data_schema.md` and `docs/contracts/module_interfaces.md` before writing code.** They define the exact CSV schema, the inter-module JSON message, score conventions, and every function signature.
2. **Ownership:** work only inside the target member's folder (+ the `backend/`/`frontend/`/`data/` paths listed in `prompts/memberN_*.txt`). Never edit another member's folder.
3. **Cross-module imports go through `integration/` adapters only** — never reach into another member's internals. Register implementations in `integration/pipeline.py::register_available_implementations()`.
4. **Schema changes:** propose in `docs/contracts/CHANGE_REQUESTS.md`, get approval, then update contract + code in one commit. Never silently change the schema. (CR **#1–#4 all APPROVED 2026-10-06**: #1 `physical:` config, #2 `temporal:` config, #3 §1 fused-row/streams/label semantics → `data_schema.md` §1.1, #4 `compute_trust` `observations` kwarg + `scores` return key → `module_interfaces.md`.)
5. **Score conventions (agreed by all, `data_schema.md` §3):**
   - `*_consistency` / `*_integrity` / `*_agreement`: 0–1, **higher = more trustworthy**
   - `anomaly_*`: 0–1, **higher = more anomalous**
   - `observation_trust`: **0–100**
6. Tunables live in `configs/settings.yaml` (additive sections per member: `physical:`, `temporal:`, …).
7. Model artifacts land in `models/` with the exact names from `data_schema.md` §4 (`isolation_forest.pkl`, `feature_scaler.pkl`, `temporal_model.pkl`, `network_model.pkl`, `trust_weights.json`, `fusion_config.json`). `*.pkl` is gitignored.
8. Keep a module README's "Status / integration notes" section current — that is how members communicate.

## 5. ✅ Current status — what is DONE

| Component | Status | Evidence |
|---|---|---|
| Repo scaffolding (README, contracts, config, prompts) | ✅ Done | `docs/contracts/*`, `configs/settings.yaml`, `prompts/*` |
| **M1 — physical module** | ✅ **Complete (code + eval)** | `member1_physical/src/` (loader, `extract_physical_features`, IsolationForest + OCSVM, `score_observation`, evaluate, fallback_data), 25 pytest tests, `docs/reports/m1_evaluation.md` + graphs, learned `models/physical/physical_limits.json` |
| **M2 — temporal/network module** | ✅ **Complete (code + eval + DoD verified)** | `member2_temporal/src/` (temporal + network features, IF + OCSVM, `score_observation`, evaluate, fallback_data), 44/44 pytest green, `docs/reports/m2_evaluation.md` + graphs, `models/temporal/*.pkl` regenerated & reload-verified, replay + network-anomaly detection semantically verified via `score_observation` |
| Integration adapters | ✅ M1–M5 wired | `integration/interfaces.py` + `pipeline.py` register **M1 + M2 + M3**; M5 `RealTrustService` calls them and persists to SQLite |
| M1/M2 retrained on M4 data | ✅ Done (2026-10-03) | M1: P 0.99 / FPR 0.3%; M2: P 0.87 / FPR 4.1% — family coverage documented in `member4_cyber/docs/threat_model.md` §4; open model-side item: window-mean dilution on 50%-interleaved replay (M1/M2 lever) |
| **M1/M2 retrained on REAL data** | ✅ Done (2026-10-04) | Real dataset: `scripts/convert_geolife.py` → `data/real/geolife.csv` (59,094 rows of real GeoLife GPS traces, 11 users, schema-validated) + live device captures `data/real/device_capture.csv`; both `train.py` `_clean_sources()` now prefer `data/real/` then M4/fallback (80/20 split per source). M1: P 0.988 / FPR 0.4%; M2 combined: P 1.000 / **FPR 0.000%** (was 2.6% — previous open item resolved); M3 headline unchanged (gnss_spoof F1=0.992) — see `docs/real_data.md` |
| **M3 — trust engine + fusion** | ✅ **Complete (code + eval + DoD verified)** | `member3_trust/src/` (`compute_trust` weighted-geometric evidence model + per-sensor attribution + §13 dynamic trust + §16-worded alerts; `fuse` trust-aware/normal + Kalman baseline), artifacts `models/trust/*.json` seeded, 34/34 pytest green, demo story 92.3 → 21.1 RED → 92.2 (7/7 checks), `docs/reports/m3_evaluation.md` robustness table (M4 data: gnss_spoof F1=0.992; mixed c05–c30 recall 0.50–0.72) |
| **M4 — cyber/data (datasets)** | ✅ **Complete (DoD verified)** | `data/synthetic/uav_normal_v1.parquet` (+3 support seeds, 24k rows) + 6 attack scenarios + mixed c05/c10/c20/c30 with exact §5 truth pairs — all pass `validate_dataset.py`; threat model `member4_cyber/docs/threat_model.md`; 15/15 pytest; reproducible from seed 42; per-sensor streams variant in `member4_cyber/scenarios/` (CR #3) |
| M1/M2 retrained on M4 data | ✅ Done (2026-10-03) | M1: P 0.99 / FPR 0.3%; M2: P 0.87 / FPR 4.1%; family coverage in `member4_cyber/docs/threat_model.md` §4; open model-side item: window-mean dilution on 50%-interleaved replay (M1/M2 lever) |
| Root pytest config | ✅ Done | `pytest.ini` (importlib mode) — M1+M2+M3+M4 suites collect together; repo-wide `py -m pytest -q` → **188 passed** (2026-10-09; was 175 before the LIVE-demo tests were added) |
| Interim results | ✅ Done (fallback data) | M1: precision 1.000, FPR 0%, spoof/malfunction/conflict recall 1.000 (replay only 0.367 → M2's job). M2 combined: precision 1.000, recall 1.000, FPR 0 — catches replay, telemetry manip, network anomaly. M3: detection F1 0.80–1.00 / FPR ≤ 0.036 across the corruption sweep; trust-aware fusion error 2.7–6.7 m vs normal 3.0–9.2 m |
| **M5 — backend + dashboard** | ✅ **Complete (code + tests)** | `backend/app/` (FastAPI, SQLAlchemy SQLite/PG, TrustService interface + Mock + Real, v1 REST, `/ws/live`); 17/17 backend pytest green; `frontend/` (Vite + React 18, Leaflet map, Recharts, gauge, sensor cards, evidence §15 wording, 8 scenario buttons, WS streaming); `member5_software/README.md` documents swap-in + run commands |
| Presentations | ✅ Done | `*.pptx` at repo root |
| **System audit (test/harden/document)** | ✅ **Done (2026-10-05)** | `docs/reports/system_audit.md`: root suite **152 passed** (M4 tests now in `pytest.ini`), `integration/run_demo.py` **16/16** incl. real M4 data section + byte-identical reruns, **fixed** hardcoded mock scenario playback/WS stream (H1), swallowed `observations` TypeError (H2), M1 model not reaching trust (H3), demo labels/checks (H4); new `tests/test_end_to_end.py` (17); CR #4 filed. Open items **all resolved 2026-10-07**: network-family trust sensitivity (primary-channel pull → network_anomaly F1 0.519→0.899), stale `lands_near_30` §22 expectation (reframed to §22 drop-through → demo 7/7), clean-phase IMU-drift artifact (epoch-aligned observations + speed damping) |
| **TRUSTBATTLE LIVE — judge demo** | ✅ **Done (2026-10-09)** | Controlled live simulation: `backend/app/services/live_demo.py` (input-only controller, seed 42, NORMAL/GNSS_SPOOF/REPLAY/TELEMETRY_MANIP/SENSOR_MALFUNCTION/RESET + RUN LIVE DEMO auto phases), REST `/api/v1/live/{status,scenario,auto,step,events,trajectory}`, `/ws/live` streams live frames + status frames; dashboard `LiveControl.jsx` (system status, pipeline panel, event log), map label "Simulated UAV Track — Controlled Live Simulation", "TRUST REDUCED BECAUSE" explainability block; `scripts/run_live_demo.py` prints real M3 values. Trust is NEVER hardcoded — controller changes input only; key fix: persistent in-place buffer frame so M3's IMU dead-reckoner diverges from the spoof (trust 92→42 AMBER, w_gnss 0.25→0.125, IMU stays 97). Root suite **188 passed** (13 new `tests/test_live_demo.py`) |
| **Release check + push (2026-10-09)** | ✅ **Done** | Full suite re-run on the current checkout: **188 passed** (exit 0). Backend `uvicorn backend.app.main:app --reload` from repo root → `/health` 200, `/docs` 200, no import errors; frontend `npm run dev` → `:5173` 200, no build/runtime errors, zero ECONNREFUSED; `/ws/live` delivers live trust frames **and** `live_status` frames (pipeline flags all ✓). Observed live arc (seed 42, API + terminal driver): NORMAL 93.8 GREEN / w_gnss 0.246 → SPOOF **40.8 AMBER** / w_gnss **0.123** (cross-agreement 0.88→0.35, IMU ~97) → RECOVERY 88.8–95.1 GREEN / w_gnss 0.250. §22 `demo_story` (64 msgs, source `pipeline`), Real Dataset replay (400 msgs, source `real_data`) and Live Device GPS (/real/ingest, /real/session, datasets device_capture + geolife) all still work. Pushed as `67c18c6`; `data/trustbattle.db` (runtime growth) and `docs/technical_concept_report.md` (untracked) deliberately **not** committed. No contract changed; no test weakened |
| **LIVE SENSOR INTEGRITY COMPARISON (2026-10-09, uncommitted)** | ✅ **Done** | New dashboard section beside the Real Dataset / Live Device GPS controls: real-device panel (permission/connection state, timestamp + freshness, coordinates, motion availability, honest `INSUFFICIENT DATA` until a full window), controlled-simulation panel (NORMAL/GNSS SPOOF/RECOVER → existing `/api/v1/live/*` pathway, computed trust/per-sensor trust/weights/evidence), 8-row real-vs-sim table with `NOT AVAILABLE`/`INSUFFICIENT DATA` + non-comparability caveat, and a computed-events timeline (`SIM ·` backend events / `REAL ·` real transitions). Backend additions are additive only: `GET /api/v1/real/status` + `source` validation on `/real/ingest` (simulated rows rejected 400 — server-side isolation, §5), and `RealDataSession.last_row()`. **Fixed:** rows with a MISSING timestamp were silently coerced to epoch-0 (1970) and accepted — now dropped as `coerce_rows` intended. Files: `SensorIntegrityComparison.jsx` (new), `deviceState.js` (new pure helpers), `DashboardPage.jsx`, `api.js`, `v1.py`, `real_data.py`; tests: `tests/test_sensor_integrity_comparison.py` (16) + `frontend/src/services/deviceState.test.mjs` (11, mocked permission states — real device hardware still unverified). Suite **204 passed** (exit 0); `npx vite build` exit 0; browser-verified via CDP (spoof click → 48.4 AMBER / w_gnss 0.143; real pathway → 88.3 GREEN / 13 evidence items; 0 JS exceptions; only pre-existing favicon 404). No contract change, no test weakened, no location/DB artifact added to git |
| **Pipeline self-check + mock-mode banner (2026-10-10)** | ✅ **Done (pushed `195e7a8`)** | New additive `GET /api/v1/pipeline/status`: runs M1→M2→M3 + fusion **for real** on a schema-valid window (`make_clean_track`) and reports `source: pipeline|mock`, `missing_modules`, `registered_adapters`, `self_check` and the interpreter path. Dashboard shows a green "✓ REAL PIPELINE verified" strip or a red "⚠ MOCK MODE" banner (resolves §6 item 3). Also fixed live-demo replay: stale rows addressed by **age** (`h[-ticks_ago]`) instead of an absolute cursor (broke after RESET / past the 4000-row cap), `_reset_track_locked()` now resets `_row` so RESET reproduces an identical trust sequence, and `reset()`/`auto()` cancel+join the auto-thread so no stray step lands afterwards. **Untracked `data/trustbattle.db`** (grew to 110.5 MB → GitHub GH001 rejected the push; rewritten the two unpushed commits with `hash-object` plumbing so the file on disk was never touched while the backend held it open, now in `.gitignore`). Suite **211 passed** (2× exit 0), 11 `node --test`, `vite build` OK, `/health` + `/api/v1/pipeline/status` live from `RealTrustService`. Backup branch `backup/pre-push-124930`. §6 items 4 (SQLite retention/double-write) and 5's `.git` size (~106 MB, history rewrite only) remain |
| **End-to-end demo (`integration/run_demo.py`)** | ✅ **Done (2026-10-03)** | Replays M4 spoof scenario → M1+M2 scores → M3 trust/fusion; **9/9 acceptance checks**: start trust 93.5 → min 5.0 RED → recovers 94.0; GNSS weight 0.249→0.017; peak per-sensor trust gnss 5 / imu 93 / visual 93.5 / net 95.8 |
| **M3 evaluation rerun on M4 mixed datasets** | ✅ **Done (2026-10-03)** | Fixed filename-matching bug in `member3_trust/src/evaluate.py` (`fallback_corruption_*` + `scenario_mixed_cXX`/`scenario_gnss_spoof`); `sensor_observations()` now dead-reckons IMU from accel integration so cross-sensor agreement catches well-built spoofs; gnss_spoof **F1=0.992**, mixed c05–c30 recall 0.50–0.72; §20 position errors N/A (no ground-truth position attrs) |
| **Model-side tuning (window aggregation)** | ✅ **Done (2026-10-03)** | mean→**p90** per window in M1 scorer + M2 scorer/calibration/eval — fixes window-mean dilution; `anomaly_physical` reaches 1.0 on replay windows; M2 replay recall still 0.050 (detection dominated by evidence checks — clock rewind, sequence continuity — not the IF model; documented trade-off); network anomaly + telemetry manipulation R=1.0; M2 clean FPR resolved → **0.000%** by the 2026-10-04 real retrain |
| **Real-data pipeline (dashboard)** | ✅ **Done (2026-10-04)** | `POST /api/v1/real/ingest` → 10-row batches through real M1→M2→M3, persisted to `data/real/device_capture.csv`; dashboard **Live Device GPS** (browser Geolocation+DeviceMotion) + **Real Dataset** (400 precomputed GeoLife predictions) buttons; retrain cmds + roadmap in `docs/real_data.md` |
| **Root cross-module tests** | ✅ **Done (updated 2026-10-09)** | `tests/test_end_to_end.py` (17 tests, system audit) + `tests/test_live_demo.py` (13 tests, TRUSTBATTLE LIVE), included in `pytest.ini` testpaths; verified `py -m pytest tests/ -q` → **36 passed** (2026-10-09, exit 0; was 17 on 2026-10-06) |
| **CR review #1–#4** | ✅ **Approved + applied (2026-10-06)** | All four `PROPOSED`→**APPROVED** in `docs/contracts/CHANGE_REQUESTS.md`; contracts updated: `data_schema.md` §1.1 (CR #3 fused rows / streams variant / window-level labels), `module_interfaces.md` (CR #4 `compute_trust(…, observations=None)` + `scores` return key); CR #1/#2 config sections and CR #4 code already shipped and re-verified |
| **M5 evaluation report** | ✅ **Done (2026-10-06)** | `docs/reports/m5_evaluation.md` — REST latency (5 endpoints × 200 req under load: p50 6–39 ms, p99 ≤ 325 ms), **30-min WS soak** (8015 frames, 0 errors, 224 ms avg interval, 2.3 s to first frame), backend RSS flat (ends 199.8 < starts 232.8 MB, max 288.8), browser JS-heap bounded sawtooth (max 75.7 MB, DOM stable, +5.7 MB/h trend **extrapolated** to 1 h — true 1 h soak not run, labeled in report); tooling in `member5_software/eval/` |
| **Trust development phase (13-step brief)** | ✅ **Done (2026-10-07)** | Steps 2–13: corroboration + primary-channel aggregation (`trust_engine.aggregation`, CR #5), M2 replay history context (`temporal.context_rows`=150 → freshness evidence fires across windows, 0.533→0.375), epoch-aligned observation model + speed damping (**resolved system-audit M3-open IMU-drift artifact**, clean gap 22.6→9.1 m), §13 recovery ramp, per-sensor trust + HIGH/MEDIUM/LOW evidence levels (dashboard chips), floor-normalized fusion weights; **experiment matrix `evaluation/results/trust_vs_baseline.csv` + `docs/reports/trust_vs_baseline.md` + `experiment_results.md`** with verified pre-change baseline (`trust_vs_baseline_before.csv`, captured by stashing): F1 improved 8/10 scenarios (network 0.519→0.899, conflict 0.696→0.800, mixed c10 0.230→0.359, c30 0.500→0.606), FPR down everywhere, clean fusion error 32.1→8.6 m; **demo mode** `POST /api/v1/demo/attack/demo_story` + dashboard “▶ Run §22 Demo” (verified live: 95→5 RED→84); demo `lands_near_30` reframed to §22 drop-through (**7/7**, system-audit M2-open resolved); M3 eval regenerated; 23 new tests (M3 47, M2 48, root 23) → **175 passed** |

**Known interim caveat (IMPORTANT UPDATE):** the M1/M2 "fallback data" caveat is RESOLVED as of 2026-10-03 (retrained on M4 datasets) and further superseded on 2026-10-04 — both modules now train on **real GPS data** (`data/real/geolife.csv` from Microsoft GeoLife + live device captures) with M4 clean data; models backup at `models/_backup_pre_real/`. M3's evaluation report uses M4's real attack datasets. Remaining M3 caveat: §20 position/velocity errors are N/A because M4 data has no ground-truth position attrs.

## 6. ⬜ What is REMAINING (priority order)

**No blockers — the project is competition-ready as of 2026-10-09.** No tracked feature work is open; the demo runs end-to-end on the real pipeline (§5).

**Non-blocking hardening backlog** (assessment 2026-10-09; none of these break a single 60–90 s demo — do these *after* the competition):

1. **Pin dependencies.** `requirements.txt` is all `>=` (pandas / fastapi / pydantic / scikit-learn) with **no CI**, so a fresh `pip install` can drift. Freeze the working set (`pip freeze > requirements.lock`) and add a ~40 s GitHub Actions job running `py -m pytest -q`.
2. **Run the stage backend without `--reload`** (`uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`): avoids the stale-reloader port-8000 footgun (§7) and the reloader's CPU overhead. Evaluators should also record the exact interpreter — the service warns to stderr when stages fail to register.
3. **Make mock-vs-pipeline visible in the UI.** If the uvicorn interpreter is missing pandas/sklearn, `RealTrustService` silently serves the labelled mock story. Expose `source: pipeline|mock` on `/health` + `/api/v1/live/status` and show a red banner when it is mock — for a trust project, silently scripted numbers are the worst failure mode.
4. **Single source of advance in live mode.** Each `/ws/live` connection calls `advance_playback("live")` → `LiveDemoController.step()`, so two browser tabs generate two windows and two DB rows per tick. Gate generation to one advancer; subscribers only read the latest message.
5. **Bound the SQLite write volume.** Measured 2026-10-09: **9,304 observations → 95.1 MB (~10 KB/obs), 298,049 evidence rows (~32/obs)**; `store_trust_message` is called from both `ws.py` (every streamed frame) and `v1.py` (every `/trust/current`), and `repository.py` has **no pruning**. A single demo adds only ~1–2 MB, so this is cumulative, not a stage risk — add retention (e.g. keep the last ~5k observations) and stop the double-write. ~~Untrack `data/trustbattle.db`~~ **done 2026-10-10** (`195e7a8`: untracked + `.gitignore`d after it hit GitHub's 100 MB limit). `.git` still carries the old 85–110 MB blobs in history — shrinking it needs a history rewrite (`git filter-repo`), only worth doing if clone size becomes a problem.
6. **Frontend tests (partially addressed 2026-10-09).** `deviceState.test.mjs` covers the comparison's permission/freshness logic via `node --test` (11 tests), but React components (`LiveControl.jsx`, `SensorIntegrityComparison.jsx`, `DashboardPage.jsx` mode switching / per-frame dedupe / `live_status` handling) are still only verified in the browser — add a vitest + Testing Library smoke test if time allows.
7. **Four copies of the same scoring sequence** (`trust_service._advance_pipeline`, `_build_trajectory`, `real_data._score_locked`, `live_demo.step`) will drift — consolidate into one `integration/` helper (refactor, not a bug fix).
8. **Demo-quality (optional, input-only):** spoof bottoms out at **AMBER ~41**, never RED — honest M3 dynamics for a capped 150 m ramp; a larger offset / longer ramp would legitimately cross RED without touching any score. Recovery can wobble one window (e.g. 66→51→71→88→95); a rolling-median *plot* (not a smoothed trust value) reads cleaner on a projector.
9. **Deeper live data (partially addressed 2026-10-09).** Missing-timestamp rows are now dropped explicitly (previously coerced to epoch-0) and asserted by `tests/test_sensor_integrity_comparison.py`; remaining: add a visible drop **counter** so Live Device GPS cannot look connected while silently discarding bad rows.
10. **Comparison-view gaps:** real-device state polls `/real/status` every 5 s (freshness label can lag); permission-denied/unavailable states are unit-tested (mocked) but never exercised on real hardware; a stale fix still shows `state: LIVE` until the next poll — freshness text marks it STALE; cosmetic pre-existing `/favicon.ico` 404 in the browser console.

> Older backlog ideas still valid: full 1 h browser soak + browser process-level memory, `trust/history` pagination for p99 < 100 ms, OpenSky ADS-B live feed, hardware IMU (see `docs/real_data.md`), mixed c20/c30 recovery-time tail + trust-aware fusion error on sensor_malfunction (see `experiment_results.md` limitations).

## 7. Commands (run from repo root)

```bash
pip install -r requirements.txt

# M1
python -m member1_physical.src.train        # trains + saves models/physical/*.pkl
python -m member1_physical.src.evaluate     # writes docs/reports/m1_evaluation.md
python -m pytest member1_physical/tests -q

# M2
python -m member2_temporal.src.train
python -m member2_temporal.src.evaluate
python -m pytest member2_temporal/tests -q

# Frontend pure-logic tests (Node built-in runner, no deps)
node --test frontend/src/services/deviceState.test.mjs

# End-to-end (needs M1+M2; trust stage degrades gracefully until M3 lands)
python integration/run_demo.py

# M5 — BOTH must run, from repo root (never from backend/ or frontend/)
uvicorn backend.app.main:app --reload       # :8000 — must run at repo root
cd frontend && npm install && npm run dev    # :5173 — proxies /api + /ws → :8000
```

> **M5 run gotchas (2026-10-06):**
> - Run uvicorn **at repo root**, not inside `backend/` — otherwise the spawned process dies with `ModuleNotFoundError: No module named 'backend'` (it also imports `integration/`, `member*_*/`).
> - If uvicorn's child crashes, the `--reload` **reloader parent can keep port 8000 bound (not listening)**: new instances fail with `Errno 10048`, while Vite logs endless `ws/http proxy error ECONNREFUSED`. Fix: `Ctrl+C` the stale PowerShell or `taskkill /PID <pid> /T /F` (check owner: `Get-NetTCPConnection -LocalPort 8000`).

Python 3.10+. Stack: pandas, numpy, scikit-learn, FastAPI, SQLAlchemy, React + Vite, Leaflet, Recharts, WebSocket.

## 8. Agent etiquette for this repo

- Integration starts **Day 1**: keep your slice wireable — exact contract signatures, register in `integration/pipeline.py`, commit often.
- Don't start with deep learning (Transformer/LSTM); baseline first (IsolationForest primary, One-Class SVM baseline) per `about_project.txt` §8–9.
- Update the module README "Status" section + this file's §5/§6 when a milestone lands.
- If a task touches contracts, follow §4 rule 4 before coding.
