"""TRUSTBATTLE — Cross-module interface stubs.

These are the ONLY approved import points between member modules.
Keep the signatures EXACTLY as agreed in docs/contracts/module_interfaces.md.

Members implement their side in their own folder; the implementations
registered here simply delegate. Until a member ships, their stub raises
ModuleNotReadyError so callers fail loudly and clearly.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

_REGISTRY: Dict[str, Callable] = {}
MISSING: set[str] = {
    "extract_physical_features",   # Member 1
    "score_physical",              # Member 1
    "extract_temporal_features",   # Member 2
    "score_temporal",              # Member 2
    "compute_trust",               # Member 3
    "fuse",                        # Member 3
}


class ModuleNotReadyError(ImportError):
    """Raised when a member's implementation is not registered yet."""


def register(name: str, fn: Callable) -> None:
    """Register a member implementation, e.g. in integration/pipeline.py setup."""
    _REGISTRY[name] = fn
    MISSING.discard(name)


def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    fn = _REGISTRY.get(name)
    if fn is None:
        raise ModuleNotReadyError(
            f"'{name}' is not implemented yet. Owner must register it in integration/."
        )
    return fn(*args, **kwargs)


# ---- Member 1: Physical & Sensor Analysis ---------------------------------
def extract_physical_features(df):
    """M1: df -> df with physical feature columns (contract signature)."""
    return _call("extract_physical_features", df)


def score_physical(row_or_window) -> Dict[str, Any]:
    """M1: -> {"scores": {...}, "evidence": [...]} per data_schema.md §2."""
    return _call("score_physical", row_or_window)


# ---- Member 2: Temporal & Telemetry Analysis ------------------------------
def extract_temporal_features(df):
    """M2: df -> df with temporal/network feature columns."""
    return _call("extract_temporal_features", df)


def score_temporal(window_df) -> Dict[str, Any]:
    """M2: -> {"scores": {...}, "evidence": [...]} per data_schema.md §2."""
    return _call("score_temporal", window_df)


# ---- Member 3: Trust Engine & Fusion --------------------------------------
def compute_trust(scores: Dict[str, float], history: List[Dict[str, Any]],
                  observations: Any = None) -> Dict[str, Any]:
    """M3: scores dict -> {"trust": {...}, "alert": {...}} per data_schema.md §2.

    ``observations`` is M3's additive optional third parameter (per-sensor
    position/velocity estimates used to derive cross-sensor agreement, §11).
    The two-argument contract call stays valid; ``None`` means "not supplied".
    """
    return _call("compute_trust", scores, history, observations=observations)


def fuse(observations, trust_scores) -> Dict[str, Any]:
    """M3: -> state_estimate per data_schema.md §2."""
    return _call("fuse", observations, trust_scores)
