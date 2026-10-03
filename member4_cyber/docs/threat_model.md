# TRUSTBATTLE — Threat Model & Attack Simulation Catalogue (Member 4)

> Controlled-simulation catalogue for the TRUSTBATTLE information-integrity
> layer. Every scenario below is generated **synthetically** from seeded
> generators (`member4_cyber/src/`) — no real systems, no classified data,
> no live-signal experiments (about_project.txt §18/§24).
>
> Framing rule (§24): these scenarios model ways battlefield information can
> become **unreliable** — they do NOT model a specific adversary, and nothing
> here implies our system can attribute an attack. Detection targets are
> phrased as "evidence potentially consistent with …".

## 1. Threat framing

The MVP platform is a single UAV (`uav1`) publishing a fused 10 Hz telemetry
stream (schema v1.0, `docs/contracts/data_schema.md`): GNSS-reported
navigation + IMU + telemetry/network metadata. An unreliable-observation
event is any sustained manipulation of one of those channels such that the
reported picture stops matching physical reality. The damage is not the
compromised channel itself — it is the corrupted battlefield picture the
fusion layer would produce from it.

Clean reference: `data/synthetic/uav_normal_v1.parquet` (+ 3 support seeds),
6000 rows @ 10 Hz, multi-leg mission with turns/climbs, seed 42.

## 2. Scenario catalogue

All parameters come from `configs/settings.yaml → attacks:` (M4-owned).
Datasets: `data/attacks/scenario_<name>.parquet` + `scenario_<name>_ground_truth.csv`
(per-row §5 truth; `attack_start=1` marks "inside the attack window", per-row
`label` carries the scenario code). Attack window = second half of the track.

### 2.1 `scenario_gnss_spoof` — label 1 (GNSS spoofing)

* **Parameters:** offset ramps to 540 m after 30 s and keeps drifting at
  18 m/s, due east; reported GNSS quality ×0.6. Calibration: about_project.txt
  §7 (GNSS claims ~120 km/h where the IMU supports ~55 km/h → ~18 m/s
  divergence). The ramp is **unbounded** — a sustained manipulation.
* **What an honest stream shows:** position/velocity consistent with the
  IMU-integrated motion; GNSS quality ~0.95.
* **What the manipulated stream shows:** a *self-consistent* trajectory that
  drifts away from the inertial truth — position, velocity and course all
  agree with each other (a naive consistency check passes). The only
  witnesses are (a) the IMU/visual estimates that stay on the true track,
  (b) the historical speed envelope once the drift pushes reported speed
  beyond anything the platform has flown, (c) degraded reported signal quality.
* **Expected detection difficulty: MEDIUM.** Individually plausible values;
  detectable through cross-sensor disagreement (M1 physics, M3 §11 evidence).
  Early-ramp windows (offset still small) are genuinely hard — detection
  latency ~45 s in the interim M1 evaluation.
* **Real-world analogy:** GNSS spoofing demonstrated against UAVs in recent
  conflicts (§2 motivation; documented military requirement §24).

### 2.2 `scenario_replay` — label 2 (replay / stale data)

* **Parameters:** from the window start, every OTHER row is a verbatim copy
  of the message from 12.1 s ago (configs `attacks.replay.delay_s: 12`; odd
  tick offset so each copied source row is itself a live frame): old
  timestamp, old sequence number, old navigation state, old packet-delay
  pattern. Live rows in between keep fresh values.
* **Honest vs manipulated:** honest rows advance timestamp/sequence normally;
  manipulated rows re-broadcast already-transmitted content — the clock jumps
  backward ~12 s and forward again, sequence numbers repeat, the nav solution
  is frozen in the past while the platform kept flying.
* **Expected detection difficulty: LOW for temporal analysis** (duplicate
  sequence numbers + stale-age are unambiguous), **MEDIUM for physics**
  (stale nav on steady flight is physically indistinguishable — it becomes
  visible during maneuvers). Interim results: M1 0.90 recall (the loop
  mission guarantees maneuvers inside the window), M2 temporal detector sees
  the signature but its window-mean score is diluted by the 50% live rows
  (see §4 findings).
* **Real-world analogy:** recorded-signal replay, stale-data injection,
  delayed-message re-transmission (§9).

### 2.3 `scenario_telemetry_manipulation` — label 3 (false-data injection)

* **Parameters:** sequence numbers jump +3/+5, occasionally repeat/step
  backward; timestamps jitter ±30 ms with ~3% small non-monotonic steps;
  packet delay 8× noisier; packet rate wanders ±15 pps; position/velocity
  noise triples (σ 9 m / 1.5 m/s); GNSS quality −0.25.
* **Honest vs manipulated:** every manipulated value sits inside a plausible
  envelope — nothing is individually extreme. The manipulation is visible
  only as *joint* inconsistency (sequence-vs-timestamp, noise-vs-platform).
* **Expected detection difficulty: MEDIUM** — subtler and noisier than
  replay; trades recall for the false-positive budget. Interim: both M1 and
  M2 catch it at 0.95–1.00 recall (the joint pattern is strong).
* **Real-world analogy:** statistically plausible false-data injection,
  sensor-spoofing with realistic noise floors (§9/§10).

### 2.4 `scenario_network_anomaly` — label 4 (datalink anomaly)

* **Parameters:** ~8% of rows spike to 900 ± 150 ms packet delay (§10's
  "20 ms … 950 ms" example), each followed by a ~4 ms catch-up burst; packet
  rate drops 30–45 pps; packet loss ~25% (configs). Navigation fields stay
  clean — only the link misbehaves.
* **Honest vs manipulated:** nav identical to clean; the telemetry channel
  shows the spike/catch-up/loss pattern.
* **Expected detection difficulty: LOW** for the network detector (the
  §10 signature is unmistakable); the platform picture is affected only via
  the trust layer (stale/rate-limited information). Interim: M2 network
  recall 1.00, FPR on clean ≤1%.
* **Real-world analogy:** jamming, degraded datalinks, congested or
  manipulated communication channels (§10).

### 2.5 `scenario_sensor_malfunction` — label 5 (hardware failure)

* **Parameters:** IMU accel ramps a 1.2 m/s² bias on x (0.3× on y) over 10 s;
  the reported nav state integrates the faulty IMU (velocity random-walks
  off truth); accel/gyro freeze for ~1.5 s stretches every ~20 s (stuck
  values); accel noise ×8 bursts ~1 s every ~15 s.
* **Honest vs manipulated:** GNSS stays truthful; the inertial channel
  degrades — bias, frozen outputs, noise bursts.
* **Expected detection difficulty: MEDIUM** — the bias ramps slowly (early
  windows are subtle); stuck-value/noise-burst windows are easier. Interim:
  M1 recall 0.68, M2 0.40 (M1 owns the physics signature).
* **Real-world analogy:** hardware degradation/failure — no adversary
  required (§1 "sensor malfunction").

### 2.6 `scenario_cross_sensor_conflict` — label 6 (persistent disagreement)

* **Parameters:** constant ~35 m GNSS position offset + reported course
  rotated 12° from the IMU-sensed heading — constant, no ramp.
* **Honest vs manipulated:** every value is plausible in isolation (35 m is
  within poor-satellite-geometry behaviour; 12° within sloppy calibration) —
  but GNSS, IMU and the visual estimate **persistently disagree**, so nothing
  is individually anomalous while everything is jointly inconsistent.
* **Expected detection difficulty: HIGH by design** — this is the scenario
  that justifies the cross-sensor evidence layer (§11): it should be caught
  by *agreement analysis*, not by any single-channel threshold. Interim
  M1/M2 (single-channel detectors) barely see it — expected; M3's derived
  cross-sensor evidence is the designated detector.
* **Real-world analogy:** miscalibrated sources, multipath, subtle deception,
  conflicting observations from different sensors (§1/§11).

### 2.7 `scenario_mixed_c05/c10/c20/c30` — mixed corruption (§19 experiments)

Exact-rate mixtures (5/10/20/30% of rows corrupted) built from six
consecutive BLOCKS, one per attack family (cycle: spoof → replay →
telemetry → network → malfunction → conflict), laid over the middle 80% of
the track. Per-row truth identifies the attack type. These power the §20
robustness comparison (normal vs trust-aware fusion) in M3's evaluation.

## 3. Ground-truth semantics (important for consumers)

* `attack_start = 1` ⇔ "row is inside an injected attack window" (§1) —
  window semantics, matching the M1/M2 scenario convention.
* `label` = the scenario's attack code for every row inside the window
  (including replay's interleaved live rows; which rows are actually stale
  frames is discoverable from duplicated timestamps/sequence numbers).
* The §5 `*_ground_truth.csv` mirrors the parquet row-for-row — row *i* of
  the truth file corresponds to row *i* of the data file.

## 4. Interim evaluation findings on M4 data (handoff to M1/M2)

M1/M2 retrained on `uav_normal_v1` (+3 support seeds, 24k rows) and evaluated
over all 10 scenario pairs (`docs/reports/m1_evaluation.md`,
`docs/reports/m2_evaluation.md`, 2026-10-03):

* **Clean FPR is healthy** on the retrained models: M1 0.3% (P 0.99), M2
  combined 4.1% (P 0.87) — the earlier 46% FPR was a calibration-holdout
  artifact of a single-recipe clean track (fixed by the looping mission +
  4 clean files ≈ 96 calibration windows).
* **Per-family coverage (recall):** replay M1 0.90 / telemetry 1.0+1.0 /
  network M2 1.0 / malfunction M1 0.68 / spoof M1 0.23–0.40 (early-ramp
  windows genuinely hard) / conflict ≈0 (by design → M3's §11 layer).
* **Known open item (model-side, M1/M2 ownership):** *window-mean dilution* —
  attacks that manipulate only part of a window (replay: 50% interleaved
  stale rows) produce window-mean anomaly scores that cannot clear a
  max-of-holdout-window-means threshold when clean behavior is varied.
  Candidates for the owners: top-k or per-row window scoring, quantile
  (not max) calibration, or per-feature window statistics. The datasets
  above are stable inputs for that work.
* Truth position/velocity for error metrics is reconstructible from the seed:
  `member4_cyber.src.generate_data.simulate_truth(seed=42)` (parquet does
  not carry `DataFrame.attrs`).

## 5. Honest-claim boundaries (§24)

* We do **not** claim these scenarios replicate any specific real attack or
  adversary capability; they are controlled abstractions of *failure and
  manipulation modes* documented in the open literature (§2 motivation).
* We do **not** claim the interim detection numbers are final — they are the
  current baseline on synthetic data with interim M1/M2 models.
* All datasets, code and parameters are reproducible from seed 42 and
  validated by `member4_cyber/src/validate_dataset.py`
  (`docs/reports/m4_dataset_reports.md`).
