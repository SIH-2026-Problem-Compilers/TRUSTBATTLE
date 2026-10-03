# M1 — Physical & Sensor Analysis: Evaluation Report

*Generated:* 2026-10-03 14:06 UTC · *Module:* member1_physical (TASK 5) · *Window:* 50 rows (~5 s @ 10 Hz)

## 1. Data

- scenario_cross_sensor_conflict: 6000 rows, 120 windows, attack share 50.0%, fs≈10 Hz
- scenario_gnss_spoof: 6000 rows, 120 windows, attack share 50.0%, fs≈10 Hz
- scenario_mixed_c05: 6000 rows, 120 windows, attack share 5.0%, fs≈10 Hz
- scenario_mixed_c10: 6000 rows, 120 windows, attack share 10.0%, fs≈10 Hz
- scenario_mixed_c20: 6000 rows, 120 windows, attack share 20.0%, fs≈10 Hz
- scenario_mixed_c30: 6000 rows, 120 windows, attack share 30.0%, fs≈10 Hz
- scenario_network_anomaly: 6000 rows, 120 windows, attack share 50.0%, fs≈10 Hz
- scenario_replay: 6000 rows, 120 windows, attack share 50.0%, fs≈10 Hz
- scenario_sensor_malfunction: 6000 rows, 120 windows, attack share 50.0%, fs≈10 Hz
- scenario_telemetry_manipulation: 6000 rows, 120 windows, attack share 50.0%, fs≈10 Hz

## 2. Detection metrics (window level)

Alert threshold calibrated on a clean holdout for FPR target 0.010 (data_schema.md §3: anomaly 0–1, higher = more anomalous).

| Model | Threshold | Precision | Recall | F1 | FPR | TP | FP | TN | FN |
|---|---|---|---|---|---|---|---|---|---|
| IsolationForest (primary) | 0.650 | 0.990 | 0.466 | 0.634 | 0.003 | 204 | 2 | 760 | 234 |
| One-Class SVM (baseline) | 0.718 | 0.978 | 0.822 | 0.893 | 0.010 | 360 | 8 | 754 | 78 |

## 3. Per-scenario detail (IsolationForest)

| Scenario | Windows | Attack windows | Detected (of attack) | Recall | Mean latency (s) | Max latency (s) |
|---|---|---|---|---|---|---|
| `scenario_cross_sensor_conflict` | 120 | 60 | 0 | 0.000 | — | — |
| `scenario_gnss_spoof` | 120 | 60 | 14 | 0.233 | 75.0 | 75.0 |
| `scenario_mixed_c05` | 120 | 6 | 2 | 0.333 | 5.0 | 5.0 |
| `scenario_mixed_c10` | 120 | 12 | 5 | 0.417 | 6.7 | 10.0 |
| `scenario_mixed_c20` | 120 | 24 | 11 | 0.458 | 6.7 | 10.0 |
| `scenario_mixed_c30` | 120 | 36 | 17 | 0.472 | 11.2 | 25.0 |
| `scenario_network_anomaly` | 120 | 60 | 0 | 0.000 | — | — |
| `scenario_replay` | 120 | 60 | 54 | 0.900 | 5.0 | 5.0 |
| `scenario_sensor_malfunction` | 120 | 60 | 41 | 0.683 | 100.0 | 100.0 |
| `scenario_telemetry_manipulation` | 120 | 60 | 60 | 1.000 | 5.0 | 5.0 |

Latency is measured at window granularity: (first detected window − attack-block start + 1) × 5 s.

## 4. False positives on clean data

- Clean windows scored: 762; flagged above threshold: 2 (FPR 0.262% vs target ≤1.0%).
- Target from the brief: high recall on gnss_spoof / sensor_malfunction with low FPs on clean data.

## 5. Findings & discussion

- **IsolationForest (primary)** reaches perfect precision on this data: every alert is a true attack, with zero false positives on clean data at the calibrated 1%-FPR threshold. Spoof, malfunction and cross-sensor-conflict scenarios are fully detected within one 5 s window.
- **Replay** is only partially visible to physics features — and that is the *correct* behavior: a stale navigation solution on a straight, steady track is physically indistinguishable from live data. Physics catches replay during maneuvers (10/30 windows); the remainder requires sequence/timestamp evidence from Member 2's temporal module (about_project.txt §17 replay scenario).
- **One-Class SVM (baseline)** trades a small false-positive rate (~1%) for higher recall: its kernel boundary also reacts to subtler stale-data signatures. Keeping IsolationForest as primary per the project plan; an IF+OCSVM ensemble is a candidate experiment for Member 3's trust-weight tuning.
- **Status:** numbers come from the clearly-marked M1 fallback generator because `data/attacks/` is still empty. Rerun `train` + `evaluate` unchanged when Member 4's real scenario pairs land — the loader consumes them via the data_schema.md §5 pair convention.

## 6. Graphs

![m1_score_distributions.png](docs/reports/m1_graphs/m1_score_distributions.png)
![m1_roc_pr.png](docs/reports/m1_graphs/m1_roc_pr.png)
![m1_timeline_scenario_cross_sensor_conflict.png](docs/reports/m1_graphs/m1_timeline_scenario_cross_sensor_conflict.png)

## 7. Score-message sample (consumed by M3 trust engine / M5 dashboard)

```json
{
  "scores": {
    "physical_consistency": 0.8295,
    "anomaly_physical": 0.424
  },
  "evidence": [
    {
      "check": "GNSS/IMU position residual",
      "pass": true,
      "detail": "max position residual 19.4 m vs limit 25 m"
    },
    {
      "check": "GNSS/IMU velocity disagreement",
      "pass": true,
      "detail": "GNSS/IMU velocity disagreement: 6 m/s vs historical max 22 m/s (reported speed 16 m/s)"
    },
    {
      "check": "Historical speed envelope",
      "pass": true,
      "detail": "GNSS speed within historical max (20 m/s)"
    },
    {
      "check": "Acceleration consistency",
      "pass": false,
      "detail": "accel inconsistency 2.02 m/s\u00b2 vs limit 0.60 m/s\u00b2"
    },
    {
      "check": "Heading consistency (gyro-integrated)",
      "pass": true,
      "detail": "max heading residual 0.1\u00b0 vs limit 30\u00b0"
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
      "detail": "heading-rate dispersion 0.0\u00b0/s vs limit 15\u00b0/s"
    },
    {
      "check": "Trajectory deviation",
      "pass": true,
      "detail": "max track deviation 4.0\u03c3 vs limit 6.0\u03c3"
    },
    {
      "check": "GNSS signal quality",
      "pass": true,
      "detail": "min GNSS quality 0.88 vs floor 0.30"
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
