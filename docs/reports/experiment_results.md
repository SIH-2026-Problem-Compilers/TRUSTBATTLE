# Experiment Matrix — Results

*Generated:* 2026-10-07 · *Runner:* `evaluation/run_experiments.py`

Scenario matrix: normal, GNSS spoofing, replay/stale, telemetry manipulation, network anomaly, sensor malfunction, cross-sensor conflict, and mixed corruption at 5/10/20/30% (M4 datasets in `data/attacks/` + `data/synthetic/`).

## Method

- **Pipeline (actual, no shortcuts):** every window of every scenario (50 rows
  ≈ 5 s @ 10 Hz) is scored by M1 (`score_physical`) and M2 (`score_temporal`)
  through the `integration/` adapters, then assessed by M3 `compute_trust`
  (with per-sensor observations → derived cross-sensor agreement), then fused
  in BOTH modes — `normal` (equal weights, the conventional baseline) and
  `trust_aware` (weights ∝ current observation trust) — each smoothed with an
  identical constant-velocity Kalman filter so the comparison is fair.
- **Detection truth:** window-level M4 ground-truth labels
  (`label > 0` or `attack_start > 0`, schema §1). Detection decision:
  alert level ≠ GREEN (`observation_trust < trust_engine.thresholds.green`).
- **Fusion error:** mean Kalman-smoothed position error against the
  row-aligned truth track (reconstructed from M4's seed-42 clean dataset —
  attack functions only modify reported fields; same reconstruction the M5
  dashboard uses). When truth is unavailable, the cell reads **N/A**.
- **Recovery time:** seconds (windows × 5 s) from the last attack window
  back to trust ≥ GREEN, for scenarios that have a clean tail. Attack-to-EOF
  scenarios and the clean scenario report **N/A**.
- **Reproducibility:** fixed seeds (model `random_state`, per-window RNG
  `2000 + row_offset`); rerunning the runner reproduces the numbers.
  Per-window audit trail: `evaluation/results/windows/<scenario>.csv`.

## 1. Detection & trust per scenario

| Scenario | Corruption % | Windows (attack) | Precision | Recall | F1 | FPR | Avg trust | Min trust | Recovery (s) |
|---|---|---|---|---|---|---|---|---|---|
| normal | 0.0 | 120.0 (0.0) | 1.0 | N/A | N/A | 0.0 | 89.3 | 77.6 | N/A |
| gnss_spoof | 50.0 | 120.0 (60.0) | 1.0 | 1.0 | 1.0 | 0.0 | 50.5 | 5.0 | N/A |
| replay | 50.0 | 120.0 (60.0) | 1.0 | 1.0 | 1.0 | 0.0 | 59.2 | 23.5 | N/A |
| telemetry_manipulation | 50.0 | 120.0 (60.0) | 1.0 | 0.983 | 0.992 | 0.0 | 73.6 | 44.1 | N/A |
| network_anomaly | 50.0 | 120.0 (60.0) | 1.0 | 0.817 | 0.899 | 0.0 | 79.0 | 63.2 | N/A |
| sensor_malfunction | 50.0 | 120.0 (60.0) | 1.0 | 0.9 | 0.947 | 0.0 | 53.6 | 5.0 | N/A |
| cross_sensor_conflict | 50.0 | 120.0 (60.0) | 1.0 | 0.667 | 0.8 | 0.0 | 76.6 | 39.8 | N/A |
| mixed_c05 | 5.0 | 120.0 (6.0) | 0.087 | 0.333 | 0.138 | 0.184 | 82.0 | 45.4 | 5 |
| mixed_c10 | 10.0 | 120.0 (12.0) | 0.259 | 0.583 | 0.359 | 0.185 | 79.5 | 32.0 | 10 |
| mixed_c20 | 20.0 | 120.0 (24.0) | 0.339 | 0.792 | 0.475 | 0.385 | 60.1 | 5.0 | N/A |
| mixed_c30 | 30.0 | 120.0 (36.0) | 0.476 | 0.833 | 0.606 | 0.393 | 55.4 | 5.0 | N/A |

## 2. Fusion robustness (conventional vs trust-aware)

| Scenario | Corruption % | Normal fusion err (m) | Trust-aware fusion err (m) | Improvement |
|---|---|---|---|---|
| normal | 0.0 | 8.63 | 8.61 | 0.2 |
| gnss_spoof | 50.0 | 479.6 | 115.44 | 75.9 |
| replay | 50.0 | 222.03 | 220.87 | 0.5 |
| telemetry_manipulation | 50.0 | 12.44 | 13.14 | -5.6 |
| network_anomaly | 50.0 | 8.63 | 8.6 | 0.3 |
| sensor_malfunction | 50.0 | 5736.0 | 8167.76 | -42.4 |
| cross_sensor_conflict | 50.0 | 27.54 | 29.21 | -6.1 |
| mixed_c05 | 5.0 | 13.0 | 13.65 | -5.0 |
| mixed_c10 | 10.0 | 15.36 | 16.27 | -5.9 |
| mixed_c20 | 20.0 | 377.74 | 518.02 | -37.1 |
| mixed_c30 | 30.0 | 583.14 | 798.65 | -37.0 |

## 3. What each column means

- **Precision / Recall / F1 / FPR** — window-level detection vs M4 ground truth (flagged = alert level ≠ GREEN).
- **Avg/Min trust** — observation trust (0–100) across all windows of the scenario.
- **Recovery (s)** — time from the last attack window back to trust ≥ GREEN; `N/A` when the scenario has no clean tail.
- **Fusion errors / improvement** — Kalman-smoothed mean position error of each fusion mode vs ground truth; improvement = (1 − trust-aware/normal) × 100%.

## 4. Engine before → after (this development phase)

`before` = the identical runner executed with every Step-2..6 engine change stashed (mixed-corruption evidence aggregation, replay/stale history context, recovery ramp, trust-gated aiding + speed damping, epoch-aligned sensor observations); `after` = this run. Saved at `evaluation/results/trust_vs_baseline_before.csv`.

| Scenario | F1 before → after | FPR before → after | Normal err (m) before → after | Trust-aware err (m) before → after |
|---|---|---|---|---|
| normal | N/A → N/A | 0.075 → 0 | 32.11 → 8.63 | 34.96 → 8.61 |
| gnss_spoof | 0.992 → 1 | 0 → 0 | 463.11 → 479.6 | 60.19 → 115.44 |
| replay | 1 → 1 | 0 → 0 | 228.91 → 222.03 | 226.55 → 220.87 |
| telemetry_manipulation | 0.929 → 0.992 | 0 → 0 | 31.99 → 12.44 | 34.94 → 13.14 |
| network_anomaly | 0.519 → 0.899 | 0 → 0 | 32.11 → 8.63 | 34.86 → 8.6 |
| sensor_malfunction | 0.974 → 0.947 | 0 → 0 | 6112.07 → 5736 | 8922.1 → 8167.76 |
| cross_sensor_conflict | 0.696 → 0.8 | 0 → 0 | 32.8 → 27.54 | 35.8 → 29.21 |
| mixed_c05 | 0.136 → 0.138 | 0.307 → 0.184 | 63.41 → 13 | 76.87 → 13.65 |
| mixed_c10 | 0.23 → 0.359 | 0.389 → 0.185 | 157.64 → 15.36 | 218.39 → 16.27 |
| mixed_c20 | 0.376 → 0.475 | 0.469 → 0.385 | 404.74 → 377.74 | 579.08 → 518.02 |
| mixed_c30 | 0.5 → 0.606 | 0.5 → 0.393 | 615.8 → 583.14 | 882.62 → 798.65 |

- **Detection F1:** improved in 8/10 scenarios, unchanged in 1, worse in 1 (sensor_malfunction 0.974 → 0.947).
- **False-positive rate:** reduced in 5/11 scenarios (6 were already 0 and stayed 0).
- **Fusion errors:** the clean-scenario error dropped because sensor observations are now epoch-aligned (window-mean position for every channel) instead of comparing a window-mean GNSS against an end-of-window dead-reckoner position.

## Limitations (read this before quoting any number)

- Window-level evaluation: a 5 s window containing attack rows counts as an
  attack window; trust dynamics are intentionally gradual (§13), so the FIRST
  window of an attack block may still read GREEN — detection latency is real
  and is not hidden.
- Recovery windows immediately after an attack are counted as false positives
  by the strict window labels even though the system is explicitly in its
  designed gradual-recovery mode.
- The system assesses **information integrity**. It does NOT claim: military
  validation, detection of every cyberattack, attribution of attackers, or
  that any sensor "was hacked". Alerts use the §16 wording (potentially
  consistent with spoofing / malfunction / communication manipulation).
- Public datasets + controlled simulation only (no classified/real military
  data).
