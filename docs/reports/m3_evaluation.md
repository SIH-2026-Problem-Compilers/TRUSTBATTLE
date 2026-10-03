# M3 — Trust Engine & Trust-Aware Fusion: Evaluation Report

*Module:* member3_trust (TASK 5) · *Pipeline:* M1+M2 scores → M3 trust → fusion

*Data source:* FALLBACK generator (member3_trust/src/eval_scenarios.py) — data/attacks/ is empty. Ground truth: per-row `label`/`attack_start` (schema §1); fusion error reference: generator truth in `df.attrs`.

## 1. Method

- Windows of 50 rows (~5 s @ 10 Hz). Per window: M1 (`score_physical`) + M2 (`score_temporal`) via the `integration/` adapters → `compute_trust` → `fuse` (trust-aware) and `fuse_normal` (baseline), both Kalman-smoothed identically for a fair §20 comparison.
- Detection unit: an alert level worse than GREEN (`observation_trust < 70`).
- Trust aggregation: weighted **geometric** mean over physical/temporal/network/cross-sensor/historical evidence (no-absolution combination), per-sensor blame routing via the attribution matrix, §13 dynamic trust (drop_rate 0.6, recovery_rate 0.25), weakest-link `observation_trust`.

## 2. Final-demo story (§22, DoD #3)

- start trust **92.3** → min under spoofing **21.1** (RED) → recovers to **92.2**. All demo acceptance checks passed: `7/7`.
- Per-sensor trust at attack peak: gnss 21, imu 97, visual 95, net 98 — the suspect source (GNSS) collapses while independent sources keep high trust.
- GNSS fusion weight 0.251 → 0.067 (§14 influence reduction).
![demo trust curve](m3_graphs/m3_demo_trust_curve.png)

## 3. Detection metrics vs corruption (window level)

| Corruption % | Windows | Attack win | Precision | Recall | F1 | FPR | Latency (s) | Min trust |
|---|---|---|---|---|---|---|---|---|
| 0 | 32 | 0 | 1.000 | 1.000 | 1.000 | 0.000 | — | 90.5 |
| 5 | 32 | 1 | 1.000 | 1.000 | 1.000 | 0.000 | 0.0 | 67.6 |
| 10 | 32 | 2 | 0.667 | 1.000 | 0.800 | 0.033 | 0.0 | 59.1 |
| 20 | 32 | 4 | 0.800 | 1.000 | 0.889 | 0.036 | 0.0 | 52.7 |
| 30 | 32 | 6 | 1.000 | 0.833 | 0.909 | 0.000 | 5.0 | 51.3 |

## 4. Robustness: Normal vs Trust-Aware fusion (§20)

| Corruption % | Normal pos err (m) | Trust-aware pos err (m) | Improvement | Normal vel err (m/s) | Trust-aware vel err (m/s) |
|---|---|---|---|---|---|
| 0 | 1.7 | 1.7 | -0% | 0.00 | 0.00 |
| 5 | 3.0 | 2.7 | 10% | 0.00 | 0.00 |
| 10 | 4.3 | 3.6 | 16% | 0.00 | 0.00 |
| 20 | 6.8 | 5.1 | 24% | 0.00 | 0.00 |
| 30 | 9.2 | 6.7 | 27% | 0.00 | 0.00 |

## 5. Graphs

![m3_robustness_vs_corruption.png](m3_graphs/m3_robustness_vs_corruption.png)
![m3_f1_vs_corruption.png](m3_graphs/m3_f1_vs_corruption.png)

## 6. Findings & discussion

- **Trust-aware fusion degrades more gracefully**: the largest error advantage is at 30% corruption (9.2 m → 6.7 m). As corruption rises, normal fusion lets spoofed GNSS pull the estimate while trust-aware fusion keeps the reliable sources dominant (§14).
- **No permanent blacklist**: after the attack ends, trust recovers gradually (recovery_rate 0.25) and returns above GREEN — §13 behaviour.
- **Explainability**: every alert carries evidence entries with the implicated sensor, possible causes (§16 wording — never "hacked") and a recommended action (§4/§15).
- **Cross-sensor evidence (Layer 5, §11)** is derived by M3 from the per-sensor estimates with consensus-based blame routing; it is the decisive evidence against a self-consistent spoof. When an upstream module starts emitting `cross_sensor_agreement`, the derived value steps aside automatically.
- **Status / caveat:** numbers come from the clearly-marked M3 fallback generator because `data/attacks/` is still empty (M4); M1/M2 interim models are likewise fallback-trained. Rerun `py -m member3_trust.src.evaluate` unchanged when M4's real scenario pairs land.
