"""TRUSTBATTLE — Member 4 shared schema constants (data_schema.md §1, verbatim).

Single source of truth for M4's generator, validator and tests. The contract
itself lives in docs/contracts/data_schema.md (read-only for M4) — changes go
through docs/contracts/CHANGE_REQUESTS.md.
"""

from __future__ import annotations

COLUMNS: list[str] = [
    "timestamp", "sensor_id", "latitude", "longitude", "altitude",
    "velocity", "vx", "vy", "vz",
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "heading", "gnss_quality",
    "packet_rate", "packet_delay_ms", "packet_loss", "sequence_number",
    "label", "attack_start",
]

FLOAT_COLUMNS = [
    "timestamp", "latitude", "longitude", "altitude",
    "velocity", "vx", "vy", "vz",
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "heading", "gnss_quality",
    "packet_rate", "packet_delay_ms", "packet_loss",
]
INT_COLUMNS = ["sequence_number", "label", "attack_start"]

LABEL_NAMES: dict[int, str] = {
    0: "normal",
    1: "gnss_spoof",
    2: "replay",
    3: "telemetry_manip",
    4: "network_anomaly",
    5: "sensor_malfunction",
    6: "cross_sensor_conflict",
}
VALID_LABELS = set(LABEL_NAMES)

GROUND_TRUTH_COLUMNS = ["timestamp", "sensor_id", "label", "attack_start"]

# Attack-type blocks used by the mixed-corruption datasets (§19 experiments),
# cycled in this order so every corruption level contains all six families.
MIXED_ATTACK_CYCLE = ["gnss_spoof", "replay", "telemetry_manipulation",
                      "network_anomaly", "sensor_malfunction",
                      "cross_sensor_conflict"]
