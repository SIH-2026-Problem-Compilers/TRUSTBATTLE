# TRUSTBATTLE

**AI-Driven Battlefield Information Integrity & Trust Assessment Engine**

> Don't just ask what the battlefield sensors are reporting — ask whether the information they are reporting can be trusted.

**Flow:** Sensor Data → Analysis → Evidence → Trust Score → Trust-Aware Fusion → Dashboard

## Pipeline

```
M4 (attack/data) ──▶ M1 (physical) ──┐
                 └──▶ M2 (temporal) ──┼──▶ M3 (trust+fusion) ──▶ M5 (backend+dashboard)
```

| Module | Owner | Output |
|---|---|---|
| `member1_physical/` | Member 1 — AI/ML | Physical Consistency Score + Anomaly Score |
| `member2_temporal/` | Member 2 — AI/ML | Temporal Anomaly Score + Network Anomaly Score |
| `member3_trust/` | Member 3 — AI/ML | Observation Trust Score (0–100) + Sensor Weights + Final State Estimate |
| `member4_cyber/` | Member 4 — Cyber | Attack/Failure Scenarios + Synthetic Data + Ground Truth |
| `member5_software/` | Member 5 — Software | FastAPI backend + React real-time dashboard |

## Repo structure

```
TRUSTBATTLE/
├── member1_physical/        # M1: GNSS/IMU physics + anomaly detection
├── member2_temporal/        # M2: temporal + network telemetry analysis
├── member3_trust/           # M3: trust engine + trust-aware fusion
├── member4_cyber/           # M4: attack simulation + synthetic data
├── member5_software/        # M5: working notes for backend/dashboard
├── backend/                 # M5: FastAPI app
│   └── app/{api,core,models,services,db}
├── frontend/                # M5: React + Vite dashboard
│   └── src/{components,pages,services}
├── integration/             # shared adapters wiring M1+M2+M3+M5 together
├── data/
│   ├── raw/                 # public datasets (never modified)
│   ├── synthetic/           # M4 clean trajectories
│   ├── attacks/             # M4 attack scenarios + ground truth
│   └── processed/           # feature-engineered outputs (M1/M2)
├── models/                  # trained artifacts (physical/ temporal/ trust/)
├── docs/
│   ├── contracts/           # data_schema.md + module_interfaces.md — READ FIRST
│   └── reports/             # experiment reports & graphs
├── notebooks/               # exploration notebooks
├── configs/                 # shared YAML/JSON configs
├── scripts/                 # one-off utility scripts
├── tests/                   # cross-module tests
└── prompts/                 # the 5 team prompts (one per member)
```

## Rules (read before writing any code)

1. **Read `docs/contracts/data_schema.md` and `docs/contracts/module_interfaces.md` first.**
2. Work only inside your own `memberN_*/` folder (+ your `backend/`, `frontend/`, `data/` ownership).
3. Never edit another member's folder. Need something from them? Use the contract; need a change? Open a request in `docs/contracts/CHANGE_REQUESTS.md`.
4. Commit often. Integration starts Day 1, not at the end.
5. Everything uses **public datasets + controlled simulation** only.
6. The system assesses **trust/integrity** — it never claims "this sensor was hacked" without sufficient evidence (see `about_project.txt` §16).

## Prompts for AI tools

Each member uses their own prompt file from `prompts/` with any AI coding tool, **from inside this repo root**:

| File | Member |
|---|---|
| `prompts/member1_physical_analysis.txt` | M1 |
| `prompts/member2_temporal_analysis.txt` | M2 |
| `prompts/member3_trust_engine.txt` | M3 |
| `prompts/member4_cyber_simulation.txt` | M4 |
| `prompts/member5_backend_dashboard.txt` | M5 |

## Stack

Python 3.10+ · pandas · numpy · scikit-learn · FastAPI · React + Vite · Leaflet/Mapbox · Recharts/Plotly · WebSocket · PostgreSQL (or SQLite for dev)

## Quickstart (after modules exist)

```bash
pip install -r requirements.txt
python integration/run_demo.py        # end-to-end: data → trust → fusion
uvicorn backend.app.main:app --reload # backend on :8000
cd frontend && npm install && npm run dev
```
