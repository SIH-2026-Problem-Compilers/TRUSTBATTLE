# member4_cyber — Threat & Attack Simulation (Member 4)

FIRST in the pipeline: Members 1–3 train/validate against these datasets.
Everything is controlled simulation on synthetic data (about_project.txt
§18/§24) — nothing touches real systems, nothing over-claims.

## Deliverables (definition of done — COMPLETE, 2026-10-03)

| Item | Path |
|---|---|
| Clean dataset (canonical) | `data/synthetic/uav_normal_v1.parquet` (+ 3 support seeds, 24k rows total) |
| 6 attack scenarios + §5 truth pairs | `data/attacks/scenario_{gnss_spoof,replay,telemetry_manipulation,network_anomaly,sensor_malfunction,cross_sensor_conflict}.parquet` + `*_ground_truth.csv` |
| Mixed corruption 5/10/20/30% | `data/attacks/scenario_mixed_c{05,10,20,30}.parquet` + truth (exact rates, all 6 families as consecutive blocks) |
| Per-sensor streams variant | `member4_cyber/scenarios/uav_normal_v1_streams.parquet` (uav1_gnss/imu/visual/net at configured rates — see CR #3) |
| Threat model | `member4_cyber/docs/threat_model.md` |
| Validation report | `docs/reports/m4_dataset_reports.md` (+ `m4_graphs/`) |

All 11 dataset files pass `validate_dataset.py` (schema + ground-truth
alignment + consistency); M1/M2 retrain + evaluate on them end-to-end
(see "Integration status").

## Layout

```
src/
├── schema.py            §1 constants (verbatim from the contract)
├── generate_data.py     TASK 1 — mission simulator + fused/streams serialisation
├── attack_simulator.py  TASK 2 — 6 attack functions + exact-rate mixed builder
├── build_datasets.py    TASK 3 — deterministic orchestrator (run this)
└── validate_dataset.py  TASK 5 — schema validation + sanity plots + report
docs/threat_model.md     TASK 4 — scenario catalogue, §24-compliant
tests/                   pytest suite (15 tests)
```

## Usage (from repo root)

```bash
py -m member4_cyber.src.build_datasets      # regenerate ALL datasets (seed 42, byte-reproducible)
py -m member4_cyber.src.validate_dataset    # validate + plots + report (exit 1 on any failure)
py -m pytest member4_cyber/tests -q
```

## Dataset semantics (read before consuming)

* **Fused rows (canonical):** one row = one 10 Hz platform tick with the full
  §1 field set, `sensor_id='uav1'`. Ground truth: `attack_start=1` marks every
  row *inside* an injected window (§1 wording); `label` = the scenario code
  for all window rows (replay's interleaved live rows included — which rows
  are actually stale is discoverable from duplicated timestamps/sequence
  numbers). The §5 CSV mirrors the parquet row-for-row.
* **Truth for error metrics:** parquet drops `DataFrame.attrs`; reconstruct
  via `member4_cyber.src.generate_data.simulate_truth(seed=42)`.
* **Mixed datasets:** six consecutive attack blocks (one per family, cycle in
  `schema.MIXED_ATTACK_CYCLE`) over the middle 80%; exact row counts.
* **Config ownership:** `attacks:` + `simulation:` sections of
  `configs/settings.yaml`. `attacks.gnss_spoof.offset_start_m` is calibrated
  to §7 (GNSS claims ~2× the IMU-supported speed → 18 m/s drift → 540 m).

## Integration status (2026-10-03)

* M1 + M2 retrained on this data (their documented `train` entry points pick
  up `data/synthetic/` automatically) and re-evaluated over all 10 pairs.
  Clean FPR: M1 0.3%, M2 4.1% combined. Family recall: telemetry 1.0 (both),
  network 1.0 (M2), replay 0.90 (M1), malfunction 0.68 (M1), spoof 0.23–0.40
  (early-ramp windows hard — by design), conflict ≈0 → M3's §11 layer.
* **Open model-side item (M1/M2 ownership, quantified in
  `docs/threat_model.md` §4):** window-mean dilution — 50%-interleaved replay
  windows cannot clear a max-of-holdout threshold when clean behavior is
  varied. Dataset-side fixes already shipped (looping representative mission,
  4 clean calibration files, jerk-limited kinematics); remaining gains need
  window-scoring changes in M1/M2.
* M3's `evaluate` maps corruption levels by filename (`corruption_XXpct`);
  these files are named `scenario_mixed_cXX` — M3 should update their matcher
  (or M4 can add alias symlinks if they prefer).
* Schema clarification (fused canonical vs per-sensor streams) proposed as
  `docs/contracts/CHANGE_REQUESTS.md` #3 — needs team 👍.
