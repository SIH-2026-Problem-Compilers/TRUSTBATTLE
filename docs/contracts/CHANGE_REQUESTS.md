# Schema / Interface Change Requests

> Add new requests at the bottom. Status: `PROPOSED → APPROVED / REJECTED`.
> Do NOT merge code that depends on an unapproved change.

---

| # | Date | Proposed by | Change | Reason | Status |
|---|------|-------------|--------|--------|--------|
| 1 | 2026-09-29 | M1 (physical) | Add additive `physical:` section to configs/settings.yaml (historical max speed, check limits, IF/OCSVM hyperparams, FPR target) | M1 tunables must live in the shared config per conventions; purely additive — no existing key touched, other members unaffected. Already shipped in commit b4c64a2 so M1 is testable; happy to restructure on request | PROPOSED |
| 2 | 2026-09-30 | M2 (temporal) | Add additive `temporal:` section to configs/settings.yaml (IF/OCSVM hyperparams, FPR target, temporal + network evidence-check limits) | M2 tunables must live in the shared config per conventions; purely additive — no existing key touched, other members unaffected. Shipped in the same commit as the M2 module so it is testable; happy to restructure on request | PROPOSED |
| 3 | 2026-10-03 | M4 (cyber) | Clarify §1 row structure for v1.0 datasets: the canonical `uav_normal_v1.parquet` / `scenario_*.parquet` files use **fused platform rows** (one row = one 10 Hz observation tick carrying the full §1 field set, `sensor_id='uav1'`); the per-sensor streams layout (`uav1_gnss`/`uav1_imu`/`uav1_visual`/`uav1_net` at per-sensor rates) ships as a **variant** (`member4_cyber/scenarios/uav_normal_v1_streams.parquet`) for M5/future use, NOT in `data/synthetic/` (M1's `load_synthetic_directory` concatenates every file there). Also clarifies `attack_start`/`label` semantics: window-level marking — every row inside an injected window carries `attack_start=1` and the scenario label (matches M1/M2 scenario convention). | The M4 brief asks for separate sensor streams, but M1/M2 feature code (dt/sequence continuity, 50-row ≈ 5 s windows) assumes fused 10 Hz rows; interleaved multi-rate rows would break sequence/timestamp semantics. No code change required by anyone — this documents what already ships. A streams migration (v1.1, with per-sensor grouping helpers in M1/M2) can be scheduled separately if the team wants it | PROPOSED |
