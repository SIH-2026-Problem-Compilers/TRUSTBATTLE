"""TRUSTBATTLE — end-to-end pipeline wiring (M1+M2 -> M3 -> JSON for M5).

Registers member implementations into integration/interfaces.py and provides
run_observation(): one observation/window in -> full trust message out.
Members extend this file together as their modules land.
"""

from __future__ import annotations

from typing import Any, Dict

from integration import interfaces


def register_available_implementations() -> None:
    """Import member modules that exist and register their functions.

    Import defensively so the pipeline still runs with missing members
    (their interfaces raise ModuleNotReadyError on use).
    """
    try:
        from member1_physical.src.physical_module import score_observation as m1_score
        from member1_physical.src.features import extract_physical_features
        interfaces.register("score_physical", m1_score)
        interfaces.register("extract_physical_features", extract_physical_features)
    except ImportError:
        pass  # M1 not ready

    try:
        from member2_temporal.src.temporal_module import score_observation as m2_score
        from member2_temporal.src.features import extract_temporal_features
        interfaces.register("score_temporal", m2_score)
        interfaces.register("extract_temporal_features", extract_temporal_features)
    except ImportError:
        pass  # M2 not ready

    try:
        from member3_trust.src.trust_engine import compute_trust
        from member3_trust.src.fusion import fuse
        interfaces.register("compute_trust", compute_trust)
        interfaces.register("fuse", fuse)
    except ImportError:
        pass  # M3 not ready


register_available_implementations()


def run_observation(window_df) -> Dict[str, Any]:
    """One observation window -> full inter-module message (data_schema.md §2).

    Returns the message with whatever stages are ready; missing stages
    appear as {"status": "module_not_ready"}.
    """
    message: Dict[str, Any] = {"schema_version": "1.0"}

    for stage, scorer in (("physical", interfaces.score_physical),
                          ("temporal", interfaces.score_temporal)):
        try:
            out = scorer(window_df)  # one call: scores + evidence from the same run
            message.setdefault("scores", {}).update(out.get("scores", {}))
            message.setdefault("evidence", []).extend(out.get("evidence", []))
        except interfaces.ModuleNotReadyError:
            message[f"{stage}_status"] = "module_not_ready"

    try:
        trust_result = interfaces.compute_trust(message.get("scores", {}), history=[])
        message.setdefault("trust", {}).update(trust_result.get("trust", {}))
        message.setdefault("alert", {}).update(trust_result.get("alert", {}))
    except interfaces.ModuleNotReadyError:
        message["trust_status"] = "module_not_ready"

    return message
