# TRUSTBATTLE — Real Data Guide

How real (non-synthetic) data flows into the models and the dashboard, and the
roadmap for the remaining sources. Status: **live (2026-10-04)**.

## 1. What "real" means here

| Channel | What is real | What is derived | Where it lands |
|---|---|---|---|
| **Live device GPS** | Browser Geolocation fixes (lat/lon/alt/speed/heading/accuracy) + DeviceMotion accelerometer/gyroscope (phones; optional) | vx/vy from bearing+speed, packet_rate/delay from fix cadence, gnss_quality from accuracy | `POST /api/v1/real/ingest` → scored live → persisted `data/real/device_capture.csv` |
| **GeoLife dataset** | 59,094 rows of real phone GPS traces (Microsoft Research Asia, 182-user study, 2007–2012; 11 users selected round-robin, long traces only) | velocity/heading from consecutive fixes, accel/gyro from d(v)/dt and d(heading)/dt, network channel from real sampling cadence | `data/real/geolife.csv` (schema-valid) → **training set** + dashboard replay |
| **Synthetic scenarios (M4)** | simulated attacks with ground truth | — | `data/synthetic/`, `data/attacks/` → evaluation + demo playback |

**Honesty notes** (also printed by `scripts/convert_geolife.py`):
- GeoLife is GNSS-only — `accel_z`, `gyro_x`, `gyro_y` are 0.0; accel_x/y and
  gyro_z are *derived* from real positions, not measured. Live captures from a
  phone use the **measured** accelerometer/gyro when DeviceMotion is granted.
- The "network" channel for GeoLife is the real sampling cadence (fix rate,
  inter-fix delay, >10 s gap fraction) — not real packet telemetry.
- Every trajectory change / >60 s gap starts a new segment (derivatives reset,
  first 10 rows dropped) so no fabricated jump ever enters training.

## 2. Live device GPS (model predicts on your real position)

1. Dashboard → **Live Device GPS** button (cyan, under "Real Data").
2. Frontend starts `navigator.geolocation.watchPosition` (+ DeviceMotion after
   the iOS permission gesture) and batches schema rows every 2 s.
3. `POST /api/v1/real/ingest` coerces rows to `data_schema.md §1`, appends to
   `data/real/device_capture.csv` (gitignored), and once ≥10 new rows exist
   runs the **real** pipeline on the last ≤50 rows:
   `integration.pipeline.run_observation` (M1 physical + M2 temporal) →
   `compute_trust` (with trust history) → `fuse`.
4. The returned TrustMessage drives the gauge/evidence/alerts/trust chart;
   reported points (raw fixes) and fused state estimates draw the map.
5. Per-sensor honesty: observations = **gnss** (your receiver); **imu** is
   added only when the device actually reports motion data (dead-reckoned);
   no visual sensor is invented.

Endpoints: `POST /api/v1/real/session` (reset), `POST /api/v1/real/ingest`,
`GET /api/v1/real/trajectory`, `GET /api/v1/real/datasets`.

**Limitations:** geolocation needs a secure context — works on
`localhost`/`127.0.0.1` out of the box; testing from a phone on the LAN needs
HTTPS (use a tunnel such as `ngrok`/Cloudflare tunnel, or `vite --host` behind
a TLS proxy). Indoors the GPS fix may be denied or noisy — that is real data,
and trust scores reflect it.

## 3. Real dataset replay (no phone needed)

- Dashboard → **Real Dataset (GPS traces)** (lime, under "Real Data"), or
  `POST /api/v1/demo/attack/real_geolife` + `POST /api/v1/demo/advance/{sid}`.
- `backend/app/services/real_data.py::build_replay_messages()` runs every
  50-row window of `data/real/geolife.csv` through the real pipeline once and
  caches the 400 TrustMessages; the dashboard streams them (~700 ms/window)
  so the gauge/chart/evidence show real model output on real coordinates
  (Beijing traces). Map shows real path + fused estimates
  (`GET /api/v1/trajectory?scenario=real_geolife`).

## 4. Retraining on real data

```bash
py scripts/convert_geolife.py --target-rows 60000   # data/raw/geolife.zip -> data/real/geolife.csv
py -m member1_physical.src.train                    # prefers data/real/, then data/synthetic/, then fallback
py -m member2_temporal.src.train
py -m member1_physical.src.evaluate && py -m member2_temporal.src.evaluate && py -m member3_trust.src.evaluate
```

- Both `_clean_sources()` functions load `data/real/*.csv|parquet` **first**,
  then M4 clean data, then the fallback generator; each source is split 80/20
  *before* feature extraction (rolling windows never span sources).
- Previous artifacts backed up in `models/_backup_pre_real/`.
- Result (2026-10-04, pure real+M4 training): M1 P 0.988 / FPR 0.4%; M2 combined P 1.000 /
  **FPR 0.000%** (was 2.6%); M3 headline unchanged (gnss_spoof F1=0.992).
  Trade-off: some M4 synthetic per-scenario recalls dropped — the model now
  learns real-GPS noise; M3 end-to-end is dominated by evidence checks and
  stayed the same.

## 5. Roadmap (not yet wired)

1. **Live ADS-B aircraft feed (OpenSky)** — verified reachable without auth:
   `GET https://opensky-network.org/api/states/all?lamin=…&lomax=…` returns
   live aircraft states (lat/lon/vel/heading/rate). Planned as a third "real"
   scenario: poll conservatively (≥10 s), map callsign → velocity/accel, feed
   `/api/v1/real/ingest` with `sensor_id=adsb_gnss`. Watch anonymous rate
   limits before a live demo; cache the last response.
2. **Hardware sensors** — ESP32/Arduino + BN-220 GNSS/IMU streaming NMEA/CSV
   over serial→HTTP into the same ingest endpoint (schema already matches;
   no dashboard changes needed).
3. **Labeled real attacks** — GeoLife is clean; for real spoofing ground
   truth, convert a controlled-spoofing dataset (e.g. Zenodo MARSIM NMEA
   scenarios) to `data/attacks/` with `_ground_truth.csv` pairs and rerun the
   §eval reports.
4. **HTTPS for phone testing** — see §2 limitations.
