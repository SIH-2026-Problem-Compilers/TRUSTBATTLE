# TRUSTBATTLE — Detailed Technical Concept Report

> **Purpose:** answer every technical question you can be asked about this project —
> where the data comes from, how it is cleaned, what the features are, which
> algorithms are used and *why*, how the model pipeline works, what the tech
> stack is, how everything is evaluated and tested.
>
> Every number in this report is either quoted from a file in this repo or
> reproducible with the commands shown. Nothing is invented. Status: 2026-10-08.

---

## Table of contents

1. [Project & problem framing](#1-project--problem-framing)
2. [Data: where it comes from](#2-data-where-it-comes-from)
3. [Data schema & labels](#3-data-schema--labels)
4. [Data cleaning & preprocessing](#4-data-cleaning--preprocessing)
5. [Feature engineering (what the models actually see)](#5-feature-engineering-what-the-models-actually-see)
6. [Algorithms: which, and why](#6-algorithms-which-and-why)
7. [Model training pipeline](#7-model-training-pipeline)
8. [Trust engine (M3) — the core scoring math](#8-trust-engine-m3--the-core-scoring-math)
9. [Fusion (state estimation)](#9-fusion-state-estimation)
10. [End-to-end system pipeline](#10-end-to-end-system-pipeline)
11. [Tech stack (full)](#11-tech-stack-full)
12. [Backend API & real-time layer](#12-backend-api--real-time-layer)
13. [Frontend dashboard](#13-frontend-dashboard)
14. [Evaluation: metrics & results](#14-evaluation-metrics--results)
15. [Testing & quality assurance](#15-testing--quality-assurance)
16. [Reproducibility & experiment protocol](#16-reproducibility--experiment-protocol)
17. [Explainability & domain rules](#17-explainability--domain-rules)
18. [Limitations (say these before anyone asks)](#18-limitations-say-these-before-anyone-asks)
19. [Quick reference: commands, artifacts, file map](#19-quick-reference-commands-artifacts-file-map)
20. [Persistence & database](#20-persistence--database)
21. [WebSocket protocol details](#21-websocket-protocol-details)
22. [Configuration, security & failure handling](#22-configuration-security--failure-handling)

---

## 1. Project & problem framing

### Q1. What is TRUSTBATTLE in one sentence?
An **AI-driven information-integrity and trust assessment engine**: given a stream
of UAV sensor observations, it answers *"Can we trust this particular observation
**right now** — and why?"* and produces a 0–100 trust score, per-sensor trust, a
fused position estimate, evidence, possible causes, and a recommended action.

### Q2. How is it different from a normal anomaly/attack detector?
Three differences:

1. **It is an integrity-assessment system, not an attack-attribution system.**
   It never says "this sensor was hacked"; it says observations are
   *"inconsistent / unreliable, potentially consistent with spoofing or
   malfunction"* (§16 wording rule, enforced in `trust_engine._CAUSES` and tests).
2. **Two distinct concepts are kept apart:** *sensor reliability* (historical,
   e.g. 94%) vs *observation trust* (this measurement right now, e.g. 31%).
3. **Trust is dynamic** — it drops fast during an attack and recovers gradually
   afterwards (§13), instead of flipping binary on/off.

### Q3. What is the pipeline in one line?
```
Sensor Data → M1 physical analysis ┐
              M2 temporal analysis ┼→ M3 trust + fusion → M5 backend + dashboard
              (M4 provides data)   ┘
```
M4 (cyber) generates data + ground truth; M1/M2 produce evidence scores; M3
combines them into trust and fuses the state; M5 serves it over REST/WebSocket
to a React dashboard.

### Q4. What is the MVP scenario?
UAV navigation integrity: GNSS + IMU + visual estimate + telemetry/network
metadata, with attack families: **normal / GNSS spoofing / replay-stale /
telemetry manipulation / network anomaly / sensor malfunction / cross-sensor
conflict** (plus mixed-corruption datasets at 5/10/20/30%).

---

## 2. Data: where it comes from

### Q5. What datasets feed this project?
Three tiers, in priority order (documented in `docs/real_data.md` §1):

| # | Source | What is real | Size / content | Where it lands |
|---|---|---|---|---|
| 1 | **Microsoft GeoLife GPS Trajectories 1.3** (Microsoft Research Asia, 182 users, phone GPS traces 2007–2012) | Real GNSS fixes (lat/lon/alt/timestamps) | 59,094 rows, 11+ users selected round-robin, converted from `data/raw/geolife.zip` | `data/real/geolife.csv` — **training set** + dashboard replay |
| 2 | **Live device capture** (browser Geolocation API + DeviceMotion) | Real phone GPS fixes and, when granted, measured accelerometer/gyro | Streams in batches of 10 rows via `POST /api/v1/real/ingest` | `data/real/device_capture.csv` (gitignored) |
| 3 | **M4 synthetic scenarios** (controlled simulation, seed 42) | Simulated attacks **with ground truth** | `uav_normal_v1.parquet` + 3 support seeds (24k rows), 6 single-attack scenarios, 4 mixed-corruption datasets | `data/synthetic/`, `data/attacks/` — evaluation + demo |

Plus clearly-marked **fallback generators** (`member1_physical/src/fallback_data.py`,
`member2_temporal/src/fallback_data.py`) that exist only so the pipeline runs
before any dataset lands — they are never silently mixed into published numbers
(every report states which source produced it).

### Q6. Why GeoLife? Is the data public and legal?
Yes — GeoLife is a **public academic dataset** published by Microsoft Research
for GPS-trajectory research. The project brief mandates *public datasets +
controlled simulation only* (no classified/real military data), and GeoLife
satisfies that: real-world phone GPS traces with no sensitive content.

### Q7. GeoLife is GNSS-only — where do IMU and network columns come from?
Honest answer, documented in `scripts/convert_geolife.py` and `docs/real_data.md`:

- `velocity`, `heading` → **derived** from consecutive real fixes (bearing + speed).
- `accel_x/y` → d(velocity)/dt in ENU, clipped ±30 m/s²; `gyro_z` → d(heading)/dt, clipped ±3 rad/s.
- `accel_z`, `gyro_x`, `gyro_y` = **0.0** (no accelerometer in the dataset — never faked).
- `packet_rate`, `packet_delay_ms`, `packet_loss` → the **real sampling cadence** (1/dt, inter-fix delay, >10 s gap fraction) — a cadence channel, not real packet telemetry.
- `gnss_quality` = 1.0 (raw traces publish no accuracy field).
- `label` = 0, `attack_start` = 0 — it is **clean real data, the detectors' TRAIN set**.

Live phone captures are different: when the user grants motion permission the
accelerometer/gyro are **measured**, not derived.

### Q8. How is the synthetic (M4) data generated?
`member4_cyber/src/build_datasets.py` in one deterministic run (seed 42):

- `make_clean_dataset()` simulates a 600 s UAV track at 10 Hz with GNSS noise
  (σ 3 m), IMU noise, visual updates at 5 Hz — settings from `configs/settings.yaml`
  (`simulation:`, `sensors:`, `attacks:`).
- `attack_simulator` injects the 6 attack families with calibrated magnitudes,
  e.g. GNSS spoof offset starts at 540 m reached via a 30 s ramp
  (18 m/s velocity divergence, `settings.yaml attacks.gnss_spoof`), replay delay
  12 s (= 121 ticks @10 Hz), network delay spike 900 ms + 25% packet loss.
- Each attack file is written as a **pair**: `scenario_x.parquet` +
  `scenario_x_ground_truth.csv` (`timestamp, sensor_id, label, attack_start`).
- Re-running the builder produces **byte-identical** datasets (verified in
  `docs/reports/system_audit.md` §8); `validate_dataset.py` gates every file
  (`docs/reports/m4_dataset_reports.md`: all 14 datasets ✅ VALID).

### Q9. What about data for live demos without any dataset?
`integration/run_demo.py` replays an M4 spoof scenario through the real
M1→M2→M3 pipeline with 9/9 acceptance checks (trust 93.5 → 5.0 RED → 94.0
recovered). The backend additionally has a clearly-labelled `MockTrustService`
demo story (92 → ~18 RED → 93) that is only used when the real pipeline cannot
import.

---

## 3. Data schema & labels

### Q10. What does one row of data look like?
`docs/contracts/data_schema.md` §1 — 23 columns, one row = one observation:

| Group | Fields (unit) |
|---|---|
| Time/identity | `timestamp` (epoch s), `sensor_id`, `sequence_number` |
| Position | `latitude`, `longitude`, `altitude` (deg/deg/m) |
| Velocity | `velocity`, `vx`, `vy`, `vz` (m/s) |
| IMU | `accel_x/y/z` (m/s²), `gyro_x/y/z` (rad/s) |
| Attitude | `heading` (deg), `gnss_quality` (0–1) |
| Network | `packet_rate` (pkt/s), `packet_delay_ms`, `packet_loss` (0–1) |
| Truth | `label` (0–6), `attack_start` (0/1) |

### Q11. What do the labels mean?
`0 = normal, 1 = gnss_spoof, 2 = replay, 3 = telemetry_manip, 4 = network_anomaly,
5 = sensor_malfunction, 6 = cross_sensor_conflict`.

Per **CR #3 (approved)**: `label` and `attack_start` are **window-level marks** —
every row inside an injected attack window carries `attack_start=1` and the
scenario label; rows outside carry 0. Ground-truth CSVs use the same convention.

### Q12. What is the inter-module message format?
A JSON object (schema §2) with blocks: `scores` (6 floats), `evidence[]`
(`check`, `pass`, `detail`, `level`), `trust` (`observation_trust` 0–100,
`sensor_reliability`, `sensor_weights`, `state_estimate`), `alert`
(`level`, `message`, `possible_causes`, `recommended_action`).

**Score conventions (§3, agreed by all):**
- `*_consistency / *_integrity / *_agreement`: **0–1, higher = more trustworthy**
- `anomaly_*`: **0–1, higher = more anomalous**
- `observation_trust`: **0–100**

### Q13. Can the schema be changed freely?
No. Rule 4 of `AGENTS.md`: propose in `docs/contracts/CHANGE_REQUESTS.md`,
get approval, then update contract + code together. CR #1–#5 are the ones that
exist; nothing changes silently.

---

## 4. Data cleaning & preprocessing

### Q14. How is GeoLife cleaned? (`scripts/convert_geolife.py`)
Ordered steps, each with a stated reason:

1. **Parse** `.plt` files (6 header lines, then lat/lon/alt/date/time); malformed lines skipped.
2. **Trace-level filters:** drop traces with < 600 points (too few boundaries),
   median dt > 8 s (ultra-sparse), all-zero coordinates (null island).
3. **Diversity selection:** round-robin over the 182 users, ≤ 4000 rows/user,
   up to 6 laps, until `--target-rows` (60 000) — so no single user dominates.
4. **Global timestamp sort**, then **segment cuts** at trajectory change,
   non-increasing dt, or gap > 60 s — derivatives never span a cut.
5. **Gap-aware derivatives:** speed clipped 0–70 m/s, accel clipped ±30 m/s²,
   gyro_z clipped ±3 rad/s, heading wrap-aware ((dh+180)%360−180).
6. **Boundary trim:** first 10 rows after every cut are dropped so no fabricated
   jump ever lands in training data.
7. **Schema gate:** the output is re-loaded through
   `member1_physical.src.data_loader.load_data()` — the converter *refuses to
   ship* a file the loaders would reject, and prints duration/speed/accel sanity stats.

### Q15. How is data split for training?
**80/20 per source, before feature extraction** (`_clean_sources()` in both
M1/M2 `train.py`). Why before: rolling windows (21 samples) must never span two
sources, and the model must be calibrated on rows it never saw. The 20% holdout
is used **only** for threshold calibration, never for fitting.

### Q16. How are missing/invalid values handled in features?
At the end of both feature extractors:
`replace([inf, -inf], 0.0).fillna(0.0)` — every feature column is guaranteed
finite (asserted by tests: `np.isfinite(...).all()`). Neutral 0.0 means
"no evidence either way", never a spurious spike.

### Q17. Is there any data leakage protection?
Yes, three layers:
- split **before** rolling-window feature extraction;
- thresholds calibrated on the clean holdout the model never trained on;
- models trained only on **clean** data (unsupervised) — attack rows are used
  exclusively for evaluation, never for fitting.

---

## 5. Feature engineering (what the models actually see)

### Q18. What features does M1 (physical) compute?
18 features, all `m1_*` (`member1_physical/src/features.py::FEATURE_COLUMNS`) —
residuals between the **reported navigation state (GNSS claim)** and the
**IMU-integrated motion**, plus trajectory-shape metrics:

| Feature | Meaning |
|---|---|
| `m1_dt_s`, `m1_speed_mps`, `m1_speed_excess_mps` | sampling step, speed, speed above historical max (22 m/s default, re-learned from clean data) |
| `m1_position_residual_m`, `m1_velocity_residual_mps`, `m1_accel_residual_mps2` | GNSS claim vs dead-reckoned prediction |
| `m1_heading_residual_deg`, `m1_course_heading_residual_deg` | reported heading vs course-over-ground |
| `m1_speed_component_residual_mps` | velocity component consistency |
| `m1_accel_mag_mps2`, `m1_heading_rate_deg_s` | raw motion magnitudes |
| `m1_smoothness_heading_deg_s`, `m1_smoothness_accel_mps2` | jerk/spikiness over a 21-sample (~2 s) window |
| `m1_traj_deviation_m`, `m1_traj_deviation_sigma` | deviation from the recent trajectory model, in σ units |
| `m1_gnss_imu_disagreement`, `m1_sensor_disagreement` | cross-source agreement |
| `m1_gnss_quality` | reported signal quality |

Key design detail: dead-reckoned heading uses a **drift-anchored** IMU forward
integration with a gate (`_ANCHOR_TAU_S=5.0`, `_ANCHOR_GATE_MPS2=0.5`, median-5
filter): on clean data the anchor bounds integration drift; during
spoof/malfunction the gate closes and the disagreement survives instead of
being absorbed.

### Q19. What features does M2 (temporal/network) compute?
45 features `m2_*`, split into two disjoint sets (tests assert
`union == FEATURE_COLUMNS` and `intersection == ∅`):

**Temporal (34)** — five groups:
- *Sampling/kinematic baselines:* `m2_dt_s`, `m2_dt_median_s`, `m2_dt_ratio`,
  `m2_speed_mps`, `m2_accel_mag_mps2`, rolling speed std/range, jerk, change rates, `m2_heading_rate_deg_s`.
- *Timestamp integrity:* `m2_ts_nonmono`, `m2_ts_gap_s`, `m2_ts_jump_forward_s`,
  `m2_ts_rewind_s`, `m2_ts_drift_s`, `m2_ts_repeat`, `m2_ts_stale_age_s`.
- *Sequence integrity:* `m2_seq_gap`, `m2_seq_jump`, `m2_seq_dup`, `m2_seq_back`,
  `m2_seq_expected_err`, `m2_seq_dup_run`, `m2_seq_seen_before`.
- *Replay/staleness:* `m2_stale_score`, `m2_stale_active`.

**Network (11)** — `m2_pkt_rate` (+ratio, deficit), `m2_pkt_iat_ms` (+ratio,
excess, std/jitter, burst), `m2_pkt_loss` (+excess), `m2_net_disruption`.

### Q20. Why *these* features — how do they map to attacks?
Each attack family has a signature the feature set is designed to expose:

| Attack | Signature features |
|---|---|
| GNSS spoofing | position/velocity/accel residuals, `m1_gnss_imu_disagreement`, speed excess |
| Replay (stale) | `m2_seq_seen_before`, `m2_ts_stale_age_s`, `m2_ts_rewind_s` — caught **across window boundaries** via `history` (150 rows of context ≥ the 121-tick replay delay) |
| Network anomaly | `m2_pkt_iat_excess_ms` (~950 ms spikes vs ~20 ms normal), packet loss, rate drop |
| Telemetry manipulation | sequence gaps/duplicates/backward steps, timestamp jitter/non-monotonicity |
| Sensor malfunction | smoothness spikes, accel/heading-rate anomalies, growing trajectory deviation |
| Cross-sensor conflict | `m1_sensor_disagreement`, `m1_gnss_imu_disagreement` with clean individual channels |

### Q21. What is a "window"?
One scoring unit = **50 rows ≈ 5 s at 10 Hz**. Aggregation inside a window is
**p90** (not mean) of per-row anomaly scores — the "window-mean dilution" fix:
a 50%-interleaved attack would otherwise be averaged down to invisibility.
Deterministic check severity also saturates at `severity_cap_multiplier=4×`
the learned limit.

---

## 6. Algorithms: which, and why

### Q22. Which ML algorithms are used?
Per module (all scikit-learn):

| Role | Algorithm | Config (`settings.yaml`) |
|---|---|---|
| **Primary anomaly detector** (M1, M2-temporal, M2-network) | **IsolationForest** | `n_estimators: 200`, `contamination: auto`, `random_state: 42`, `fpr_target: 0.01` |
| **Baseline comparison** | **One-Class SVM** | `nu: 0.02`, `kernel: rbf` |
| Feature scaling | `StandardScaler` | fit on train only |
| Deterministic evidence checks | physics/rule checks with **learned limits** | limits = 99.9th percentile of clean data (`threshold_percentile: 0.999`) |
| Trust combination | **weighted geometric mean** + attribution matrix + dynamic decay | `trust_engine:` section |
| Fusion | trust-aware weighted least squares (+ Kalman baseline) | `fusion:` section |

### Q23. Why IsolationForest as primary?
1. **Unsupervised / one-class:** training data is *clean only* — attacks are
   rare and (in the real world) unlabeled; IF learns "normal" and scores
   deviations. This also means **no attack data is needed at train time**, which
   is exactly the project's threat premise.
2. **Baseline-first mandate:** the brief (`about_project.txt` §8–9) explicitly
   says start with classic ML baselines, not deep learning. IF is the canonical
   novelty detector — small, fast, explainable-by-feature-importance.
3. **Robust to contamination:** `contamination='auto'` means the decision
   threshold is not guessed from a contaminated training set; instead we
   calibrate it on a clean holdout (below).
4. **Deterministic:** `random_state=42` → reproducible artifacts.

### Q24. Why keep One-Class SVM at all?
It is the **comparison baseline required by the brief** and it has a real
trade-off worth showing: on M1 data OCSVM reaches higher recall (0.833 vs IF
0.555) at the cost of a slightly higher FPR (0.010 vs 0.004). Keeping both
documents *why* IF is primary (precision + speed) and quantifies what an
ensemble could gain later.

### Q25. Why not deep learning (LSTM/Transformer)?
The project brief prescribes baselines first. Also: the datasets are small
(24k–60k rows of tabular time-window features, not raw sequences), the module
must run in a real-time backend loop (p50 6–39 ms REST — deep models add
latency and GPU dependency), and explainability per window matters more than
raw accuracy. The trust engine reserves fields (`model_type`/`learned_model`)
so a learned model can be swapped in later **without touching callers**.

### Q26. How are alert thresholds set? Why not just 0.5?
Two-level calibration:
- **M1:** one IF threshold calibrated on the clean holdout so that the false-positive rate ≤ `fpr_target` 0.01 (measured: threshold 0.459, achieved FPR 0.004).
- **M2:** two detectors (temporal, network) each calibrated at `fpr_target/2`
  with a **Šidák correction**, so their **union** meets the 0.010 FPR budget
  (multiple-testing correction — two shots at flagging a window must not double
  the false-alarm rate).
- **M3:** GREEN ≥ 70, AMBER 40–70, RED < 40 (`trust_engine.thresholds`).

### Q27. What are the deterministic (non-ML) checks?
Rule-based evidence with limits learned from clean data (p99.9), e.g. M1:
`max_position_residual_m 25`, `max_velocity_residual_mps 22`,
`max_heading_residual_deg 30`, `max_deviation_sigma 6`, `min_gnss_quality 0.3`;
M2: `max_ts_rewind_s 0.05`, `max_seq_back 0`, `max_dt_ratio 3`,
network `iat_spike_ms 200`, `max_pkt_loss 0.05`.
**Why both ML and rules?** Rules give *explainable, per-check evidence strings*
("velocity residual 65 m/s > historical max 22 m/s") that the dashboard shows;
ML catches subtle multivariate deviations no single threshold can. They remain
**separate inputs** to the trust engine — neither can mask the other.

---

## 7. Model training pipeline

### Q28. Walk through training end-to-end (M1 as the example)
`py -m member1_physical.src.train`:

1. `_clean_sources()` — load `data/real/*` first, then `data/synthetic/*`, then
   fallback generator; print which source was used (provenance).
2. Per source: drop NaN timestamps → **80/20 split** →
   `extract_physical_features()` on each half separately.
3. `fit_scaler(train)` — StandardScaler on `m1_*` columns.
4. `train_model(train, settings)` — IsolationForest(200, auto, 42).
5. `train_ocsvm_baseline(...)` — OCSVM(nu 0.02, rbf) for comparison.
6. `calibrate_threshold(iso, scaler, holdout, fpr_target=0.01)` — the alert
   threshold from clean-holdout score quantile.
7. `learned_limits(train)` — per-check limits at the 99.9th percentile of clean data.
8. Save contract artifacts (below).

M2 does the same **twice** (temporal model on temporal columns, network model
on network columns) plus the Šidák per-detector calibration.

### Q29. What artifacts are produced, and where?
Per `data_schema.md` §4:

| Artifact | Producer | Format |
|---|---|---|
| `models/physical/isolation_forest.pkl` | M1 | joblib |
| `models/physical/feature_scaler.pkl` | M1 | joblib |
| `models/physical/physical_limits.json` | M1 | JSON (learned limits) |
| `models/temporal/temporal_model.pkl` + `network_model.pkl` (+ scalers, OCSVM baselines) | M2 | joblib/JSON |
| `models/trust/trust_weights.json`, `fusion_config.json` | M3 | JSON |

`*.pkl` is **gitignored** — regenerate locally after cloning. All models were
retrain-verified reloadable (`system_audit.md` §5).

### Q30. When are models retrained, and what changed?
Timeline (all measured, `AGENTS.md` §5):

| When | Data | Result |
|---|---|---|
| Initial | fallback generators | M1 P 1.000 / FPR 0%; M2 P 1.000 / R 1.000 |
| 2026-10-03 | M4 synthetic | M1 P 0.99 / FPR 0.3%; M2 P 0.87 / FPR 4.1% |
| 2026-10-04 | **real GeoLife + M4 clean** | M1 P 0.988 / FPR 0.4%; **M2 FPR 0.000%** (was 2.6%); M3 headline unchanged (gnss_spoof F1 0.992) |

Old artifacts backed up at `models/_backup_pre_real/`.

### Q31. How do you retrain?
```bash
py scripts/convert_geolife.py --target-rows 60000   # raw zip -> data/real/geolife.csv
py -m member1_physical.src.train                    # prefers data/real/, then synthetic, then fallback
py -m member2_temporal.src.train
py -m member1_physical/src.evaluate && py -m member2_temporal/src.evaluate && py -m member3_trust/src.evaluate
```

---

## 8. Trust engine (M3) — the core scoring math

### Q32. How is the 0–100 trust score computed?
`member3_trust/src/trust_engine.py::compute_trust(scores, history=None, observations=None)`:

1. **Normalize inputs** to "higher = trustworthy": `anomaly_*` inverted to `1 − value`.
2. **Weighted geometric mean** over evidence families
   (`trust_engine.weights`, seeded from `settings.yaml`):
   `physical 0.30, temporal 0.20, cross_sensor 0.25, network 0.15,
   historical_reliability 0.10, anomaly_physical 0.05, anomaly_temporal 0.05`.
   **Why geometric, not arithmetic?** "No-absolution": all evidence must agree
   for high trust, and one catastrophic red flag pulls the result down
   proportionally to its weight instead of being averaged away — exactly the
   §12 behavior (reliability 0.94 with weight 0.10 cannot rescue a 0.03 physical score).
3. **Three evidence-aggregation rules** on top (CR #5, `aggregation:` config):
   - **Corroboration penalty:** ≥2 independent degraded families (quality < 0.75)
     multiply trust by 0.92 each (floored at `severe_floor 0.35`) — two agreeing
     bad signals are worse than one.
   - **Primary-channel pull:** a sensor's score blends 0.85 toward its primary
     channel when that channel is much weaker (`primary_margin 0.10`) — e.g. the
     `net` sensor cannot out-live its own network-integrity channel. This took
     network_anomaly F1 0.519 → 0.899 without changing any weights.
   - **Uncorroborated-extreme tempering:** extreme cross-sensor disagreement
     with every other family clean is bounded to floor 0.72 (likely derived-channel
     drift, not decisive evidence).
4. **Per-sensor attribution matrix:** observation-level evidence is routed to
   sensors — low physical consistency implicates GNSS (the spoofable absolute
   reference), not the self-contained IMU. Produces the §22 story:
   GNSS 5% while IMU/visual/network stay 93–96%.
5. **Dynamic trust (§13):** per-sensor trust *moves toward* its evidence target —
   fast down (`drop_rate 0.75`, so a 50-row attack block reaches RED in ≤2
   windows), slow up (`recovery_rate 0.25`, ramping +0.5× per consecutive clean
   window up to `recovery_max 0.9`). No permanent blacklist.
6. **Headline = weakest link:** `observation_trust = min(per-sensor trust)` —
   one manipulated measurement that looks legitimate can corrupt everything
   (§1), so it must not be averaged away. The consensus mean is reported
   separately as `trust.consensus_trust`.
7. **Alert:** GREEN ≥ 70 / AMBER 40–70 / RED < 40, with §16 wording,
   `possible_causes` from `_CAUSES`, and a recommended action.

### Q33. What are `sensor_weights` and how are they normalized?
Per-sensor fusion weights derived from per-sensor trust, normalized by
`floor_normalize()` so each weight ≥ `fusion.min_sensor_weight` (0.05) and they
**sum to 1** (tested to 1e-6). The floor is enforced *after* normalization so a
catastrophic sensor keeps a small non-zero weight (it can still be evidence)
but never dominates. In the spoof demo GNSS weight drops 0.249 → 0.017.

### Q34. What is the difference between `sensor_trust` and `sensor_reliability`?
- `sensor_trust` (0–100): **dynamic, per-observation** — this measurement right now.
- `sensor_reliability` (e.g. 94): **historical baseline** prior of the sensor,
  an evidence term with weight 0.10.
The dashboard shows the former in the sensor cards and the latter as the gauge
baseline — explicitly commented in `SensorStatusCards.jsx`.

---

## 9. Fusion (state estimation)

### Q35. How does fusion work, and why does trust matter to it?
`member3_trust/src/fusion.py::fuse(observations, trust_scores)`:

- **Normal fusion:** weights from assumed sensor accuracies — trusts ignored.
- **Trust-aware fusion:** weights from current per-sensor trust (via
  `floor_normalize`) — a spoofed GNSS is down-weighted to ~2% before it drags
  the estimate.
- Weighted least squares position solution; a **Kalman baseline** is included
  for the §20 comparison.
- **Trust-gated aided-INS:** dead-reckoned channels get velocity damping and
  position re-anchoring **only while evidence is clean** (`rate 0.35`,
  `min_disagreement_m 80`, `max_velocity_gap_mps 8`): bounded inertial drift is
  healed, but a conflict step (35 m) or spoofed velocity (18 m/s gap) is *never*
  healed — the conflict must stay visible to cross-sensor agreement.

**Result (§20 robustness table):** trust-aware fusion beats normal fusion at
every corruption level — e.g. at 30% corruption **6.7 m vs 9.2 m** error;
clean-scenario error improved 32.1 → 8.6 m after the epoch-alignment fix.

---

## 10. End-to-end system pipeline

### Q36. What happens when one observation window arrives at runtime?
```
rows (schema §1, 50-row window, plus 150 prior rows as history)
  │
  ▼  integration/pipeline.py::run_observation(window_df, prior_rows)
  ├─► score_physical(window)          → M1: physical_consistency, anomaly_physical, evidence, level
  ├─► score_temporal(window, history) → M2: temporal_consistency, anomaly_temporal,
  │                                    network_integrity, evidence (seen-before freshness!)
  ├─► compute_trust(scores, history)  → M3: trust 0–100, sensor_trust/weights,
  │                                    alert (GREEN/AMBER/RED), enriched evidence
  └─► fuse(...) (backend)             → fused state_estimate
  │
  ▼
TrustMessage JSON (data_schema §2)
  ├─► persisted (SQLite/PG: observations, trust_scores, evidences, alerts)
  ├─► REST  /api/v1/trust/current, /history, /evidence/{id}, /alerts, /trajectory
  └─► WebSocket /ws/live  ──► React dashboard (gauge, map, charts, evidence, alert)
```

### Q37. How are the modules decoupled?
Three mechanisms:
1. **Contracts first:** `docs/contracts/data_schema.md` + `module_interfaces.md`
   fix exact CSV columns, JSON message, and function signatures before code.
2. **Registry, not imports:** `integration/interfaces.py` keeps a name→function
   registry; `integration/pipeline.py::register_available_implementations()`
   registers M1/M2/M3 **defensively** — a missing member degrades to
   `{"status": "module_not_ready"}` instead of crashing (the backend falls back
   to the labelled mock).
3. **No cross-member imports:** members never reach into each other's folders;
   everything crosses through the `integration/` adapters (repo rule).

### Q38. Where does streaming state/history live?
The backend `RealTrustService` keeps per-scenario pipeline sessions
(`_pipeline_sessions`) that retain the last `temporal.context_rows` (150) rows
per stream, feeding them to M2 as `history` and to M3 as trust history —
so replay detection and §13 dynamics work across windows, not just inside one.

---

## 11. Tech stack (full)

| Layer | Technology | Why this choice |
|---|---|---|
| Language | **Python 3.10+** | one language for data, ML, and backend; type hints; team familiarity |
| Data | **pandas ≥2.0, numpy ≥1.24, pyarrow ≥14** | tabular telemetry, vectorized feature math, parquet datasets |
| ML | **scikit-learn ≥1.3** (IsolationForest, One-Class SVM, StandardScaler), **joblib** | brief mandates classic baselines; joblib pickles with metadata (columns stored on the model as `m2_columns_`) |
| Plots/EDA | matplotlib, seaborn | evaluation graphs in `docs/reports/` |
| Backend | **FastAPI ≥0.110 + uvicorn** | async, Pydantic-native, auto OpenAPI; WebSocket support built in |
| Validation | **Pydantic ≥2.5** | schemas mirror `data_schema.md §2` exactly — contract enforced at runtime |
| ORM/DB | **SQLAlchemy ≥2.0**, SQLite (default) / PostgreSQL (psycopg2) | swap DB via `DATABASE_URL`, no code change |
| Real-time | **WebSockets (websockets ≥12)** `/ws/live` | one JSON frame per tick to the dashboard |
| Frontend | **React 18 + Vite** | fast dev server, proxy `/api` + `/ws` → :8000 |
| Map | **react-leaflet + CartoDB dark tiles** | trajectory visualization |
| Charts | **Recharts** | trust history line + stacked sensor-weight area |
| Testing | **pytest** (root `pytest.ini`, `--import-mode=importlib`) | 5 member suites collect together despite same-named test files |
| Config | **YAML** (`configs/settings.yaml`) + pydantic-settings | single shared tunables file, per-member additive sections (CR #1/#2) |
| Perf tooling | httpx load scripts, headless Chrome memory sampler | `member5_software/eval/` |

No GPU, no cloud services, no paid APIs — everything runs locally from the repo.

---

## 12. Backend API & real-time layer

### Q39. What endpoints exist?
From `backend/app/api/v1.py`:

```
GET  /health, /api/v1/health
GET  /api/v1/trust/current
GET  /api/v1/trust/history?sensor_id=&limit=
GET  /api/v1/evidence/{observation_id}
GET  /api/v1/alerts?active_only=&limit=
GET  /api/v1/trajectory?scenario=
POST /api/v1/demo/attack/{scenario}    # starts M1→M2→M3 playback (or mock fallback);
                                       # scenario "demo_story" = §22 story (92→5 RED→recovery)
POST /api/v1/demo/stop/{session_id}
POST /api/v1/demo/advance/{session_id}
POST /api/v1/real/session | /real/ingest | GET /real/trajectory | /real/datasets
WS   /ws/live                           # one §2 JSON frame per tick, epoch-based scenario switch
```

### Q40. How do mock and real services coexist?
`TrustServiceABC` interface with two implementations in
`backend/app/services/trust_service.py`:
- `MockTrustService` — labelled §22 demo-story numbers (fallback only).
- `RealTrustService` — calls `integration.pipeline.run_observation()` +
  `compute_trust(...)` + `fuse(...)`, persists to the DB.

`get_trust_service()` **auto-prefers Real** and falls back to Mock only if the
ML modules raise on import — one line to swap, and the fallback is logged, never
silent.

### Q41. How does the real-time stream handle scenario switches?
The service tracks `(ws_scenario, ws_epoch)`. Starting a new scenario bumps the
epoch; connected clients see the epoch change and reopen their session, so the
stream never mixes two scenarios' frames. Playback is per-session with speed
control; if the pipeline session cannot open, the labelled mock fallback plays
(and logs a warning once).

---

## 13. Frontend dashboard

### Q42. What does the dashboard show, and how is §15 explainability realized?
Components (`frontend/src/components/`):

| Component | What it shows |
|---|---|
| `TrustGauge` | 180 px SVG ring, color by GREEN/AMBER/RED, shows observation trust + historical reliability baseline |
| `MapView` | react-leaflet dark map: **true path / reported GNSS / fused estimate** (3-line legend) |
| `TrustChart` + `SensorWeightsChart` | Recharts: trust history with threshold refs; stacked per-sensor weight area |
| `SensorStatusCards` | 4 cards: current per-sensor trust %, weight %, level bar |
| `EvidencePanel` | ✓/✗ per check, **HIGH/MEDIUM/LOW evidence-level chip**, detail string, and the `Recommended action` box (§15: scores + evidence + causes + action, not just "anomaly 96%") |
| `AlertBanner` | pulsing RED banner on RED trust |
| `ScenarioControl` | 8 attack buttons + **Demo story** + Real Dataset / Live Device GPS buttons + WS live indicator |

Initial load is a REST fetch of current state; the WebSocket then keeps
gauge/chart/map/evidence/alert live.

---

## 14. Evaluation: metrics & results

### Q43. What metrics are used, and at what granularity?
**Window level** (50-row windows): Precision, Recall, F1, FPR, TP/FP/TN/FN,
plus detection **latency** = (first detected window − attack start + 1) × 5 s.
Fusion is evaluated separately by position error (m, §20). Targets: FPR ≤ 1%
on clean data; high recall on the family each module owns.

### Q44. What are M1's headline results?
`docs/reports/m1_evaluation.md` (10 M4 scenarios × 120 windows, 762 clean windows):

| Model | Threshold | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| IsolationForest (primary) | 0.459 | **0.988** | 0.555 | 0.711 | **0.004** |
| One-Class SVM (baseline) | 0.636 | 0.979 | 0.833 | 0.900 | 0.010 |

Per-scenario: telemetry manipulation **1.000**, sensor malfunction 0.883,
gnss spoof 0.767, mixed c05–c30 ≈ 0.5–0.58. On **real-data retraining**:
P 0.988 / FPR 0.4%. Replay is deliberately weak in M1 (a stale solution on a
steady track is physically indistinguishable) — that's M2's job.

### Q45. What are M2's headline results?
`docs/reports/m2_evaluation.md`: combined (temporal ∪ network) IsolationForest
**precision 1.000, FPR 0.000%** on clean windows (0 of 762 flagged, vs 1% budget);
network anomaly and telemetry manipulation caught via IAT spikes/sequence
evidence; after real-data retraining FPR stayed **0.000%** (down from 2.6%).
Replay detection is dominated by **deterministic evidence** (clock rewind,
sequence continuity, seen-before freshness), not the IF model — a documented
trade-off, not a gap: the evidence checks fire for the whole replay block.

### Q46. What are M3's headline results?
`docs/reports/m3_evaluation.md` + `experiment_results.md`:
- Demo story: trust 92.3 → 21.1 RED → 92.2, 7/7 acceptance checks, GNSS weight 0.252 → 0.068.
- Robustness sweep: detection **F1 0.80–1.00, FPR ≤ 0.036** across corruption levels; gnss_spoof **F1 0.992**.
- Fusion: trust-aware 6.7 m vs normal 9.2 m at 30% corruption.

### Q47. What did the last development phase improve? (before → after)
`docs/reports/experiment_results.md` §4 — measured against a verified
pre-change baseline (`trust_vs_baseline_before.csv`, captured by stashing all
changes and re-running the identical runner):

- Detection F1 improved in **8/10 scenarios**: network_anomaly **0.519 → 0.899**,
  cross-sensor conflict **0.696 → 0.800**, mixed c10 0.230 → 0.359, c30 0.500 → 0.606.
- FPR reduced in 5/11 scenarios (6 already 0); clean-scenario FPR **0.075 → 0.000**;
  clean fusion error **32.1 → 8.6 m** (epoch-alignment + damping fixes).
- Costs (stated): sensor_malfunction F1 0.974 → 0.947 (one borderline window);
  trust-aware fusion still loses to normal fusion on sensor_malfunction and mixed c20/c30.

### Q48. What are the backend/dashboard performance results?
`docs/reports/m5_evaluation.md`:
- REST latency, 5 endpoints × 200 requests: **p50 6–39 ms, p99 ≤ 325 ms**, all HTTP 200.
- WebSocket **30-min soak**: 8015 frames, **0 errors**, 224 ms average interval, 2.3 s to first frame.
- Backend RSS flat over the soak: ends 199.8 MB < starts 232.8 MB (max 288.8) — no leak.
- Browser JS heap bounded sawtooth, max 75.7 MB, DOM stable (1 h trend is
  *extrapolated*, labeled as such in the report).

---

## 15. Testing & quality assurance

### Q49. What is the test suite?
**175 tests, all passing** (`py -m pytest -q` → exit 0), up from the 152 baseline:

| Suite | Count | What it pins |
|---|---|---|
| M1 `member1_physical/tests` | 25 | features finite, learned limits, scorer contract, model reload |
| M2 `member2_temporal/tests` | 48 | feature sets disjoint/complete, replay evidence through history, empty-history equivalence |
| M3 `member3_trust/tests` | 47 | weighted-geometric math, alert bands, Σweights=1, aggregation rules, floor_normalize |
| M4 `member4_cyber/tests` | 15 | schema conformance, dataset pairs, reproducibility from seed |
| M5 `backend/tests` | 17 | endpoint contracts, schema §2 compliance, scenario validation |
| Root `tests/` (end-to-end + context wiring) | 23 (17 + 6) | full pipeline wiring; history forwarding, context-row config, demo_story endpoint |
| Frontend | build check | `npm run build` ✓ |

### Q50. What does the end-to-end test verify?
`tests/test_end_to_end.py`: real M4 data through `run_observation` → scores in
range, evidence present, trust 0–100, alert levels sane, fusion output valid,
module-missing degradation contract, byte-identical reruns.

### Q51. How were regressions handled during development?
Failures were fixed **at the cause**, never suppressed: e.g. M1's
ValueError on minimal frames → tests fake both scorers properly; missing
evidence `level` → level asserted only on M3-owned entries with a frontend
fallback for pass/fail-only entries. One behavioral test input was recalibrated
(`physical_consistency 0.35 → 0.55`) because the new primary-blend rule makes
0.35 genuinely RED — the band assertions themselves were not weakened.

---

## 16. Reproducibility & experiment protocol

### Q52. How do you know the numbers are reproducible?
- **Fixed seeds everywhere:** simulation seed 42, `random_state=42` in all models.
- **M4 datasets are byte-identical** on rebuild (audited, `system_audit.md` §8).
- **Demo reruns are byte-identical** (`run_demo.py` 16/16 checks twice).
- **Before/after comparison protocol:** the pre-change engine was captured by
  stashing all changes and re-running the *identical* runner on identical data
  (`trust_vs_baseline_before.csv` + `windows_before/`), so improvement claims
  compare file-to-file, not memory-to-memory.
- Each module has a one-command retrain + re-evaluate path (§7 Q31).

### Q53. How are thresholds/hyperparameters governed?
Everything tunable lives in `configs/settings.yaml` with per-member additive
sections (`physical:`, `temporal:`, `trust_engine:`, `fusion:`) — added via
CR #1/#2, review-flagged in `CHANGE_REQUESTS.md`. No magic numbers in code
except documented module constants (which reference their settings key).

---

## 17. Explainability & domain rules

### Q54. How is the output explainable? (§15)
Every message carries an **evidence list** where each entry has:
`check` (human-readable name), `pass` (✓/✗), `detail` with **actual numbers**
(e.g. "velocity residual 65 m/s > historical max 22 m/s"), and a
**HIGH/MEDIUM/LOW strength level**. Plus `possible_causes` and
`recommended_action`. The dashboard renders all four layers — never a bare
"anomaly = 96%".

### Q55. What wording rules must the system obey? (§16)
The system says observations are *"inconsistent / potentially consistent with
spoofing, malfunction, or communication manipulation"* — it **never** claims a
sensor "was hacked" or attributes an attacker. Enforced in
`trust_engine._CAUSES`, the alert templates, and tests.

### Q56. What distinguishes reliability from trust in the UI?
The gauge shows the historical reliability baseline; the sensor cards show
current dynamic observation trust (commented explicitly in
`SensorStatusCards.jsx` so a future contributor cannot confuse them).

---

## 18. Limitations (say these before anyone asks)

1. **No real attack data.** GeoLife is clean; attacks are controlled
   simulation (M4). Real spoofing ground truth would need a dataset like
   MARSIM (roadmap item 3 in `docs/real_data.md`).
2. **Derived channels in GeoLife:** accel/gyro are computed from positions
   (not measured); the "network" channel is sampling cadence, not packets —
   documented in the converter and `docs/real_data.md`, never hidden.
3. **Attribution is bounded:** per-sensor blame is an evidence-routing matrix,
   not forensic proof — the system assesses integrity, never attackers.
4. **Honest open items:** trust-aware fusion still loses to normal fusion on
   `sensor_malfunction` and mixed c20/c30; M1 IF recall on subtle mixed
   corruption is 0.5–0.6 (OCSVM higher, FPR higher); window-level replay recall
   for the IF model alone is low — deterministic evidence carries it.
5. **CR #5 is PROPOSED**, not yet team-approved (shipped with measurements,
   same pattern as approved #1–#4).
6. **Browser 1-hour memory soak was extrapolated**, not run (labeled in
   `m5_evaluation.md` §8); a true 1 h soak is a backlog item.
7. **Public datasets + simulation only** — no classified/real military data, by design.

---

## 19. Quick reference: commands, artifacts, file map

### Commands (repo root)
```bash
pip install -r requirements.txt

# Data
py scripts/convert_geolife.py --target-rows 60000
py -m member4_cyber.src.build_datasets          # deterministic, seed 42

# Train + evaluate
py -m member1_physical.src.train   && py -m member1_physical.src.evaluate
py -m member2_temporal.src.train   && py -m member2_temporal.src.evaluate
py -m member3_trust.src.evaluate

# Verify
py -m pytest -q                       # 175 passed
py -m member3_trust.src.demo          # 7/7 DEMO PASSED
python integration/run_demo.py        # 16/16

# Run the system (both, from repo root)
py -m uvicorn backend.app.main:app --reload        # :8000
cd frontend && npm install && npm run dev          # :5173
```

### Where to look for each answer
| Question about… | Read |
|---|---|
| Data format / labels | `docs/contracts/data_schema.md` |
| Function signatures | `docs/contracts/module_interfaces.md` |
| Change history / approvals | `docs/contracts/CHANGE_REQUESTS.md` |
| Real data flow | `docs/real_data.md` |
| M1/M2/M3/M4/M5 numbers | `docs/reports/m{1..5}_*.md` |
| Before/after experiment matrix | `docs/reports/experiment_results.md`, `trust_vs_baseline.md` |
| Trust math rationale | `member3_trust/src/trust_engine.py` docstring |
| All tunables | `configs/settings.yaml` |
| Current status | `AGENTS.md` §5/§6 |

---

## 20. Persistence & database

### Q57. What is stored in the database, and in what schema?
Four SQLAlchemy tables (`backend/app/db/models.py`), SQLite by default,
PostgreSQL by swapping `DATABASE_URL`:

| Table | Key columns | Notes |
|---|---|---|
| `observations` | `observation_id` (unique, indexed), `sensor_id`, `timestamp`, lat/lon/alt/velocity, `scores` JSON, `raw` JSON | parent row; `created_at` UTC |
| `trust_scores` | 1:1 with observations (FK `ondelete=CASCADE`), `observation_trust`, `sensor_weights`/`sensor_trust`/`state_estimate` JSON, `level`, `alert_message`, `possible_causes`, `recommended_action` | indexed on trust + level + recorded_at for history queries |
| `evidences` | per-observation evidence items (cascade delete) | powers `GET /evidence/{observation_id}` |
| `alerts` | `alert_id`, `level`, `message`, `possible_causes`, `observation_trust` | indexed on timestamp + level for `GET /alerts` |

JSON columns hold the variable-shape blocks (weights per sensor, evidence
lists) so the relational part stays queryable without schema churn.

### Q58. When is data written?
Two paths: REST playback persists as the pipeline advances, and **every
WebSocket frame is also written** (`store_trust_message` in `ws.py`) — so the
dashboard history survives restarts. Writes are wrapped in try/except inside
the stream loop: a DB hiccup must never kill the live feed.

### Q59. How does `GET /trust/history` choose its source?
`v1.py::get_trust_history` tries the database first (`list_trust_history` with
`sensor_id`/`limit` filters) and falls back to the in-memory service history
when the DB is unavailable — the endpoint never 500s just because the
database is down.

---

## 21. WebSocket protocol details

### Q60. What exactly flows over `/ws/live`?
One `TrustMessage` JSON frame (data_schema §2, serialized by alias) per tick,
at `ws_sleep_s / ws_playback_speed` intervals. Shape of the loop (`api/ws.py`):

1. Read `(scenario, epoch)` from the service; if the epoch changed (user
   pressed a different scenario button) or no session exists, open a new
   playback session — **the stream follows the dashboard buttons**, nothing is
   hard-coded.
2. `advance_playback(sid)` → next message; `None` = end of scenario → pause 2 s
   → reopen, so the stream loops continuously.
3. Persist the frame, `send_text(json.dumps(payload))`.
4. Non-blocking receive (1 ms timeout): a client `ping` gets a `{"type":"pong"}`.
5. Sleep the tick interval.

### Q61. How do clients survive disconnects / scenario switches?
- **Server side:** `WebSocketDisconnect` exits the loop cleanly and removes the
  connection from `_active_connections`; a new connection just starts reading
  the current `(scenario, epoch)` state.
- **Client side:** the dashboard auto-reconnects and re-fetches REST state on
  open, so a dropped socket costs at most one tick of staleness.
- The 30-min soak measured **8015 frames, 0 errors, 2.3 s to first frame**
  (`m5_evaluation.md` §3).

---

## 22. Configuration, security & failure handling

### Q62. How is configuration and environment handled?
- `backend/app/core/config.py` (pydantic-settings): `app_name`,
  `allowed_origins`, `DATABASE_URL`, `ws_playback_speed`, `ws_sleep_s`.
- All ML/tunable values: `configs/settings.yaml` (per-member additive sections;
  personal overrides go in `configs/local.yaml` per its header comment).
- The pipeline reads `temporal.context_rows` defensively: config unreadable →
  safe default 150, never a crash (`integration/pipeline.py`).

### Q63. What about CORS and security posture?
CORS is enabled with `allow_origins=settings.allowed_origins` (configurable —
default is the local Vite origin), all methods/headers for the dev topology.
This is a **local demo/research system**: no auth layer, no TLS termination in
the app (the phone-testing docs recommend putting a tunnel/proxy such as
ngrok or Cloudflare tunnel in front for HTTPS). No secrets are stored in the
repo; `*.pkl`, the SQLite DB, and device captures are gitignored.

### Q64. What happens when something fails at runtime?
Graceful degradation at every layer, each logged once (`_warn_once`) instead
of spamming:

| Failure | Behaviour |
|---|---|
| A member module missing/unimportable | `register_available_implementations()` skips it; messages carry `{"…_status": "module_not_ready"}`; backend falls back to the **labelled** mock service |
| M4 dataset missing | loaders fall back: `data/real/` → `data/synthetic/` → clearly-marked fallback generator (printed with provenance) |
| Pipeline session won't open | `start_attack_scenario` returns the mock story **with a warning** — never silently |
| DB unavailable | history endpoints fall back to memory; frame persistence is try/except-wrapped |
| WS client disconnects | loop exits cleanly; connection deregistered |
| `init_db()` fails | app still starts (`try/except` in `main.py`) — API serves from memory |

The principle: **the demo keeps running and tells you what degraded**, which is
exactly the trust philosophy of the system itself.

---

*Report generated 2026-10-08 from the repository contents. Numbers quoted from
the reports named beside them; commands verified against the current tree
(pytest 175 passed, demo 7/7).*
