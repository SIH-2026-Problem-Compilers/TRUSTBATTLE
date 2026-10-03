"""TRUSTBATTLE — Member 4 dataset builder (TASKS 1+3, DoD #1/#2).

Generates the team's datasets in one deterministic run (seed 42):

    data/synthetic/uav_normal_v1.parquet               clean fused 10 Hz track
    data/attacks/scenario_<attack>.parquet             6 single-attack scenarios
    data/attacks/scenario_<attack>_ground_truth.csv    §5 per-row truth pairs
    data/attacks/scenario_mixed_c<NN>.parquet (+ .csv) 5/10/20/30% corruption
    member4_cyber/scenarios/uav_normal_v1_streams.parquet   per-sensor variant
    data/synthetic/README.md                           dataset description

Then runs validate_dataset.py over everything and writes
docs/reports/m4_dataset_reports.md. Reproducible: re-running produces
byte-identical datasets.

Usage (from repo root):
    py -m member4_cyber.src.build_datasets
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):  # pragma: no cover
        pass

import pandas as pd  # noqa: E402

from member4_cyber.src.attack_simulator import ATTACKS, attack_mixed  # noqa: E402
from member4_cyber.src.generate_data import (  # noqa: E402
    make_clean_dataset,
    make_streams_variant,
    simulation_settings,
)
from member4_cyber.src.schema import LABEL_NAMES  # noqa: E402
from member4_cyber.src.validate_dataset import main as validate_main  # noqa: E402

SYNTH_DIR = REPO_ROOT / "data" / "synthetic"
ATTACK_DIR = REPO_ROOT / "data" / "attacks"
SCEN_DIR = REPO_ROOT / "member4_cyber" / "scenarios"
MIXED_LEVELS = (5, 10, 20, 30)


def _writable(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of *df* without ``attrs`` (pyarrow cannot serialize ndarray attrs;
    parquet round-trips drop them anyway — truth is reconstructible from the
    seed via ``generate_data.simulate_truth``)."""
    out = df.copy()
    out.attrs = {}
    return out


def _save_pair(directory: Path, name: str, df: pd.DataFrame) -> None:
    """Write ``<name>.parquet`` + its §5 ``<name>_ground_truth.csv`` pair."""
    directory.mkdir(parents=True, exist_ok=True)
    _writable(df).to_parquet(directory / f"{name}.parquet", index=False)
    df[["timestamp", "sensor_id", "label", "attack_start"]].to_csv(
        directory / f"{name}_ground_truth.csv", index=False)


def write_synthetic_readme(s: Dict) -> None:
    """Describe the synthetic dataset (data/synthetic/README.md)."""
    lines = [
        "# data/synthetic/ — Clean UAV Telemetry (Member 4)",
        "",
        "**`uav_normal_v1.parquet`** — the canonical clean dataset (label 0 everywhere).",
        "",
        "| Property | Value |",
        "|---|---|",
        f"| Rows | {int(s['duration_s'] * s['fs'])} (one row = one platform observation tick) |",
        f"| Duration / rate | {s['duration_s']:.0f} s @ {s['fs']:.0f} Hz |",
        f"| Sensor | `sensor_id = '{s['uav_id']}'` (fused platform stream, schema v1.0) |",
        f"| Mission | multi-leg UAV flight: straight legs, coordinated turns (≤12°/s), one climb to 160 m, speed 12–24 m/s, wide cruise circle |",
        f"| GNSS | position noise σ {s['gnss_noise_std_m']} m, quality ~0.95 |",
        f"| IMU | accel/gyro = true kinematics + noise (σ {s['imu_accel_noise_std']}/{s['imu_gyro_noise_std']}), consistent with reported velocity |",
        "| Telemetry | ~100 pps, ~20 ms delay, no loss |",
        f"| Seed | {s['seed']} — bit-reproducible via `py -m member4_cyber.src.build_datasets` |",
        "",
        "Truth position/velocity are carried in `DataFrame.attrs` "
        "(`truth_latitude`, `truth_longitude`, `truth_velocity`) for evaluation —",
        "they are NOT schema columns. Ground truth for attacks: see `data/attacks/` "
        "(`scenario_*_ground_truth.csv`, data_schema.md §5).",
        "",
        "Attack scenarios live in `data/attacks/`; per-scenario descriptions in",
        "`member4_cyber/docs/threat_model.md`; validation in",
        "`docs/reports/m4_dataset_reports.md`.",
        "",
        "NOTE: keep this folder to the canonical file only — Member loaders",
        "concatenate every parquet/csv here.",
    ]
    (SYNTH_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """Build every dataset, then validate; returns 0 iff all valid."""
    print("=" * 64)
    print("TRUSTBATTLE M4 — building the team's datasets (TASKS 1+3)")
    print("=" * 64)
    s = simulation_settings()
    clean = make_clean_dataset()
    print(f"[build] clean track: {len(clean)} rows "
          f"({s['duration_s']:.0f} s @ {s['fs']:.0f} Hz, seed {s['seed']})")

    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    _writable(clean).to_parquet(SYNTH_DIR / "uav_normal_v1.parquet", index=False)
    # extra clean support missions (different sensor-noise seeds, same route
    # family) so downstream holdout calibration sees ~100 windows instead of
    # ~24 — the max-of-window-means threshold needs that tail sample
    for extra_seed in (43, 44, 45):
        sup = make_clean_dataset(seed=extra_seed)
        _writable(sup).to_parquet(SYNTH_DIR / f"uav_normal_v1_seed{extra_seed}.parquet", index=False)
    write_synthetic_readme(s)
    print(f"[build] data/synthetic/uav_normal_v1.parquet (+3 support seeds)  ✓ (team unblocked)")

    built: List[str] = []
    for name, fn in ATTACKS.items():
        df, info = fn(clean, seed=s["seed"])
        _save_pair(ATTACK_DIR, f"scenario_{name}", df)
        built.append(f"scenario_{name}")
        print(f"[build] scenario_{name}: {info['rows_attacked']} attacked rows "
              f"(label {info['label']} = {info['label_name']}, {len(info['windows'])} window(s))")

    for pct in MIXED_LEVELS:
        df, info = attack_mixed(clean, float(pct), seed=s["seed"])
        _save_pair(ATTACK_DIR, f"scenario_mixed_c{pct:02d}", df)
        built.append(f"scenario_mixed_c{pct:02d}")
        print(f"[build] scenario_mixed_c{pct:02d}: {info['rows_attacked']} corrupted rows "
              f"({info['params']['realized_pct']}%), types={list(info['params']['rows_by_type'])}")

    # per-sensor streams variant (M4 brief) — reference copy in OUR scenarios dir
    SCEN_DIR.mkdir(parents=True, exist_ok=True)
    streams = make_streams_variant(clean, s)
    _writable(streams).to_parquet(SCEN_DIR / "uav_normal_v1_streams.parquet", index=False)
    print(f"[build] member4_cyber/scenarios/uav_normal_v1_streams.parquet: "
          f"{len(streams)} per-sensor rows "
          f"({streams['sensor_id'].nunique()} streams: "
          f"{sorted(streams['sensor_id'].unique())})")

    print(f"[build] {len(built) + 1} dataset file(s) written; validating...")
    rc = validate_main([str(SYNTH_DIR / "uav_normal_v1.parquet")]
                       + [str(ATTACK_DIR / f"{n}.parquet") for n in built])
    print("[build] DONE — Members 1–3 are unblocked."
          if rc == 0 else "[build] DONE WITH VALIDATION FAILURES — see above.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
