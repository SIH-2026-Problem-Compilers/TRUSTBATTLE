"""TRUSTBATTLE — Member 3 configuration loader (settings + contract artifacts).

Loads the M3-owned sections of configs/settings.yaml (``trust_engine:``,
``fusion:``) and the contract artifacts in models/trust/ (data_schema.md §4:

    trust_weights.json   — evidence weights + per-sensor attribution + priors
    fusion_config.json   — fusion mode / min weight / learned-model hook

Mirrors the M1/M2 settings pattern: graceful defaults when the YAML or the
artifacts are missing, cached, zero side effects on import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

try:  # pyyaml is not in the shared requirements.txt; degrade gracefully
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / "configs" / "settings.yaml"
TRUST_DIR = REPO_ROOT / "models" / "trust"
TRUST_WEIGHTS_PATH = TRUST_DIR / "trust_weights.json"
FUSION_CONFIG_PATH = TRUST_DIR / "fusion_config.json"

_SETTINGS_CACHE: Optional[dict] = None
_WEIGHTS_CACHE: Optional[dict] = None
_FUSION_CACHE: Optional[dict] = None


def _deep_get(d: dict, dotted: str, default: Any) -> Any:
    """Fetch a nested value via a dotted path, e.g. 'trust_engine.decay.drop_rate'."""
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def load_settings() -> dict:
    """Load configs/settings.yaml (cached). Returns {} when unavailable."""
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is None:
        if yaml is not None and SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                _SETTINGS_CACHE = yaml.safe_load(fh) or {}
        else:
            _SETTINGS_CACHE = {}
    return _SETTINGS_CACHE


def trust_settings() -> dict:
    """M3 tunables from configs/settings.yaml with code-level defaults.

    Returns:
        {
          "weights": {evidence score name -> weight},   # §12 weighted model seed
          "aggregation": {                             # Step 2 corroboration rules
            "degraded_threshold": float, "min_degraded": int,
            "corroboration_penalty": float, "severe_floor": float,
            "min_attribution": float, "primary_min_attribution": float,
            "cross_extreme_threshold": float,
            "cross_uncorroborated_floor": float},
          "estimator_aiding": {"enabled": bool, "rate": float,
                               "min_disagreement_m": float},
          "decay": {"drop_rate": float, "recovery_rate": float,
                    "recovery_ramp": float, "recovery_max": float,
                    "clean_threshold": float},        # §13 dynamics
          "thresholds": {"green": float, "amber": float},          # §2 alert levels
          "min_sensor_weight": float,                              # fusion floor
          "fusion_mode": "normal" | "trust_aware",
          "corruption_levels_pct": [0, 5, 10, 20, 30],             # §19 experiments
        }
    """
    cfg = load_settings()
    weights = _deep_get(cfg, "trust_engine.weights", {}) or {}
    agg = _deep_get(cfg, "trust_engine.aggregation", {}) or {}
    aid = _deep_get(cfg, "trust_engine.estimator_aiding", {}) or {}
    return {
        "weights": {
            "physical_consistency": float(weights.get("physical_consistency", 0.30)),
            "temporal_consistency": float(weights.get("temporal_consistency", 0.20)),
            "cross_sensor_agreement": float(weights.get("cross_sensor_agreement", 0.25)),
            "network_integrity": float(weights.get("network_integrity", 0.15)),
            "historical_reliability": float(weights.get("historical_reliability", 0.10)),
            "anomaly_physical": float(weights.get("anomaly_physical", 0.05)),
            "anomaly_temporal": float(weights.get("anomaly_temporal", 0.05)),
        },
        "aggregation": {
            "degraded_threshold": float(agg.get("degraded_threshold", 0.75)),
            "min_degraded": int(agg.get("min_degraded", 2)),
            "corroboration_penalty": float(agg.get("corroboration_penalty", 0.92)),
            "severe_floor": float(agg.get("severe_floor", 0.35)),
            "min_attribution": float(agg.get("min_attribution", 0.30)),
            "primary_min_attribution": float(agg.get("primary_min_attribution", 0.55)),
            "primary_blend": float(agg.get("primary_blend", 0.70)),
            "primary_margin": float(agg.get("primary_margin", 0.10)),
            "primary_engage_min": float(agg.get("primary_engage_min", 0.30)),
            "cross_extreme_threshold": float(agg.get("cross_extreme_threshold", 0.35)),
            "cross_uncorroborated_floor": float(agg.get("cross_uncorroborated_floor", 0.72)),
            "cross_max_velocity_gap_mps": float(agg.get("cross_max_velocity_gap_mps", 8.0)),
        },
        "estimator_aiding": {
            "enabled": bool(aid.get("enabled", True)),
            "rate": float(aid.get("rate", 0.35)),
            "min_disagreement_m": float(aid.get("min_disagreement_m", 60.0)),
            "max_velocity_gap_mps": float(aid.get("max_velocity_gap_mps", 8.0)),
        },
        "decay": {
            "drop_rate": float(_deep_get(cfg, "trust_engine.decay.drop_rate", 0.6)),
            "recovery_rate": float(_deep_get(cfg, "trust_engine.decay.recovery_rate", 0.25)),
            "recovery_ramp": float(_deep_get(cfg, "trust_engine.decay.recovery_ramp", 0.5)),
            "recovery_max": float(_deep_get(cfg, "trust_engine.decay.recovery_max", 0.9)),
            "clean_threshold": float(_deep_get(cfg, "trust_engine.decay.clean_threshold", 0.65)),
        },
        "thresholds": {
            "green": float(_deep_get(cfg, "trust_engine.thresholds.green", 70.0)),
            "amber": float(_deep_get(cfg, "trust_engine.thresholds.amber", 40.0)),
        },
        "min_sensor_weight": float(_deep_get(cfg, "fusion.min_sensor_weight", 0.05)),
        "fusion_mode": str(_deep_get(cfg, "fusion.mode", "trust_aware")),
        "corruption_levels_pct": list(
            _deep_get(cfg, "experiments.corruption_levels_pct", [0, 5, 10, 20, 30])
        ),
    }


def load_trust_weights() -> dict:
    """Load models/trust/trust_weights.json, falling back to seeded defaults.

    The artifact is the single source of truth once it exists (created by
    ``python -m member3_trust.src.train``); the settings.yaml seed is the
    fallback so the module works before the artifact is first written.
    """
    global _WEIGHTS_CACHE
    if _WEIGHTS_CACHE is None:
        doc: Optional[dict] = None
        if TRUST_WEIGHTS_PATH.exists():
            try:
                with open(TRUST_WEIGHTS_PATH, "r", encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (json.JSONDecodeError, OSError):
                doc = None
        if doc is None:
            doc = _default_weights_doc()
        _WEIGHTS_CACHE = doc
    return _WEIGHTS_CACHE


def load_fusion_config() -> dict:
    """Load models/trust/fusion_config.json (fallback: settings.yaml + defaults)."""
    global _FUSION_CACHE
    if _FUSION_CACHE is None:
        doc: Optional[dict] = None
        if FUSION_CONFIG_PATH.exists():
            try:
                with open(FUSION_CONFIG_PATH, "r", encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (json.JSONDecodeError, OSError):
                doc = None
        if doc is None:
            s = trust_settings()
            doc = {
                "schema_version": "1.0",
                "mode": s["fusion_mode"],
                "min_sensor_weight": s["min_sensor_weight"],
                "model_type": "trust_proportional",
                "learned_model": None,
            }
        _FUSION_CACHE = doc
    return _FUSION_CACHE


def _default_weights_doc() -> dict:
    """Seed document for trust_weights.json (mirrors configs/settings.yaml).

    The weighted model follows about_project.txt §12 exactly: every evidence
    input — including ``historical_reliability`` (the per-sensor prior, §5) —
    is one term of the weighted mean. Missing evidence (e.g.
    ``cross_sensor_agreement`` until an upstream module emits it) is skipped
    and the remaining weights are renormalized.

    ``sensor_attribution`` routes blame: how strongly each evidence score
    implicates each sensor when it degrades. A low physical-consistency score
    means "the reported position breaks physics" — that implicates GNSS (the
    spoofable absolute reference), not the self-contained IMU, so innocent
    sensors keep high trust while the failing source collapses (§22 story:
    GNSS 28% while IMU 94% / Visual 91%).
    """
    s = trust_settings()
    return {
        "schema_version": "1.0",
        "model_type": "weighted_linear",   # future: "logistic" | "ensemble"
        "learned_model": None,             # path to a learned model when trained
        "weights": s["weights"],
        "sensor_priors": {"gnss": 0.94, "imu": 0.94, "visual": 0.92, "net": 0.95},
        # Rows = evidence inputs (scores 0-1 higher=trustworthy; anomaly scores
        # are inverted before use). Cols = sensors. ``historical_reliability``
        # is the per-sensor prior (§12 includes it in the weighted mean).
        "sensor_attribution": {
            "physical_consistency":   {"gnss": 1.00, "imu": 0.050, "visual": 0.150, "net": 0.050},
            "anomaly_physical":       {"gnss": 0.50, "imu": 0.025, "visual": 0.075, "net": 0.025},
            "temporal_consistency":   {"gnss": 0.30, "imu": 0.600, "visual": 0.600, "net": 0.400},
            "anomaly_temporal":       {"gnss": 0.30, "imu": 0.600, "visual": 0.600, "net": 0.400},
            "network_integrity":      {"gnss": 0.15, "imu": 0.200, "visual": 0.200, "net": 1.000},
            "cross_sensor_agreement": {"gnss": 0.90, "imu": 0.300, "visual": 0.900, "net": 0.200},
            "historical_reliability": {"gnss": 1.00, "imu": 1.000, "visual": 1.000, "net": 1.000},
        },
        "consistency_floor": 0.05,   # evidence quality floor (never fully trusted)
    }


def reset_caches() -> None:
    """Drop cached settings/artifacts (used by tests and the seed script)."""
    global _SETTINGS_CACHE, _WEIGHTS_CACHE, _FUSION_CACHE
    _SETTINGS_CACHE = None
    _WEIGHTS_CACHE = None
    _FUSION_CACHE = None
