"""Contract-artifact + settings tests (M3)."""

from __future__ import annotations

import json

from member3_trust.src.settings import (
    FUSION_CONFIG_PATH,
    TRUST_WEIGHTS_PATH,
    load_fusion_config,
    load_trust_weights,
    trust_settings,
)


def test_contract_artifacts_exist():
    """DoD #2: trust_weights.json + fusion_config.json exist and parse."""
    assert TRUST_WEIGHTS_PATH.exists(), "run: py -m member3_trust.src.train"
    assert FUSION_CONFIG_PATH.exists(), "run: py -m member3_trust.src.train"
    with open(TRUST_WEIGHTS_PATH, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["schema_version"] == "1.0"
    with open(FUSION_CONFIG_PATH, "r", encoding="utf-8") as fh:
        fcfg = json.load(fh)
    assert fcfg["schema_version"] == "1.0"


def test_weights_match_settings_seed():
    """Weights in the artifact start from configs/settings.yaml → trust_engine."""
    doc = load_trust_weights()
    cfg = trust_settings()
    for key, value in cfg["weights"].items():
        assert abs(doc["weights"][key] - value) < 1e-9, key


def test_weights_and_attribution_wellformed():
    """Every weighted score has an attribution row; priors cover the sensors."""
    doc = load_trust_weights()
    sensors = set(doc["sensor_priors"])
    for name, weight in doc["weights"].items():
        assert weight >= 0.0, name
        row = doc["sensor_attribution"].get(name)
        assert row is not None, f"missing attribution row for {name}"
        assert set(row) == sensors, name
        assert all(a >= 0.0 for a in row.values()), name
    assert doc["model_type"] == "weighted_linear"
    assert 0.0 < doc["consistency_floor"] < 0.5


def test_fusion_config_matches_settings():
    """Fusion artifact mirrors configs/settings.yaml → fusion section."""
    fcfg = load_fusion_config()
    cfg = trust_settings()
    assert fcfg["mode"] == cfg["fusion_mode"]
    assert abs(fcfg["min_sensor_weight"] - cfg["min_sensor_weight"]) < 1e-9


def test_decay_and_thresholds_loaded():
    """§13 decay rates and §2 alert thresholds come from settings.yaml."""
    cfg = trust_settings()
    assert 0 < cfg["decay"]["drop_rate"] <= 1
    assert 0 < cfg["decay"]["recovery_rate"] < cfg["decay"]["drop_rate"]
    assert cfg["thresholds"]["green"] > cfg["thresholds"]["amber"] > 0
    assert cfg["corruption_levels_pct"] == [0, 5, 10, 20, 30]
