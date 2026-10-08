# Trust-aware vs Conventional Fusion — Baseline Comparison

*Generated:* 2026-10-07 · *Runner:* `evaluation/run_experiments.py` (actual experiments; rerun to reproduce)

Research question: does weighting fusion influence by **current observation trust** reduce the impact of corrupted information on the fused state compared with conventional equal-weight fusion?

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

## Results

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

**Summary:** trust-aware fusion has lower position error in 4/11 scenarios with computable ground truth (largest reduction 75.9%). Scenarios marked **N/A** have no usable ground truth in this run — no value was estimated for them.

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
