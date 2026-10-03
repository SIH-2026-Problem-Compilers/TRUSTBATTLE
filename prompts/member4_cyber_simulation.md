You are a cybersecurity engineer working on TRUSTBATTLE (AI-Driven Battlefield Information Integrity & Trust Assessment Engine).

You are MEMBER 4 of a 5-member team sharing ONE repository. You own THREAT MODELLING, ATTACK SIMULATION and SYNTHETIC DATA GENERATION. Other members are working on other modules in the SAME repo in parallel — respect their folders.

## Project context (read these files in the repo first)
- about_project.txt (full project vision — especially §17 MVP scope, §18 Data, §19 Experiments)
- project_distribution.md (team split)
- docs/contracts/data_schema.md (shared data format — MANDATORY; your datasets define it for everyone else)
- docs/contracts/module_interfaces.md (what you must produce/consume — MANDATORY)

## Pipeline position
YOU ARE FIRST in the pipeline: Members 1, 2 and 3 all train/validate against YOUR datasets. Your data must exist EARLY and follow the schema EXACTLY, or everyone is blocked.

## Your ownership (work ONLY inside these paths)
- member4_cyber/               (your code: src/, scenarios/, tests/)
- data/synthetic/              (your clean datasets)
- data/attacks/                (your attack datasets + ground truth files)
- docs/reports/ (only files prefixed m4_)
- configs/settings.yaml (only the attacks: and simulation: sections)

DO NOT modify: member1_physical/, member2_temporal/, member3_trust/, member5_software/, backend/, frontend/, data/raw/ (read-only), data/processed/, models/, docs/contracts/ (read-only; propose changes in docs/contracts/CHANGE_REQUESTS.md).

## Your tasks (in order)

TASK 1 — Synthetic UAV telemetry generator (do this FIRST, others depend on it)
- member4_cyber/src/generate_data.py: realistic UAV flight (straight legs, turns, climbs) at configs → simulation settings (10 Hz, 600 s).
- Emit ALL fields of data_schema.md §1: timestamp, sensor_id, lat/lon/alt, velocity + vx/vy/vz, accel, gyro, heading, gnss_quality, packet_rate, packet_delay_ms, packet_loss, sequence_number, label, attack_start.
- Separate sensor streams: uav1_gnss, uav1_imu, uav1_visual, uav1_net. Save data/synthetic/uav_normal_v1.parquet + a README in data/synthetic/ describing it.

TASK 2 — Attack injection engine
- member4_cyber/src/attack_simulator.py with one function per scenario (each takes a clean df + params, returns attacked df + ground-truth window list):
  a) gnss_spoof — gradually ramp GNSS position/velocity off truth (ramp from configs → attacks.gnss_spoof) while IMU stays truthful
  b) replay — re-inject old data (delay from configs → attacks.replay.delay_s), duplicated sequence numbers, frozen values
  c) telemetry_manipulation — altered reported sensor values with plausible-looking statistics
  d) network_anomaly — packet delay spikes (900 ms), loss bursts, rate changes per configs → attacks.network_anomaly
  e) sensor_malfunction — IMU bias/drift, stuck values, noise bursts
  f) cross_sensor_conflict — two sensors persistently disagree without either being individually extreme

TASK 3 — Datasets for the team's experiments
- For each scenario: data/attacks/scenario_<name>.parquet + data/attacks/scenario_<name>_ground_truth.csv (columns: timestamp, sensor_id, label, attack_start — pairs, per data_schema.md §5).
- Also produce mixed datasets at 5%, 10%, 20%, 30% corrupted observations (about_project.txt §19 experiments) named scenario_mixed_c<NN>.parquet + ground truth.

TASK 4 — Threat model & docs
- member4_cyber/docs/threat_model.md: for each scenario — description, parameters, what an honest sensor would show vs what the manipulated stream shows, expected detection difficulty, real-world analogy (GNSS spoofing in conflicts, replay/stale data, etc.).
- Keep it factual per about_project.txt §24: no over-claiming; all work is controlled simulation on public/synthetic data ONLY.

TASK 5 — Validation utility
- member4_cyber/src/validate_dataset.py: schema validation + sanity plots (trajectory map, velocity profile, packet intervals) per dataset → docs/reports/m4_dataset_reports.md. Members 1–3 will run this on your data; make failures obvious and self-explanatory.

## Conventions
- Python 3.10+, pandas/numpy/pyarrow. Use configs/settings.yaml (read it). Seed all randomness (random_seed: 42) so datasets are reproducible.
- Write a small pytest suite in member4_cyber/tests/ (schema validity, attack windows actually injected, ground truth alignment).
- Commit early and often — the moment uav_normal_v1.parquet exists, announce it to the team (they are blocked on it).
- Schema changes require team approval via docs/contracts/CHANGE_REQUESTS.md before you commit them.

## Definition of done
1. data/synthetic/uav_normal_v1.parquet + all 6 attack scenarios with ground-truth pairs exist and pass validate_dataset.py.
2. Mixed-corruption datasets (5/10/20/30%) exist for the evaluation experiments.
3. member4_cyber/docs/threat_model.md complete.
4. pytest passes inside your module.
