# TRUSTBATTLE

**AI-Driven Battlefield Information Integrity & Trust Assessment Engine**

> *Don't just ask what the battlefield sensors are reporting — ask whether the information they are reporting can be trusted.*

TRUSTBATTLE is an **information-integrity layer** that sits *between* raw sensor data and sensor fusion. For every single observation it answers one question:

> **"Can we trust this particular sensor observation right now — and why?"**

It does **not** try to prove an attack happened, and it is **not** just another sensor-fusion system. It produces a dynamic, explainable **Observation Trust Score (0–100)** per observation, uses that score to make fusion resilient against corrupted data, and shows a human operator exactly *which* evidence drove the decision.

---

## Table of contents

1. [The problem](#1-the-problem)
2. [Why this matters (real-world motivation)](#2-why-this-matters-real-world-motivation)
3. [The core idea — an information-integrity layer](#3-the-core-idea--an-information-integrity-layer)
4. [The key design principle](#4-the-key-design-principle-sensor-reliability--observation-trust)
5. [How TRUSTBATTLE solves the problem](#5-how-trustbattle-solves-the-problem)
6. [System architecture](#6-system-architecture)
7. [A worked example](#7-a-worked-example)
8. [Attack & failure scenarios (MVP)](#8-attack--failure-scenarios-mvp)
9. [Experiments & evaluation](#9-experiments--evaluation)
10. [Results (interim)](#10-results-interim-fallback-data)
11. [Repository structure](#11-repository-structure)
12. [Getting started](#12-getting-started)
13. [Project status & roadmap](#13-project-status--roadmap)
14. [Ground rules](#14-ground-rules)
15. [Team](#15-team)

---

## 1. The problem

Modern military operations depend on many interconnected information sources — UAVs, GNSS/INS, radar, cameras, ground sensors and communication systems — to build a real-time picture of the battlefield.

The problem is simple to state and hard to solve:

> **Information coming from a sensor cannot always be assumed to be trustworthy.**

Information can become unreliable because of, among others:

- GNSS spoofing
- False-data injection
- Replay / stale data
- Communication / network anomalies
- Sensor malfunction
- Jamming / degraded signals
- Physical decoys & electronic deception
- Conflicting observations from different sensors

The dangerous part is that **a manipulated measurement can look completely legitimate**. A single sensor reporting in isolation gives no way to tell a real reading from a carefully crafted fake one.

For example, a UAV's GNSS says:

> *"I am at Location A."*

But its IMU, visual estimate and movement history all indicate:

> *"This position is physically inconsistent."*

A conventional fusion pipeline has no principled way to handle this: it blindly averages the sources, so a corrupted-but-confident GNSS stream can drag the final estimate away from the truth. The real question the system must answer is therefore not *"what did the sensor report?"* but:

> **"How much should we trust this information right now — and why?"**

---

## 2. Why this matters (real-world motivation)

This is not hypothetical:

- The **U.S. Army** runs an explicit *Ensuring Sensor Data Security and Integrity* program focused on protecting sensor data across its lifecycle. It has publicly discussed GPS spoofing producing incorrect position/timing and has tested systems to detect GNSS jamming/spoofing.
- **India's SANJAY Battlefield Surveillance System** integrates ground and aerial sensor inputs and processes them to confirm veracity before building a common surveillance picture.
- **GNSS spoofing has been demonstrated in real conflicts** (e.g. the Russia–Ukraine war), where false navigation information has been used against UAVs.
- Documented battlefield **decoys and electronic deception** can produce observations that are *technically valid* yet lead to a wrong operational interpretation.

The broad problem is:

> How can a system determine whether information received from a sensor or data source is trustworthy **before allowing it to significantly influence the operational picture**?

---

## 3. The core idea — an information-integrity layer

TRUSTBATTLE is not a replacement for sensor fusion, and not a standalone cyberattack detector. It is an **additional Information Integrity Layer on top of sensor systems**.

Instead of the usual flow:

```
Sensor ─▶ Data ─▶ Fusion ─▶ Decision
```

TRUSTBATTLE inserts an assessment stage:

```
Sensor ─▶ Data ─▶ Trust / Integrity Assessment ─▶ Fusion ─▶ Decision
```

Every observation is continuously evaluated using **multiple independent forms of evidence** — physical consistency, temporal behaviour, communication characteristics, historical reliability and cross-sensor agreement — before it is allowed to influence the fused picture.

The system sits *between* cybersecurity ("there is an attack") and plain sensor fusion ("combine the numbers"):

```
                        SENSOR DATA
                             │
                             ▼
                 ┌───────────────────────┐
                 │   INFORMATION         │
                 │   INTEGRITY LAYER     │
                 └───────────┬───────────┘
                             │
               Is this observation trustworthy?  ── and WHY?
                             │
             ┌───────────────┴───────────────┐
             ▼                               ▼
         TRUSTED                        SUSPICIOUS
             ▼                               ▼
     Robust Fusion                  Verification Alert
```

The central output is: **how much should the system trust this information right now, and why?**

---

## 4. The key design principle: sensor reliability ≠ observation trust

TRUSTBATTLE separates two things that are usually conflated:

| Concept | Question it answers | Nature |
|---|---|---|
| **Sensor reliability** | How reliable has this sensor/source *historically* been? | Slow-moving, per-sensor |
| **Observation trust** | How trustworthy is *this particular measurement right now*? | Dynamic, per-observation |

Example:

```
Drone GNSS historical reliability = 94 %      (the source is usually good)
Current observation:
  • GNSS / IMU conflict
  • GNSS / visual conflict
  • Telemetry anomaly
Current observation trust        = 31 %       (this reading is not)
```

**A normally reliable sensor can temporarily produce an unreliable observation.** This distinction is central to the whole system: we never permanently blacklist a source — trust drops during an anomaly and gradually recovers afterwards.

---

## 5. How TRUSTBATTLE solves the problem

The solution is a **multi-evidence, dynamic, explainable trust assessment** built in six layers, each owned by one team member and wired through a shared contract.

| Layer | Name | What it does | Module |
|---|---|---|---|
| **1** | Physics / consistency analysis | Position/velocity residuals, acceleration & heading consistency, trajectory deviation, timestamp consistency, GNSS-vs-IMU disagreement | M1 |
| **2** | ML anomaly detection | Learns "normal" physical behaviour (IsolationForest primary, One-Class SVM baseline) and scores deviation | M1 |
| **3** | Temporal analysis | Replay / stale data, timestamp & sequence irregularities, sampling regularity | M2 |
| **4** | Cyber / network analysis | Packet rate, inter-arrival delay, loss and burst behaviour (§ "950 ms vs 20 ms" signature) | M2 |
| **5** | Cross-sensor consistency | Compares independent sources and reports agreement — *"something about this observation is inconsistent"* | M3 (derived) |
| **6** | Observation trust engine | Fuses all evidence + historical reliability into **Observation Trust 0–100**, dynamic over time, with per-sensor attribution | M3 |

Then two capabilities complete the loop:

- **Trust-aware fusion** — fusion weights follow *current observation trust*, so when one source becomes unreliable its influence is reduced instead of letting it dominate the estimate.
- **Explainable dashboard** — every alert shows the score, the evidence list, the possible causes (hypotheses only) and the recommended action.

**Why a hybrid AI + physics + cybersecurity approach (not one giant deep model):** physics/consistency checks are interpretable and produce the *evidence*; ML anomaly models catch subtle learned deviations; the trust engine combines everything into one calibrated, dynamic, explainable score. Every alert stays justified by evidence rather than a black-box number.

### 5.1 Dynamic trust

Trust is never permanent. A typical spoofing episode:

```
Normal:            95 %
Spoofing begins:   95 → 81 → 63 → 41 → 24   ⚠️ INFORMATION INTEGRITY ALERT
Anomaly ends:      24 → 38 → 61 → 79 → 92   (gradual recovery)
```

Dropping is fast; recovery is gradual. This prevents a permanent blacklist after one anomaly.

### 5.2 Robust fusion — normal vs trust-aware

```
Normal fusion                         Trust-aware fusion (this project)
GNSS 33 %  IMU 33 %  Visual 33 %      GNSS 10 %  IMU 45 %  Visual 45 %
(equal influence)                     (influence follows current observation trust)
```

The goal: when one information source becomes unreliable, the system must reduce its influence instead of allowing the corrupted information to dominate the final estimate. The actual weights are produced by the model and evaluated experimentally (§9).

### 5.3 Explainability

The dashboard never shows only *"anomaly = 96 %"*. It shows an **INFORMATION INTEGRITY ALERT** with:

```
Observation Trust: 28 %
Evidence:                       Possible causes:
  ✓ Historical reliability HIGH   • GNSS spoofing
  ✗ GNSS/IMU disagreement         • sensor malfunction
  ✗ Trajectory inconsistency      • communication manipulation
  ✗ Cross-sensor disagreement   Recommended action:
  ✗ Network timing anomaly        Independent verification required.
```
---

## 6. System architecture

```
                     ┌──────────────────────────┐
                     │     Battlefield Sources  │
                     │  GNSS │ IMU │ Visual │ Net│
                     └────────────┬─────────────┘
                                  ▼
                        Feature Extraction
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
 Physics/State            Temporal ML              Cyber/Network
 Consistency              Anomaly                  Anomaly
   (M1)                     (M2)                     (M2)
        └─────────────────────────┼─────────────────────────┘
                                  ▼
                          Evidence Engine ──▶ Observation Trust Model (M3)
                                                      │
                                      ┌───────────────┴───────────────┐
                                      ▼                               ▼
                                 TRUSTWORTHY                     SUSPICIOUS
                                      ▼                               ▼
                              Robust Fusion                  Verification Alert
                                      └───────────────┬───────────────┘
                                                      ▼
                                          Explainable Dashboard (M5)
```

### Module ownership (5-member pipeline)

| Module | Folder | Owner role | Contract output |
|---|---|---|---|
| **M1** — Physical & Sensor Analysis | `member1_physical/` | AI/ML | `physical_consistency`, `anomaly_physical` + evidence |
| **M2** — Temporal & Telemetry/Network | `member2_temporal/` | AI/ML | `temporal_consistency`, `anomaly_temporal`, `network_integrity` + evidence |
| **M3** — Trust Engine & Fusion | `member3_trust/` | AI/ML | `observation_trust` (0–100), `sensor_weights`, `state_estimate` |
| **M4** — Threat & Attack Simulation | `member4_cyber/` | Cyber | Attack/failure scenarios + synthetic data + ground truth |
| **M5** — Backend & Dashboard | `backend/`, `frontend/`, `member5_software/` | Software | FastAPI + React real-time dashboard |

**End-to-end flow (the demo story):**
`Normal data → attack injection → evidence → trust drops → suspicious source down-weighted → system continues on reliable sources → recovery → trust recovers.`

### Score conventions (agreed by all — `docs/contracts/data_schema.md` §3)

- `*_consistency` / `*_integrity` / `*_agreement`: **0–1, higher = more trustworthy**
- `anomaly_*`: **0–1, higher = more anomalous**
- `observation_trust`: **0–100**

---

## 7. A worked example

Suppose a UAV carries GNSS, IMU, a visual/position estimate and network telemetry:

- **GNSS** reports `Position = X`
- **IMU** reports movement that does *not* support the GNSS trajectory
- **Camera / visual system** reports an environment that does not match the location
- **Network telemetry** shows abnormal timing / communication behaviour
- **Historical reliability** says the GNSS receiver has normally been reliable

Instead of shouting *"GPS is hacked"*, TRUSTBATTLE outputs:

```
⚠  OBSERVATION INTEGRITY ALERT
Observation Trust: 28 %

Evidence:
  ✓ Sensor historically reliable
  ✗ GNSS/IMU disagreement
  ✗ Trajectory inconsistency
  ✗ Visual/location disagreement
  ✗ Telemetry anomaly

Assessment:  Current observation is potentially unreliable.
Possible causes:  GNSS spoofing · sensor malfunction · communication manipulation
Action:  Reduce the influence of this observation and request independent verification.
```

The independent sources keep their high trust, the suspect source collapses, and fusion re-weights automatically.

---

## 8. Attack & failure scenarios (MVP)

The first prototype deliberately keeps the scope focused on **UAV navigation / information integrity** rather than trying to simulate an entire battlefield.

**Sensors:** GNSS · IMU · simulated visual/position estimate · telemetry/network metadata.

**Scenarios (ground-truth label in `data_schema.md` §1):**

| Label | Scenario | Primary detecting layer |
|---|---|---|
| 0 | Normal operation | — |
| 1 | GNSS spoofing | Physics (M1) |
| 2 | Replay / stale data | Temporal (M2) |
| 3 | Telemetry manipulation | Temporal (M2) |
| 4 | Network anomaly | Network (M2) |
| 5 | Sensor malfunction | Physics (M1) |
| 6 | Cross-sensor conflict | Physics + Trust (M1/M3) |

Attack parameters are pre-specified in `configs/settings.yaml` under `attacks:` (spoof offset/ramp, replay delay, packet-delay spike & loss). **Everything uses public datasets + controlled simulation only** — no classified or real military data.

---

## 9. Experiments & evaluation

The research hypothesis is tested experimentally, not asserted:

> *A multi-evidence observation-integrity model combining physical consistency, temporal behaviour, communication characteristics, historical reliability and cross-sensor agreement can identify unreliable sensor observations and reduce the impact of corrupted information on situational estimation compared with conventional sensor fusion.*

### Experiment design

Inject a controlled percentage of corrupted observations and, at each level, compare **Normal fusion (baseline)** vs **Trust-aware fusion (ours)**:

```
Corruption:   0 %   5 %   10 %   20 %   30 %
              │     │      │      │      │
              ▼     ▼      ▼      ▼      ▼
        Normal fusion  vs  Trust-aware fusion  → position / velocity error
```

### Metrics

- **Anomaly detection:** precision, recall, F1-score, false-positive rate, detection latency
- **State estimation:** position error, velocity error, trajectory error
- **Resilience:** how gracefully the final estimate degrades as the corrupted fraction rises

---

## 10. Results (interim, fallback data)

> ⚠️ **Data caveat:** the numbers below are produced from each module's clearly-marked `fallback_data.py` / `eval_scenarios.py` generator because **M4's real datasets do not exist yet**. Both loaders already accept the real `data/attacks/scenario_*.parquet` + `*_ground_truth.csv` pairs and will be re-run **unchanged** once M4 delivers. Full reports live in `docs/reports/`.

### M1 — Physical & sensor analysis (`docs/reports/m1_evaluation.md`)

| Model | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| IsolationForest (primary) | 1.000 | 0.862 | 0.926 | 0.000 |
| One-Class SVM (baseline) | 0.979 | 0.993 | 0.986 | 0.011 |

- Spoof / malfunction / cross-sensor-conflict recall **1.000**, each detected within one 5 s window.
- **Replay is only partially visible to physics (recall 0.367) — by design:** a stale navigation solution on a straight, steady track is physically indistinguishable from live data. That residual is Member 2's job.

### M2 — Temporal & telemetry/network (`docs/reports/m2_evaluation.md`)

| Detector | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| Temporal IsolationForest | 1.000 | 0.696 | 0.821 | 0.000 |
| Network IsolationForest | 1.000 | 0.674 | 0.805 | 0.000 |
| **Combined (temporal ∪ network)** | **1.000** | **1.000** | **1.000** | **0.000** |

- Catch replay via re-broadcast sequence numbers + frozen-clock stale age → **closes M1's replay gap**.
- Catch network anomalies via `~950 ms` inter-arrival spikes vs `~20 ms` normal + catch-up bursts, loss and rate drop.

### M3 — Trust engine & trust-aware fusion (`docs/reports/m3_evaluation.md`)

**Final-demo story (§22):** trust **92.3 → 21.1 (RED) → 92.2**, all 7 acceptance checks pass. At attack peak per-sensor trust is `gnss 21 · imu 97 · visual 95 · net 98` and the GNSS fusion weight falls **0.252 → 0.068**.

Detection vs corruption:

| Corruption % | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| 0 | 1.000 | 1.000 | 1.000 | 0.000 |
| 5 | 1.000 | 1.000 | 1.000 | 0.000 |
| 10 | 0.667 | 1.000 | 0.800 | 0.033 |
| 20 | 0.800 | 1.000 | 0.889 | 0.036 |
| 30 | 1.000 | 0.833 | 0.909 | 0.000 |

Robustness — **trust-aware fusion wins at every corruption level**:

| Corruption % | Normal pos err (m) | Trust-aware pos err (m) | Improvement |
|---|---|---|---|
| 0 | 1.7 | 1.7 | — |
| 5 | 3.0 | 2.7 | 10 % |
| 10 | 4.3 | 3.6 | 16 % |
| 20 | 6.8 | 5.1 | 24 % |
| 30 | 9.2 | 6.7 | **27 %** |

The larger the corrupted fraction, the more the trust-aware layer helps — exactly the resilience argument the project set out to demonstrate.

---

## 11. Repository structure

```
TRUSTBATTLE/
├── member1_physical/        # M1: GNSS/IMU physics + anomaly detection
├── member2_temporal/        # M2: temporal + network telemetry analysis
├── member3_trust/           # M3: trust engine + trust-aware fusion
├── member4_cyber/           # M4: attack simulation + synthetic data
├── member5_software/        # M5: working notes for backend/dashboard
├── backend/                 # M5: FastAPI app  (app/{api,core,models,services,db})
├── frontend/                # M5: React + Vite dashboard  (src/{components,pages,services})
├── integration/             # ONLY cross-module wiring: interfaces.py, pipeline.py, run_demo.py
├── data/
│   ├── raw/                 # public datasets (never modified; gitignored)
│   ├── synthetic/           # M4 clean trajectories
│   ├── attacks/             # M4 scenario_*.parquet + *_ground_truth.csv pairs
│   └── processed/           # feature outputs written by M1/M2
├── models/                  # trained artifacts: physical/ temporal/ trust/ (*.pkl gitignored)
├── docs/
│   ├── contracts/           # data_schema.md + module_interfaces.md — READ FIRST
│   └── reports/             # m1/m2/m3 evaluation reports + graphs
├── configs/settings.yaml    # shared config — all tunables live here
├── prompts/                 # the 5 per-member AI-tool prompts
├── scripts/                 # presentation / misc utilities
├── notebooks/               # exploration
├── tests/                   # cross-module tests
└── pytest.ini               # shared pytest config (importlib mode)
```

---

## 12. Getting started

Requires **Python 3.10+** (and Node for the frontend, once M5 lands).

```bash
pip install -r requirements.txt

# M1 — physical & sensor analysis
py -m member1_physical.src.train       # trains + calibrates + saves models/physical/*.pkl
py -m member1_physical.src.evaluate    # writes docs/reports/m1_evaluation.md + graphs
py -m pytest member1_physical/tests -q

# M2 — temporal & telemetry/network
py -m member2_temporal.src.train
py -m member2_temporal.src.evaluate
py -m pytest member2_temporal/tests -q

# M3 — trust engine & fusion
py -m member3_trust.src.train          # (re)seed models/trust/*.json
py -m member3_trust.src.demo           # §22 story; exit 0 iff all 7 checks pass
py -m member3_trust.src.evaluate       # corruption sweep -> m3_evaluation.md + graphs
py -m pytest member3_trust/tests -q

# Whole repo test suite
py -m pytest -q                         # currently 152 passed (incl. M4 + cross-module tests)

# End-to-end (M4 data -> M1+M2 -> M3 -> fusion; 16/16 acceptance checks)
python integration/run_demo.py

# M5 (once implemented)
uvicorn backend.app.main:app --reload   # backend on :8000
cd frontend && npm install && npm run dev
```

> `models/**/*.pkl` are gitignored — regenerate them locally by running the `train` entry points after cloning.

**Stack:** Python · pandas · numpy · scikit-learn · FastAPI · SQLAlchemy · React + Vite · Leaflet · Recharts · WebSocket · SQLite (dev) / PostgreSQL (prod).

---

## 13. Project status & roadmap

### ✅ Done

- Repo scaffolding: contracts (`data_schema.md`, `module_interfaces.md`), shared config, prompts.
- **M1** — physical module: loader, physics features, IsolationForest + OCSVM, scoring, evaluation, 25 tests, `m1_evaluation.md`.
- **M2** — temporal/network module: temporal + network features, IF + OCSVM, scoring, evaluation, 44 tests, `m2_evaluation.md`.
- **M3** — trust engine + fusion: weighted-geometric evidence model, per-sensor attribution, dynamic trust, trust-aware & Kalman fusion, demo (7/7 checks), 34 tests, `m3_evaluation.md`.
- Integration adapters register **M1 + M2 + M3**; root `pytest.ini` unifies all suites (103 passed).

### ⬜ Remaining (priority order)

1. **M4 — attack/data simulation (blocking everything):** synthetic UAV telemetry generator, the seven attack/failure scenarios + ground-truth pairs (schema v1.0), threat model, tests.
2. **Re-run M1 + M2 + M3 train/evaluate on real M4 data** (same commands, no code change expected) and regenerate reports.
3. **M5 — backend:** FastAPI app (`backend.app.main:app`) with `GET /api/v1/trust/current`, `GET /api/v1/evidence/{observation_id}`, `GET /api/v1/alerts`, `WS /ws/live`, plus DB.
4. **M5 — frontend:** React + Vite dashboard — Leaflet map, sensor status, trust/anomaly scores, evidence explanation, alerts, trajectory comparison.
5. **Experiments on real data** and the **end-to-end demo** through `integration/run_demo.py`.
6. **Root `tests/`:** cross-module integration tests.

### Future expansion

`V1` GNSS + IMU + telemetry → `V2` + camera/EO → `V3` + radar simulation → `V4` multi-UAV/multi-agent → `V5` edge deployment + hardware sensor integration.

---

## 14. Ground rules

**What we can honestly claim.**

- ❌ We do **not** claim the AI can prove an attack, identify attackers, or that any specific army's sensors are being hacked.
- ✅ We **do** claim sensor-information integrity is a documented requirement; that GNSS spoofing/jamming and battlefield deception are real; that existing systems address portions of the problem; and that our project investigates an **explainable observation-level information-integrity layer** combining physical, temporal, cyber and cross-sensor evidence.

**Therefore the system assesses *trust/integrity* — it never says "this sensor was hacked" without sufficient evidence.** It says *"the observation is inconsistent / unreliable, with evidence potentially consistent with spoofing, malfunction or communication manipulation."* It is an **information-integrity assessment system, not an attack-attribution system.**

**Engineering rules:**

1. Read `docs/contracts/data_schema.md` and `docs/contracts/module_interfaces.md` before writing code.
2. Work only inside your own `memberN_*/` folder. Never edit another member's folder.
3. Cross-module imports go through `integration/` adapters only.
4. Schema changes → propose in `docs/contracts/CHANGE_REQUESTS.md` first, then update contract + code in one commit.
5. Keep the module README "Status / integration notes" current.
6. Everything uses **public datasets + controlled simulation** only.

---

## 15. Team

| Member | Role | Deliverable |
|---|---|---|
| Member 1 | AI/ML — Physical & sensor analysis | Physical consistency + anomaly scores |
| Member 2 | AI/ML — Temporal & telemetry analysis | Temporal + network anomaly scores |
| Member 3 | AI/ML — Trust engine & fusion | Observation trust + sensor weights + state estimate |
| Member 4 | Cybersecurity — Threat & attack simulation | Scenarios + synthetic data + ground truth |
| Member 5 | Software — Backend & dashboard | Working web app + real-time dashboard |

---

*Full concept & design rationale: `about_project.txt` · work split: `project_distribution.md` · agent context: `AGENTS.md`.*