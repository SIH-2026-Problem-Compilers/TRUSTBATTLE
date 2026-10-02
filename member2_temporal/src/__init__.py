"""TRUSTBATTLE — Member 2 (Temporal & Telemetry/Network Analysis) package.

Public surface (docs/contracts/module_interfaces.md):
    from member2_temporal.src.features import extract_temporal_features
    from member2_temporal.src.temporal_module import score_observation
"""

from .features import FEATURE_COLUMNS, extract_temporal_features  # noqa: F401
from .temporal_module import TemporalScorer, score_observation  # noqa: F401

__all__ = ["extract_temporal_features", "FEATURE_COLUMNS", "score_observation", "TemporalScorer"]
