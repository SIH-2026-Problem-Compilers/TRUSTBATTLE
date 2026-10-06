# TRUSTBATTLE — Shared Data Schema (v1.0)

> **RULE:** Every module MUST read/write data in exactly this format.
> If you need a new field, propose it in `docs/contracts/CHANGE_REQUESTS.md` — never silently change the schema.

## 1. Telemetry Row (CSV / Parquet — one row = one observation)

| Field | Type | Unit | Description |
|---|---|---|---|
| `timestamp` | float64 | seconds (epoch) | Time of observation |
| `sensor_id` | string | — | e.g. `uav1_gnss`, `uav1_imu`, `uav1_visual`, `uav1_net` |
| `latitude` | float64 | degrees | GNSS position |
| `longitude` | float64 | degrees | GNSS position |
| `altitude` | float64 | meters | GNSS altitude |
| `velocity` | float64 | m/s | Speed magnitude |
| `vx, vy, vz` | float64 | m/s | Velocity components |
| `accel_x, accel_y, accel_z` | float64 | m/s² | IMU acceleration |
| `gyro_x, gyro_y, gyro_z` | float64 | rad/s | IMU rotation rate |
| `heading` | float64 | degrees | Heading/yaw |
| `gnss_quality` | float64 | 0–1 | Reported GNSS signal quality |
| `packet_rate` | float64 | packets/s | Network telemetry |
| `packet_delay_ms` | float64 | ms | Inter-arrival delay |
| `packet_loss` | float64 | 0–1 | Loss fraction |
| `sequence_number` | int64 | — | Message sequence |
| `label` | int64 | — | `0=normal`, `1=gnss_spoof`, `2=replay`, `3=telemetry_manip`, `4=network_anomaly`, `5=sensor_malfunction`, `6=cross_sensor_conflict` |
| `attack_start` | int64 | — | `1` if row is inside an injected attack window |

### 1.1 Row structure & label semantics (CR #3, APPROVED 2026-10-06)

- **Canonical files are fused platform rows.** `data/synthetic/uav_normal_v1.parquet` and `data/attacks/scenario_*.parquet` carry **one row = one 10 Hz observation tick** with the full §1 field set and a single fused platform id: `sensor_id='uav1'`. All M1/M2 dt / sequence-continuity and 50-row ≈ 5 s window logic assumes this fused 10 Hz layout.
- **Per-sensor streams are a variant, not canonical.** The per-sensor layout (`uav1_gnss`/`uav1_imu`/`uav1_visual`/`uav1_net` at their own rates) ships as `member4_cyber/scenarios/uav_normal_v1_streams.parquet` for M5/future use — **not** in `data/synthetic/` (M1's `load_synthetic_directory` concatenates every file there; interleaved multi-rate rows would break sequence/timestamp semantics). A v1.1 streams migration with per-sensor grouping helpers can be proposed separately.
- **`attack_start` / `label` are window-level marks.** Every row inside an injected attack window carries `attack_start=1` **and** the scenario's label (e.g. `1` for the whole GNSS-spoof window); rows outside carry `attack_start=0` and `label=0`. Ground-truth CSVs (`scenario_*_ground_truth.csv`) use the same window-level convention.

## 2. Inter-Module Message (JSON — what modules pass to each other)

```json
{
  "schema_version": "1.0",
  "sensor_id": "uav1_gnss",
  "timestamp": 1735600000.00,
  "scores": {
    "physical_consistency": 0.0,
    "anomaly_physical": 0.87,
    "temporal_consistency": 0.42,
    "anomaly_temporal": 0.55,
    "network_integrity": 0.31,
    "cross_sensor_agreement": 0.18
  },
  "evidence": [
    {"check": "GNSS/IMU disagreement", "pass": false, "detail": "velocity residual 65 m/s > historical max 22 m/s"}
  ],
  "trust": {
    "observation_trust": 28.0,
    "sensor_reliability": 94.0,
    "sensor_weights": {"gnss": 0.10, "imu": 0.45, "visual": 0.45},
    "state_estimate": {"lat": 0.0, "lon": 0.0, "velocity": 0.0}
  },
  "alert": {
    "level": "RED",
    "message": "INFORMATION INTEGRITY ALERT",
    "possible_causes": ["GNSS spoofing", "sensor malfunction"]
  }
}
```

## 3. Score convention (AGREED BY ALL)

- All `*_consistency` / `*_integrity` / `*_agreement` scores: **0–1, higher = more trustworthy.**
- All `anomaly_*` scores: **0–1, higher = more anomalous.**
- `observation_trust`: **0–100.**

## 4. Model artifacts (saved in `models/`)

| Artifact | Producer | Consumer | Format |
|---|---|---|---|
| `models/physical/isolation_forest.pkl` | Member 1 | Member 3/backend | joblib |
| `models/physical/feature_scaler.pkl` | Member 1 | backend | joblib |
| `models/temporal/temporal_model.pkl` | Member 2 | Member 3/backend | joblib |
| `models/temporal/network_model.pkl` | Member 2 | Member 3/backend | joblib |
| `models/trust/trust_weights.json` | Member 3 | backend | JSON |
| `models/trust/fusion_config.json` | Member 3 | backend | JSON |

## 5. File layout of datasets

```
data/raw/          # original public datasets (never modified)
data/synthetic/    # Member 4's clean synthetic trajectories
data/attacks/      # Member 4's attack-injected datasets + *_ground_truth.csv
data/processed/    # feature-engineered outputs (written by M1/M2)
```

Attack datasets MUST come as pairs: `scenario_xxx.parquet` + `scenario_xxx_ground_truth.csv`
(ground truth = `timestamp, sensor_id, label, attack_start`).
