"""TRUSTBATTLE — convert the real GeoLife GPS trajectory dataset to schema v1.

Source: Microsoft Research Asia "GeoLife GPS Trajectories 1.3" (182 users,
real phone GPS traces, 2007-2012) — data/raw/geolife.zip.

Output: data/real/geolife.csv, one row = one observation in exactly
docs/contracts/data_schema.md §1 format, so M1/M2 training and the M5
dashboard consume it like any other dataset.

Derivation notes (honestly documented — GeoLife is a GNSS-only source):
  * velocity / heading  -> from consecutive real fixes (bearing + speed)
  * accel_x/y           -> d(velocity)/dt in ENU, clipped to +/-30 m/s^2
  * accel_z             -> 0.0 (no accelerometer in this dataset)
  * gyro_x/y            -> 0.0; gyro_z -> d(heading)/dt in rad/s, clipped
  * gnss_quality        -> 1.0 (raw traces, no accuracy field published)
  * packet_rate/delay   -> real sampling cadence (1 / dt, dt*1000 ms)
  * packet_loss         -> fraction of >10 s gaps in the last 50 rows
  * label/attack_start  -> 0 (clean real-world data: the detectors' TRAIN set)

Selection: round-robin over the 182 users (diverse), long traces only
(MIN_POINTS), capped per user. Derivatives are computed AFTER the global
timestamp sort with segment cuts at trajectory changes and >60 s gaps, and
the first rows after each cut are dropped, so no fake jump ever lands in
the training data.

Usage (from repo root):  py scripts/convert_geolife.py [--target-rows N]
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = REPO_ROOT / "data" / "raw" / "geolife.zip"
OUT_PATH = REPO_ROOT / "data" / "real" / "geolife.csv"

SCHEMA_COLUMNS = [
    "timestamp", "sensor_id", "latitude", "longitude", "altitude",
    "velocity", "vx", "vy", "vz", "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z", "heading", "gnss_quality",
    "packet_rate", "packet_delay_ms", "packet_loss",
    "sequence_number", "label", "attack_start",
]

MAX_DT_S = 60.0         # gap longer than this starts a new segment
MIN_POINTS = 600        # skip short traces (fewer boundaries -> cleaner data)
MAX_MEDIAN_DT = 8.0     # skip ultra-sparse traces
TARGET_PER_USER = 4000  # rows cap per user -> diversity across users
BOUNDARY_TRIM = 10      # rows dropped after each trajectory change
LAPS = 6                # round-robin laps over the user list


def parse_plt(text: str) -> pd.DataFrame | None:
    """Parse one .plt (6 header lines, then lat,lon,0,alt,date,time)."""
    lines = text.splitlines()[6:]
    if len(lines) < MIN_POINTS:
        return None
    lats, lons, alts, ts = [], [], [], []
    for ln in lines:
        parts = ln.split(",")
        if len(parts) < 7:
            continue
        try:
            la, lo, al = float(parts[0]), float(parts[1]), float(parts[3])
            # .plt columns: lat, lon, 0, altitude, days-since-1899, date, time
            date, clock = parts[5], parts[6]
        except ValueError:
            continue
        epoch = pd.Timestamp(f"{date} {clock}").timestamp()
        lats.append(la)
        lons.append(lo)
        alts.append(al)
        ts.append(epoch)
    if len(ts) < MIN_POINTS:
        return None
    df = pd.DataFrame({"lat": lats, "lon": lons, "alt": alts, "timestamp": ts})
    df = df.sort_values("timestamp").reset_index(drop=True)
    dt = df["timestamp"].diff()
    med = float(dt.median())
    if not np.isfinite(med) or med <= 0 or med > MAX_MEDIAN_DT:
        return None
    if (df["lat"] == 0).all() and (df["lon"] == 0).all():
        return None
    return df


def derive_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Ordered raw fixes (+ traj_id) -> schema rows with gap-aware derivatives."""
    n = len(df)
    traj = df["traj_id"].to_numpy()
    dt = df["timestamp"].diff().to_numpy()
    lat = df["lat"].to_numpy()
    lon = df["lon"].to_numpy()
    alt = df["alt"].to_numpy()

    # haversine step distance (metres)
    R = 6371000.0
    dlat = np.radians(np.diff(lat, prepend=lat[0]))
    dlon = np.radians(np.diff(lon, prepend=lon[0]))
    a = (np.sin(dlat / 2) ** 2
         + np.cos(np.radians(lat)) * np.cos(np.radians(np.roll(lat, 1)))
         * np.sin(dlon / 2) ** 2)
    dist = 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    dist[0] = 0.0

    # segment cut: first row, trajectory change, bad or huge dt
    traj_change = traj != np.roll(traj, 1)
    traj_change[0] = True
    seg_cut = traj_change | ~np.isfinite(dt) | (dt <= 0) | (dt > MAX_DT_S)
    dt_safe = np.where(seg_cut | ~np.isfinite(dt) | (dt <= 0), 1.0, dt)

    speed = np.clip(dist / dt_safe, 0.0, 70.0)
    speed[seg_cut] = 0.0

    # bearing (deg, 0 = north)
    y = np.sin(dlon) * np.cos(np.radians(lat))
    x = (np.cos(np.radians(np.roll(lat, 1))) * np.sin(np.radians(lat))
         - np.sin(np.radians(np.roll(lat, 1))) * np.cos(np.radians(lat))
         * np.cos(dlon))
    heading = (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0
    heading[seg_cut] = np.nan
    heading = np.where(np.isfinite(heading), heading, 0.0)

    rad = np.radians(heading)
    vx = speed * np.sin(rad)
    vy = speed * np.cos(rad)

    # ENU accelerations from d(v)/dt, gap-aware
    dvx = np.diff(vx, prepend=vx[0])
    dvy = np.diff(vy, prepend=vy[0])
    ax = np.clip(dvx / dt_safe, -30.0, 30.0)
    ay = np.clip(dvy / dt_safe, -30.0, 30.0)
    ax[seg_cut] = 0.0
    ay[seg_cut] = 0.0

    # heading rate -> gyro_z (rad/s), wrap-aware
    dh = np.diff(heading, prepend=heading[0])
    dh = (dh + 180.0) % 360.0 - 180.0
    gz = np.clip(np.radians(dh / dt_safe), -3.0, 3.0)
    gz[seg_cut] = 0.0

    # real sampling cadence as the "network" channel
    gap10 = (dt > 10.0)
    packet_rate = 1.0 / dt_safe
    packet_delay = np.clip(np.where(seg_cut, 1000.0, dt * 1000.0), 0.0, 60000.0)
    pl = pd.Series(np.nan_to_num(gap10.astype(float)))
    pl = pl.rolling(50, min_periods=1).mean().to_numpy()

    out = pd.DataFrame({
        "timestamp": df["timestamp"].to_numpy(),
        "sensor_id": "geolife_gnss",
        "latitude": lat,
        "longitude": lon,
        "altitude": np.nan_to_num(alt),
        "velocity": speed,
        "vx": vx,
        "vy": vy,
        "vz": np.zeros(n),
        "accel_x": ax,
        "accel_y": ay,
        "accel_z": np.zeros(n),
        "gyro_x": np.zeros(n),
        "gyro_y": np.zeros(n),
        "gyro_z": gz,
        "heading": heading,
        "gnss_quality": np.ones(n),
        "packet_rate": packet_rate,
        "packet_delay_ms": packet_delay,
        "packet_loss": pl,
        "sequence_number": np.zeros(n, dtype=np.int64),
        "label": np.zeros(n, dtype=np.int64),
        "attack_start": np.zeros(n, dtype=np.int64),
        "_traj": traj,
        "_cut": seg_cut,
    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-rows", type=int, default=60_000)
    args = ap.parse_args()

    if not ZIP_PATH.exists():
        print(f"[convert] missing {ZIP_PATH} — download GeoLife 1.3 first")
        return 1

    with zipfile.ZipFile(ZIP_PATH) as zf:
        plt_names = sorted(n for n in zf.namelist() if n.endswith(".plt"))
        print(f"[convert] {len(plt_names)} trajectories in archive")

        by_user: dict[str, list[str]] = {}
        for n in plt_names:
            parts = n.split("/")
            if "Data" in parts:
                user = parts[parts.index("Data") + 1]
            elif len(parts) > 2:
                user = parts[-3]
            else:
                user = n
            by_user.setdefault(user, []).append(n)

        users = sorted(by_user)
        budget: dict[str, int] = {u: 0 for u in users}
        picked: list[tuple[str, pd.DataFrame]] = []
        total = 0
        for _lap in range(LAPS):
            if total >= args.target_rows:
                break
            for user in users:
                if total >= args.target_rows:
                    break
                if budget[user] >= TARGET_PER_USER:
                    continue
                for name in by_user[user]:
                    if total >= args.target_rows or budget[user] >= TARGET_PER_USER:
                        break
                    try:
                        with zf.open(name) as fh:
                            df = parse_plt(fh.read().decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    if df is None:
                        continue
                    picked.append((name, df))
                    total += len(df)
                    budget[user] += len(df)

        n_users = sum(1 for u in users if budget[u] > 0)
        print(f"[convert] selected {len(picked)} trajectories from "
              f"{n_users} users, {total} raw fixes")

    # contiguous trajectory blocks ordered by start time; rows stay inside
    # their own trace (never interleave users), so derivatives are always
    # computed within one real trajectory
    ordered = sorted(picked, key=lambda kv: float(kv[1]["timestamp"].min()))
    frames = []
    for tid, (name, df) in enumerate(ordered):
        d = df.copy()
        d["traj_id"] = tid
        frames.append(d)
    stream = pd.concat(frames, ignore_index=True)

    out = derive_fields(stream)

    # drop boundary rows after every trajectory change (rolling-window context)
    cut = out["_cut"].to_numpy()
    drop = np.zeros(len(out), dtype=bool)
    for i in np.nonzero(cut)[0]:
        drop[i:i + BOUNDARY_TRIM] = True
    out = out.loc[~drop].copy()

    out["sequence_number"] = np.arange(len(out), dtype=np.int64)
    out = out.drop(columns=["_traj", "_cut"]).reset_index(drop=True)
    out = out[SCHEMA_COLUMNS]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"[convert] wrote {OUT_PATH} ({len(out)} rows, {len(SCHEMA_COLUMNS)} cols)")

    # schema gate — refuse to ship a file the loaders would reject
    sys.path.insert(0, str(REPO_ROOT))
    from member1_physical.src import data_loader
    chk = data_loader.load_data(OUT_PATH)
    dur = chk["timestamp"].max() - chk["timestamp"].min()
    print(f"[convert] schema OK | duration {dur / 3600:.1f} h | "
          f"speed mean {chk['velocity'].mean():.1f} max {chk['velocity'].max():.1f} m/s | "
          f"accel |ax| p99 {np.percentile(np.abs(chk['accel_x']), 99):.1f} m/s^2 | "
          f"users {n_users}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
