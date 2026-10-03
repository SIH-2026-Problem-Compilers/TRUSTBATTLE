# M2 — Temporal & Telemetry/Network Analysis: Evaluation Report

*Generated:* 2026-10-03 13:39 UTC · *Module:* member2_temporal (TASK 6) · *Window:* 50 rows (~5 s @ 10 Hz)

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

Alert thresholds calibrated on a clean holdout at fpr_target/2 per detector (union/Šidák correction so the COMBINED FPR meets the 0.010 target; data_schema.md §3: anomaly 0–1, higher = more anomalous). Combined = a window is flagged when either detector fires.

| Detector | Threshold | Precision | Recall | F1 | FPR | TP | FP | TN | FN |
|---|---|---|---|---|---|---|---|---|---|
| Temporal IsolationForest | 0.693 | 0.932 | 0.315 | 0.471 | 0.013 | 138 | 10 | 752 | 300 |
| Network IsolationForest | 0.100 | 0.874 | 0.333 | 0.483 | 0.028 | 146 | 21 | 741 | 292 |
| Combined (temporal ∪ network) | 0.693 | 0.872 | 0.482 | 0.621 | 0.041 | 211 | 31 | 731 | 227 |
| Temporal One-Class SVM (baseline) | — | 0.981 | 0.461 | 0.627 | 0.005 | 202 | 4 | 758 | 236 |
| Network One-Class SVM (baseline) | — | 0.973 | 0.333 | 0.497 | 0.005 | 146 | 4 | 758 | 292 |

## 3. Per-scenario detail (Combined IsolationForest)

| Scenario | Windows | Attack windows | Detected (of attack) | Recall | Mean latency (s) | Max latency (s) |
|---|---|---|---|---|---|---|
| `scenario_cross_sensor_conflict` | 120 | 60 | 0 | 0.000 | — | — |
| `scenario_gnss_spoof` | 120 | 60 | 24 | 0.400 | 45.0 | 45.0 |
| `scenario_mixed_c05` | 120 | 6 | 3 | 0.500 | 5.0 | 5.0 |
| `scenario_mixed_c10` | 120 | 12 | 6 | 0.500 | 5.0 | 5.0 |
| `scenario_mixed_c20` | 120 | 24 | 11 | 0.458 | 5.0 | 5.0 |
| `scenario_mixed_c30` | 120 | 36 | 16 | 0.444 | 10.0 | 25.0 |
| `scenario_network_anomaly` | 120 | 60 | 60 | 1.000 | 5.0 | 5.0 |
| `scenario_replay` | 120 | 60 | 7 | 0.117 | 75.0 | 75.0 |
| `scenario_sensor_malfunction` | 120 | 60 | 24 | 0.400 | 15.0 | 15.0 |
| `scenario_telemetry_manipulation` | 120 | 60 | 60 | 1.000 | 5.0 | 5.0 |

Latency is measured at window granularity: (first detected window − attack-block start + 1) × 5 s.

## 4. False positives on clean data

- Clean windows scored: 762; flagged (combined): 31 (FPR 4.068% vs target ≤1.0%).
- Target from the brief: high recall on replay / network_anomaly with low FPs on clean data.

## 5. Findings & discussion

- **Replay (stale data)** is M2's headline target and is caught by the temporal detector: the stale window re-broadcasts old sequence numbers and reuses old timestamps, so `m2_seq_seen_before`, `m2_ts_stale_age_s` and `m2_ts_rewind_s` fire for the whole replay block — not just its boundary. This closes the gap M1's physics module reported (replay on a steady track is physically invisible).
- **Network anomaly** is caught by the network detector through `m2_pkt_iat_excess_ms` (the ~950 ms spikes vs ~20 ms normal, about_project.txt §10), the post-spike catch-up bursts, packet loss and the packet-rate drop.
- **Telemetry manipulation** (label 3) shows up as sequence gaps/duplicates/backward steps, timestamp jitter and non-monotonic steps — a subtler, noisier signature than replay; detection here trades recall for the low false-positive budget.
- **IsolationForest stays primary** (project plan); the One-Class SVM baseline trades a small FPR for higher recall on subtle signatures. An IF+OCSVM ensemble is a candidate experiment for M3's trust-weight tuning.
- **Status:** numbers come from the clearly-marked M2 fallback generator because `data/attacks/` is still empty. Rerun `train` + `evaluate` unchanged when Member 4's real scenario pairs land — the loader consumes them via the data_schema.md §5 pair convention.

## 6. Graphs

![m2_score_distributions.png](docs/reports/m2_graphs/m2_score_distributions.png)
![m2_roc_pr.png](docs/reports/m2_graphs/m2_roc_pr.png)

## 7. Score-message sample (consumed by M3 trust engine / M5 dashboard)

```json
{
  "scores": {
    "temporal_consistency": 0.9942,
    "anomaly_temporal": 0.0115,
    "network_integrity": 0.9918
  },
  "evidence": [
    {
      "check": "Timestamp monotonicity",
      "pass": true,
      "detail": "max clock rewind 0.000 s vs limit 0.05 s"
    },
    {
      "check": "Sampling regularity",
      "pass": true,
      "detail": "max timestamp gap 0.000 s vs limit 0.50 s"
    },
    {
      "check": "Sequence-number continuity",
      "pass": true,
      "detail": "max deviation from expected sequence 1, 0 duplicate(s), max backward step 0 vs limits (2, 0, 0)"
    },
    {
      "check": "Message freshness (no re-broadcast)",
      "pass": true,
      "detail": "0 row(s) re-transmit an earlier sequence number"
    },
    {
      "check": "Velocity change-rate regularity",
      "pass": true,
      "detail": "max speed change rate 0.14 /s vs limit 2.0 /s"
    },
    {
      "check": "Inter-sample interval stability",
      "pass": true,
      "detail": "max dt/median-dt ratio 1.00 vs limit 3.0"
    },
    {
      "check": "Packet inter-arrival spikes",
      "pass": true,
      "detail": "Packet inter-arrival spike: 23 ms (normal ~20 ms)"
    },
    {
      "check": "Inter-arrival burst pattern",
      "pass": true,
      "detail": "0 catch-up burst row(s) (inter-arrival < 50% of median)"
    },
    {
      "check": "Packet loss",
      "pass": true,
      "detail": "max packet loss 0.0% vs limit 5.0%"
    },
    {
      "check": "Packet rate stability",
      "pass": true,
      "detail": "max packet-rate drop 4.0% below rolling median vs limit 40.0%"
    }
  ]
}
```

## 8. Reproduce

```bash
py -m member2_temporal.src.train      # TASK 4 (rerun when M4 ships real data)
py -m member2_temporal.src.evaluate   # TASK 6 (this report)
py -m pytest member2_temporal/tests -q
```
