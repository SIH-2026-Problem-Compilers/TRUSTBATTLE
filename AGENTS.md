# AGENTS.md — TRUSTBATTLE

> Context file for AI coding agents. Read this before touching any code.
> Last updated: 2026-10-03 (M3 complete)

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
tests/                  # cross-module tests (currently empty)
```

## 4. Hard rules for agents

1. **Read `docs/contracts/data_schema.md` and `docs/contracts/module_interfaces.md` before writing code.** They define the exact CSV schema, the inter-module JSON message, score conventions, and every function signature.
2. **Ownership:** work only inside the target member's folder (+ the `backend/`/`frontend/`/`data/` paths listed in `prompts/memberN_*.txt`). Never edit another member's folder.
3. **Cross-module imports go through `integration/` adapters only** — never reach into another member's internals. Register implementations in `integration/pipeline.py::register_available_implementations()`.
4. **Schema changes:** propose in `docs/contracts/CHANGE_REQUESTS.md`, get approval, then update contract + code in one commit. Never silently change the schema. (Existing open requests: #1 M1 `physical:` config section, #2 M2 `temporal:` config section — both additive.)
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
| Integration adapters | 🟡 Partial | `integration/interfaces.py` + `pipeline.py` register **M1 + M2 + M3**; M5 endpoints are still stubs |
| **M3 — trust engine + fusion** | ✅ **Complete (code + eval + DoD verified)** | `member3_trust/src/` (`compute_trust` weighted-geometric evidence model + per-sensor attribution + §13 dynamic trust + §16-worded alerts; `fuse` trust-aware/normal + Kalman baseline), artifacts `models/trust/*.json` seeded, 34/34 pytest green, demo story 92.3 → 21.1 RED → 92.2 (7/7 checks), `docs/reports/m3_evaluation.md` robustness table (trust-aware wins at 0/5/10/20/30% corruption) |
| Root pytest config | ✅ Done | `pytest.ini` (importlib mode) — M1+M2+M3 suites collect together; repo-wide `py -m pytest -q` → 103 passed |
| Interim results | ✅ Done (fallback data) | M1: precision 1.000, FPR 0%, spoof/malfunction/conflict recall 1.000 (replay only 0.367 → M2's job). M2 combined: precision 1.000, recall 1.000, FPR 0 — catches replay, telemetry manip, network anomaly. M3: detection F1 0.80–1.00 / FPR ≤ 0.036 across the corruption sweep; trust-aware fusion error 2.7–6.7 m vs normal 3.0–9.2 m |
| Presentations | ✅ Done | `*.pptx` at repo root |

**Known interim caveat (important):** M1/M2 numbers come from each module's own `fallback_data.py` generator because **M4's real datasets don't exist yet**. Both loaders already accept the real `scenario_*.parquet` + `*_ground_truth.csv` pairs and will need an unchanged rerun of `train` + `evaluate` once M4 delivers.

## 6. ⬜ What is REMAINING (priority order)

1. **M4 — member4_cyber (blocking everything):** empty except README. Need: synthetic UAV telemetry generator (`data/synthetic/uav_normal_v1.parquet`), attack scenario generators producing `data/attacks/scenario_*.parquet` + `scenario_*_ground_truth.csv` pairs (schema v1.0, labels 0–6), `member4_cyber/docs/threat_model.md`, tests. Attack parameters are pre-specified in `configs/settings.yaml` under `attacks:`.
2. **Rerun M1 + M2 + M3 train/evaluate on real M4 data** (same commands, no code change expected — M3's `eval_scenarios.load_scenarios()` already prefers `data/attacks/` pairs) and regenerate `docs/reports/`.
3. **M5 — backend:** `backend/app/` is empty. Need FastAPI app (`backend.app.main:app`) with contract endpoints: `GET /api/v1/trust/current`, `GET /api/v1/evidence/{observation_id}`, `GET /api/v1/alerts`, `WS /ws/live`; DB (SQLAlchemy, SQLite for dev / PostgreSQL for prod); wire M1+M2+M3 via `integration/`. M3 exposes `compute_trust(scores, history, observations=...)` + `fuse(...)` ready to call; the `observations` third arg feeds M3's derived cross-sensor evidence (§11) — pass per-sensor estimates when available.
4. **M5 — frontend:** `frontend/` is empty. Need React + Vite dashboard: map (Leaflet), sensor status, trust scores, anomaly scores, evidence explanation, alerts, trajectory comparison (normal vs trust-aware fusion).
5. **Experiments on real data (about_project.txt §19–20):** the M3 harness (`py -m member3_trust.src.evaluate`) already produces the corruption sweep + robustness table on fallback data; rerun on M4's scenarios.
6. **End-to-end demo (`integration/run_demo.py`):** the §22 story is implemented per-module (`py -m member3_trust.src.demo` passes all 7 acceptance checks); wire the same flow through `integration/run_demo.py` for the final demo.
7. **Root `tests/`:** cross-module/integration tests (currently empty; `pytest.ini` testpaths already include it).

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

# End-to-end (needs M1+M2; trust stage degrades gracefully until M3 lands)
python integration/run_demo.py

# M5 (once implemented)
uvicorn backend.app.main:app --reload       # :8000
cd frontend && npm install && npm run dev
```

Python 3.10+. Stack: pandas, numpy, scikit-learn, FastAPI, SQLAlchemy, React + Vite, Leaflet, Recharts, WebSocket.

## 8. Agent etiquette for this repo

- Integration starts **Day 1**: keep your slice wireable — exact contract signatures, register in `integration/pipeline.py`, commit often.
- Don't start with deep learning (Transformer/LSTM); baseline first (IsolationForest primary, One-Class SVM baseline) per `about_project.txt` §8–9.
- Update the module README "Status" section + this file's §5/§6 when a milestone lands.
- If a task touches contracts, follow §4 rule 4 before coding.
