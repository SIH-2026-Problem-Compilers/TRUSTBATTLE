You are an expert AI/ML engineer working on TRUSTBATTLE (AI-Driven Battlefield Information Integrity & Trust Assessment Engine).

You are MEMBER 1 of a 5-member team sharing ONE repository. Your ownership is the PHYSICAL & SENSOR ANALYSIS module. Other members are working on other modules in the SAME repo in parallel — respect their folders.

## Project context (read these files in the repo first)
- about_project.txt (full project vision)
- project_distribution.md (team split)
- docs/contracts/data_schema.md (shared data format — MANDATORY)
- docs/contracts/module_interfaces.md (what you must produce/consume — MANDATORY)

## Pipeline position
Member 4 gives you datasets → you produce physical scores → Member 3 (trust engine) and Member 5 (dashboard) consume them.

## Your ownership (work ONLY inside these paths)
- member1_physical/            (your code: src/, notebooks/, tests/)
- data/processed/              (your feature outputs, prefix files with m1_)
- models/physical/             (your trained model artifacts)
- docs/reports/ (only files prefixed m1_)

DO NOT modify: member2_temporal/, member3_trust/, member4_cyber/, member5_software/, backend/, frontend/, data/raw/, data/synthetic/, data/attacks/ (read them, never write), docs/contracts/ (read-only for you; propose changes in docs/contracts/CHANGE_REQUESTS.md).

## Your tasks (in order)

TASK 1 — Data loader
- member1_physical/src/data_loader.py: load parquet/csv from data/synthetic/ and data/attacks/, validate every column of docs/contracts/data_schema.md §1, raise clear errors on schema mismatch.

TASK 2 — Physics feature extraction
- member1_physical/src/features.py with function extract_physical_features(df) -> df (EXACT name/signature — Member 3's tooling imports it).
- Compute per-observation: position residual (GNSS vs IMU dead-reckoning), velocity residual (GNSS velocity vs IMU-integrated velocity), acceleration consistency, heading consistency, trajectory smoothness/deviation, GNSS-vs-IMU disagreement, sensor-to-sensor disagreement.
- Example anomaly signal to catch: GNSS says 120 km/h, IMU says 55 km/h, historical max 80 km/h (about_project.txt §7).

TASK 3 — Anomaly detection model
- Start with Isolation Forest (per project plan — do NOT start with deep learning). One-Class SVM as comparison baseline.
- Train on Member 4's clean data (data/synthetic/), calibrate/validate on attack scenarios (data/attacks/).
- Save artifacts as models/physical/isolation_forest.pkl and models/physical/feature_scaler.pkl (joblib).
- Output anomaly score normalized to 0–1 (higher = more anomalous).

TASK 4 — Score message
- member1_physical/src/physical_module.py: function score_observation(row_or_window) -> dict producing exactly:
  {"scores": {"physical_consistency": <0-1, higher=trustworthy>, "anomaly_physical": <0-1, higher=anomalous>}, "evidence": [{"check": ..., "pass": true/false, "detail": ...}]}
- Evidence strings must be human-readable (they appear on the dashboard), e.g. "GNSS/IMU velocity disagreement: 65 m/s vs historical max 22 m/s".

TASK 5 — Evaluation
- Against Member 4's ground truth files, report precision, recall, F1, false positive rate, detection latency. Save results + graphs to docs/reports/m1_evaluation.md.
- Target: high recall on gnss_spoof/sensor_malfunction scenarios with LOW false positives on clean data.

## Conventions
- Python 3.10+, pandas/numpy/scikit-learn/joblib. Use configs/settings.yaml for tunables (read it).
- Every function has a docstring; keep module importable with zero side effects.
- Add tests in member1_physical/tests/ (pytest) for features and scoring.
- Commit early and often with clear messages; never break the shared schema.
- If you need a field/format change, stop and propose it in docs/contracts/CHANGE_REQUESTS.md — do not silently change the contract.

## Definition of done
1. extract_physical_features(df) and score_observation(...) importable from member1_physical/src/.
2. models/physical/isolation_forest.pkl + feature_scaler.pkl saved and reloadable.
3. Evaluation report in docs/reports/m1_evaluation.md with real numbers from data/attacks/.
4. pytest passes inside your module.
