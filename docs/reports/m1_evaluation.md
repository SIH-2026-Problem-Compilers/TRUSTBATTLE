# M1 — Physical & Sensor Analysis: Evaluation Report

*Generated:* 2026-09-29 17:03 UTC · *Module:* member1_physical (TASK 5) · *Window:* 50 rows (~5 s @ 10 Hz)

## 1. Data

- fallback_normal: 4000 rows, 80 windows, attack share 0.0%, fs≈10 Hz
- fallback_spoof: 4000 rows, 80 windows, attack share 50.0%, fs≈10 Hz
- fallback_replay: 4000 rows, 80 windows, attack share 37.5%, fs≈10 Hz
- fallback_malfunction: 4000 rows, 80 windows, attack share 45.0%, fs≈10 Hz
- fallback_conflict: 4000 rows, 80 windows, attack share 40.0%, fs≈10 Hz
- ground truth: data/attacks/ is empty — evaluation uses the M1 fallback generator

## 2. Detection metrics (window level)

Alert threshold calibrated on a clean holdout for FPR target 0.010 (data_schema.md §3: anomaly 0–1, higher = more anomalous).

| Model | Threshold | Precision | Recall | F1 | FPR | TP | FP | TN | FN |
|---|---|---|---|---|---|---|---|---|---|
| IsolationForest (primary) | 0.676 | 1.000 | 0.862 | 0.926 | 0.000 | 119 | 0 | 262 | 19 |
| One-Class SVM (baseline) | 1.000 | 0.979 | 0.993 | 0.986 | 0.011 | 137 | 3 | 259 | 1 |

## 3. Per-scenario detail (IsolationForest)

| Scenario | Windows | Attack windows | Detected (of attack) | Recall | Mean latency (s) | Max latency (s) |
|---|---|---|---|---|---|---|
| `fallback_normal` | 80 | 0 | 0 | — | — | — |
| `fallback_spoof` | 80 | 40 | 40 | 1.000 | 5.0 | 5.0 |
| `fallback_replay` | 80 | 30 | 11 | 0.367 | 5.0 | 5.0 |
| `fallback_malfunction` | 80 | 36 | 36 | 1.000 | 5.0 | 5.0 |
| `fallback_conflict` | 80 | 32 | 32 | 1.000 | 5.0 | 5.0 |

Latency is measured at window granularity: (first detected window − attack-block start + 1) × 5 s.

## 4. False positives on clean data

- Clean windows scored: 262; flagged above threshold: 0 (FPR 0.000% vs target ≤1.0%).
- Target from the brief: high recall on gnss_spoof / sensor_malfunction with low FPs on clean data.

## 5. Findings & discussion

- **IsolationForest (primary)** reaches perfect precision on this data: every alert is a true attack, with zero false positives on clean data at the calibrated 1%-FPR threshold. Spoof, malfunction and cross-sensor-conflict scenarios are fully detected within one 5 s window.
- **Replay** is only partially visible to physics features — and that is the *correct* behavior: a stale navigation solution on a straight, steady track is physically indistinguishable from live data. Physics catches replay during maneuvers (10/30 windows); the remainder requires sequence/timestamp evidence from Member 2's temporal module (about_project.txt §17 replay scenario).
- **One-Class SVM (baseline)** trades a small false-positive rate (~1%) for higher recall: its kernel boundary also reacts to subtler stale-data signatures. Keeping IsolationForest as primary per the project plan; an IF+OCSVM ensemble is a candidate experiment for Member 3's trust-weight tuning.
- **Status:** numbers come from the clearly-marked M1 fallback generator because `data/attacks/` is still empty. Rerun `train` + `evaluate` unchanged when Member 4's real scenario pairs land — the loader consumes them via the data_schema.md §5 pair convention.

## 6. Graphs

![m1_score_distributions.png](docs/reports/m1_graphs/m1_score_distributions.png)
![m1_roc_pr.png](docs/reports/m1_graphs/m1_roc_pr.png)
![m1_timeline_fallback_spoof.png](docs/reports/m1_graphs/m1_timeline_fallback_spoof.png)

## 7. Score-message sample (consumed by M3 trust engine / M5 dashboard)

```json
{
  "scores": {
    "physical_consistency": 0.9799,
    "anomaly_physical": 0.3425
  },
  "evidence": [
    {
      "check": "GNSS/IMU position residual",
      "pass": true,
      "detail": "max position residual 17.7 m vs limit 25 m"
    },
    {
      "check": "GNSS/IMU velocity disagreement",
      "pass": true,
      "detail": "GNSS/IMU velocity disagreement: 0 m/s vs historical max 22 m/s (reported speed 6 m/s)"
    },
    {
      "check": "Historical speed envelope",
      "pass": true,
      "detail": "GNSS speed within historical max (6 m/s)"
    },
    {
      "check": "Acceleration consistency",
      "pass": true,
      "detail": "accel inconsistency 0.47 m/s\u00b2 vs limit 0.60 m/s\u00b2"
    },
    {
      "check": "Heading consistency (gyro-integrated)",
      "pass": true,
      "detail": "max heading residual 0.3\u00b0 vs limit 30\u00b0"
    },
    {
      "check": "Course vs heading agreement",
      "pass": true,
      "detail": "max course/heading mismatch 0.0\u00b0 vs limit 45\u00b0"
    },
    {
      "check": "GNSS velocity-component consistency",
      "pass": true,
      "detail": "velocity vs (vx,vy,vz) mismatch 0.0 m/s vs limit 3.0 m/s"
    },
    {
      "check": "Trajectory smoothness (heading rate)",
      "pass": true,
      "detail": "heading-rate dispersion 2.7\u00b0/s vs limit 15\u00b0/s"
    },
    {
      "check": "Trajectory deviation",
      "pass": true,
      "detail": "max track deviation 3.2\u03c3 vs limit 6.0\u03c3"
    },
    {
      "check": "GNSS signal quality",
      "pass": true,
      "detail": "min GNSS quality 0.87 vs floor 0.30"
    }
  ]
}
```

## 8. Reproduce

```bash
py -m member1_physical.src.train      # TASK 3 (rerun when M4 ships real data)
py -m member1_physical.src.evaluate   # TASK 5 (this report)
py -m pytest member1_physical/tests -q
```
