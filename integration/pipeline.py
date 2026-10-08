"""TRUSTBATTLE — end-to-end pipeline wiring (M1+M2 -> M3 -> JSON for M5).

Registers member implementations into integration/interfaces.py and provides
run_observation(): one observation/window in -> full trust message out.
Members extend this file together as their modules land.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from integration import interfaces

_CONTEXT_ROWS: Optional[int] = None


def temporal_context_rows() -> int:
    """Rows of preceding stream data callers should pass to M2 as history.

    Tunable: ``configs/settings.yaml → temporal.context_rows`` (default 150 —
    covers the 12 s replay re-delivery, ``attacks.replay.delay_s`` = 121 ticks
    @10 Hz, so the replay "seen-before" freshness evidence can fire across
    window boundaries; CR #5).
    """
    global _CONTEXT_ROWS
    if _CONTEXT_ROWS is None:
        rows = 150
        try:
            from pathlib import Path
            import yaml
            path = Path(__file__).resolve().parents[1] / "configs" / "settings.yaml"
            if path.exists():
                with open(path, "r", encoding="utf-8") as fh:
                    cfg = yaml.safe_load(fh) or {}
                rows = int((cfg.get("temporal") or {}).get("context_rows", rows))
        except Exception:  # config unreadable -> safe default
            pass
        _CONTEXT_ROWS = max(0, rows)
    return _CONTEXT_ROWS


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


def score_window(window_df, prior_rows=None) -> Dict[str, Any]:
    """M1 + M2 scores/evidence for one window (trust NOT computed here).

    Thin composition of the two scoring adapters so streaming callers pass
    the same context to M2 everywhere:

    Args:
        window_df: One observation window (schema §1 rows).
        prior_rows: Preceding rows of the same stream, forwarded to M2 as
            ``history`` (replay/stale "seen-before" evidence — see
            :func:`temporal_context_rows`, CR #5). None keeps the original
            no-context call.

    Returns:
        ``{"scores": {...}, "evidence": [...]}`` plus
        ``<stage>_status: "module_not_ready"`` entries for missing modules
        (same degradation contract as :func:`run_observation`).
    """
    scores: Dict[str, Any] = {}
    evidence: list = []
    status: Dict[str, str] = {}
    try:
        out = interfaces.score_physical(window_df)
        scores.update(out.get("scores", {}))
        evidence.extend(out.get("evidence", []))
    except interfaces.ModuleNotReadyError:
        status["physical_status"] = "module_not_ready"
    try:
        out = interfaces.score_temporal(window_df, history=prior_rows)
        scores.update(out.get("scores", {}))
        evidence.extend(out.get("evidence", []))
    except interfaces.ModuleNotReadyError:
        status["temporal_status"] = "module_not_ready"
    return {"scores": scores, "evidence": evidence, **status}


def run_observation(window_df, prior_rows=None) -> Dict[str, Any]:
    """One observation window -> full inter-module message (data_schema.md §2).

    Returns the message with whatever stages are ready; missing stages
    appear as {"status": "module_not_ready"}. *prior_rows* (optional preceding
    stream rows) is forwarded to M2 as history — see :func:`score_window`.
    """
    message: Dict[str, Any] = {"schema_version": "1.0"}

    scored = score_window(window_df, prior_rows=prior_rows)
    message.setdefault("scores", {}).update(scored.get("scores", {}))
    message.setdefault("evidence", []).extend(scored.get("evidence", []))
    for key, val in scored.items():
        if key.endswith("_status"):
            message[key] = val

    try:
        trust_result = interfaces.compute_trust(message.get("scores", {}), history=[])
        message.setdefault("trust", {}).update(trust_result.get("trust", {}))
        message.setdefault("alert", {}).update(trust_result.get("alert", {}))
    except interfaces.ModuleNotReadyError:
        message["trust_status"] = "module_not_ready"

    return message
