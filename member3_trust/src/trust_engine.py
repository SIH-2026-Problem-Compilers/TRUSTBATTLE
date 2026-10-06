"""TRUSTBATTLE — Member 3 Observation Trust Engine (TASKS 1, 2, 4).

The core of TRUSTBATTLE (about_project.txt §12–§13, §15–§16): combines
physical, temporal, network, cross-sensor and historical evidence into a
single **Observation Trust Score (0–100)** with dynamic behaviour, per-sensor
trust, fusion weights and a human-readable alert.

Contract (module_interfaces.md, "Owned by Member 3"; data_schema.md §2/§3):

    compute_trust(scores: dict, history: list) -> dict
        scores  — evidence scores from M1/M2 (schema §2 "scores" block);
                  missing keys are skipped (weights renormalized).
        history — prior messages (each may carry a "trust" block) from which
                  the dynamic per-sensor trust state is continued.
        returns {"trust": {...}, "alert": {...}, "evidence": [...]}

Design (documented for the team and the learned-model upgrade path)
-------------------------------------------------------------------
* **Weighted evidence model (§12).** Every evidence input is one term of a
  weighted **geometric** mean — a "no-absolution" combination, exactly in
  the spirit of the §12 example (historical reliability 0.94 with weight
  0.10 included): all evidence must agree for high trust, and one
  catastrophic red flag pulls trust down proportionally to its attribution
  instead of being averaged away. ``*_consistency``/``*_integrity`` scores
  are used as-is; ``anomaly_*`` scores are inverted (1 − value) so every
  term is "0–1, higher = more trustworthy" (schema §3). Weights live in
  models/trust/trust_weights.json (seeded from configs/settings.yaml →
  trust_engine.weights) and can later be replaced by a learned model
  (``model_type``/``learned_model`` fields) without touching callers.
* **Per-sensor attribution.** Evidence scores are observation-level, but
  fusion needs per-sensor trust (§14). An attribution matrix routes blame:
  low physical consistency implicates GNSS (the spoofable absolute
  reference), not the self-contained IMU. This is what produces the §22
  story — GNSS 28% while IMU 94% / Visual 91%.
* **Dynamic trust (§13).** Per-sensor trust moves toward its evidence
  target: FAST when degrading (trust_engine.decay.drop_rate) and SLOWLY when
  recovering (recovery_rate). No permanent blacklist: one clean stretch
  always starts recovery (§13: 95→81→63→41→24 down, 24→38→61→79→92 up).
* **Weakest-link observation trust.** ``observation_trust`` = the minimum
  per-sensor trust. One manipulated measurement that looks legitimate can
  corrupt the whole picture (§1), so a strong single red flag must not be
  averaged away — the weighted-mean consensus is reported separately as
  ``trust.consensus_trust`` for the dashboard.
* **Alert levels (settings trust_engine.thresholds).** GREEN ≥ 70,
  AMBER 40–70, RED < 40. Wording rule (§16): the system reports
  *inconsistent/unreliable observations, potentially consistent with*
  spoofing/malfunction/communication manipulation — it never claims a
  sensor "was hacked".

The module imports with zero side effects.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

from .fusion import latlon_to_xy
from .settings import load_fusion_config, load_trust_weights, trust_settings

# Evidence inputs that are already "higher = trustworthy" (schema §3).
CONSISTENCY_KEYS = (
    "physical_consistency",
    "temporal_consistency",
    "network_integrity",
    "cross_sensor_agreement",
)
# Evidence inputs that are "higher = more anomalous" — inverted before use.
ANOMALY_KEYS = ("anomaly_physical", "anomaly_temporal")
PRIOR_KEY = "historical_reliability"

# Human-readable names for evidence entries (dashboard-facing, §15).
_SCORE_LABELS = {
    "physical_consistency": "Physical consistency",
    "anomaly_physical": "Physical anomaly detector",
    "temporal_consistency": "Temporal consistency",
    "anomaly_temporal": "Temporal anomaly detector",
    "network_integrity": "Network/telemetry integrity",
    "cross_sensor_agreement": "Cross-sensor agreement",
    PRIOR_KEY: "Historical sensor reliability",
}

# Which attack families each degraded evidence family is *potentially
# consistent with* (§4/§16 wording — never "hacked", never attribution).
_CAUSES = {
    "physical": ["GNSS spoofing", "sensor malfunction"],
    "temporal": ["replay / stale data"],
    "network": ["communication manipulation", "network anomaly"],
    "cross_sensor": ["conflicting sensor observations"],
}

_RECOMMENDED = {
    "GREEN": "None — continue routine monitoring.",
    "AMBER": "Increase scrutiny of this observation and cross-check it against independent sources.",
    "RED": "Reduce this observation's influence in fusion and request independent verification.",
}

# Cross-sensor agreement (Layer 5, §11): sensors whose positions agree with
# the majority corroborate each other; the outlier is implicated. Agreement
# decays exponentially with the outlier's distance from the consensus. The
# e-folding scale is calibrated (see docs/reports/m3_evaluation.md) so that
# clean GNSS/IMU/visual jitter (a few metres) keeps agreement ≈ 1 while a
# 150–400 m spoof lands trust in the §13/§22 zone (≈ 20–30).
_CROSS_SCALE_M = 80.0


def evidence_quality(name: str, value: float) -> float:
    """Map any schema-§3 score to a 0–1 "higher = trustworthy" quality.

    Args:
        name: Score name (schema §2 scores block).
        value: Raw score value.

    Returns:
        Quality in [0, 1]; anomaly scores are inverted.
    """
    v = max(0.0, min(1.0, float(value)))
    if name in ANOMALY_KEYS:
        return 1.0 - v
    return v


def _extract_prev_state(history: Optional[List[Any]]) -> Optional[Dict[str, Any]]:
    """Find the most recent trust state in *history* (scans from the end).

    Accepts prior full messages ({"trust": {...}}) or bare trust dicts. The
    engine itself is stateless — all dynamics continue from what callers
    pass back in, so the function stays pure and testable.
    """
    if not history:
        return None
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        block = entry.get("trust", entry)
        if isinstance(block, dict) and isinstance(block.get("sensor_trust"), dict):
            return block
    return None


def _per_sensor_quality(scores: Dict[str, float], doc: dict,
                        overrides: Optional[Dict[str, Dict[str, float]]] = None
                        ) -> Dict[str, float]:
    """Weighted evidence quality per sensor (0–1) from the attribution matrix.

    Missing evidence keys are skipped and remaining weights renormalized;
    with no evidence at all the per-sensor prior is returned unchanged.

    Args:
        scores: Available evidence scores (schema §2 keys, already
            quality-mapped per key by the caller where needed).
        doc: Loaded trust_weights.json document.
        overrides: Optional per-sensor quality replacements, e.g. the derived
            cross-sensor qualities {score_name: {sensor: quality}}; used in
            place of the flat observation-level score for those sensors.

    Returns:
        {sensor: quality in [consistency_floor, 1.0]}.
    """
    weights = doc["weights"]
    attribution = doc["sensor_attribution"]
    priors = doc["sensor_priors"]
    floor = float(doc.get("consistency_floor", 0.05))
    overrides = overrides or {}

    qualities: Dict[str, float] = {}
    for sensor in priors:
        log_num = den = 0.0
        for name, w in weights.items():
            if name == PRIOR_KEY:
                # the prior is one evidence term (§12), attribution 1.0 for all
                attr = float(attribution.get(PRIOR_KEY, {}).get(sensor, 1.0))
                log_num += w * attr * math.log(max(float(priors[sensor]), 1e-6))
                den += w * attr
                continue
            attr = float(attribution.get(name, {}).get(sensor, 0.0))
            if attr <= 0.0:
                continue
            if name in overrides:
                # per-sensor evidence (e.g. derived cross-sensor agreement):
                # sensors the evidence does not apply to (None/absent) are
                # skipped entirely
                ov = overrides[name].get(sensor)
                if ov is None:
                    continue
                q = float(np.clip(ov, 1e-6, 1.0))
            elif name in scores:
                q = max(evidence_quality(name, scores[name]), 1e-6)
            else:
                continue
            log_num += w * attr * math.log(q)
            den += w * attr
        # Weighted GEOMETRIC mean (no-absolution combination): every piece of
        # evidence must agree for high trust, and one catastrophic red flag
        # (§1: a manipulated measurement can look legitimate) pulls the
        # sensor's quality down proportionally to its attribution instead of
        # being averaged away. Clean evidence keeps q ≈ prior.
        q = math.exp(log_num / den) if den > 0 else float(priors[sensor])
        qualities[sensor] = max(floor, min(1.0, q))
    return qualities


def _step(prev: float, target: float, drop_rate: float, recovery_rate: float) -> float:
    """One §13 dynamic-trust step: fast approach when dropping, slow when recovering."""
    alpha = drop_rate if target < prev else recovery_rate
    return prev + alpha * (target - prev)


def _possible_causes(scores: Dict[str, float]) -> List[str]:
    """Human-readable possible causes from the degraded evidence families (§4/§15)."""
    causes: List[str] = []
    phys_bad = (
        ("physical_consistency" in scores and scores["physical_consistency"] < 0.5)
        or ("anomaly_physical" in scores and scores["anomaly_physical"] > 0.5)
    )
    temp_bad = (
        ("temporal_consistency" in scores and scores["temporal_consistency"] < 0.5)
        or ("anomaly_temporal" in scores and scores["anomaly_temporal"] > 0.5)
    )
    net_bad = "network_integrity" in scores and scores["network_integrity"] < 0.5
    cross_bad = (
        "cross_sensor_agreement" in scores and scores["cross_sensor_agreement"] < 0.5
    )
    if phys_bad:
        causes.extend(_CAUSES["physical"])
    if temp_bad:
        causes.extend(_CAUSES["temporal"])
    if net_bad:
        causes.extend(_CAUSES["network"])
    if cross_bad:
        causes.extend(_CAUSES["cross_sensor"])
    # de-duplicated, order-stable
    seen: set = set()
    return [c for c in causes if not (c in seen or seen.add(c))]


def cross_sensor_qualities(observations: Any) -> Optional[Dict[str, float]]:
    """Per-sensor cross-sensor agreement (Layer 5, §11) from position estimates.

    Blame routing must be asymmetric: when GNSS is spoofed it disagrees with
    BOTH imu and visual, but imu/visual agree with each other. Pairwise
    distances alone would punish the innocent sources symmetrically, so the
    best-agreeing pair forms the "consensus" and only sensors OUTSIDE it are
    implicated, proportionally to their distance from it:

        q(sensor) = exp(-d(sensor, consensus) / _CROSS_SCALE_M)

    Clean operation: all pairwise distances are small → every q ≈ 1.
    ~150 m spoof: the spoofed source lands far from the consensus pair →
    q ≈ 0.05 while the consensus members stay at 1.0 (the §22 story:
    GNSS 28% while IMU 94% / Visual 91%).

    Args:
        observations: per-sensor dicts with lat/lon (see fusion._as_obs_list);
            sensors without a position (e.g. "net") are skipped.

    Returns:
        {sensor: quality 0–1} for position sensors, or None when fewer than
        two position sources exist (no cross-sensor evidence derivable).
    """
    from .fusion import _as_obs_list

    obs = [o for o in _as_obs_list(observations)
           if o.get("lat") is not None and o.get("lon") is not None]
    if len(obs) < 2:
        return None
    names = [str(o.get("sensor_id", f"sensor{i}")) for i, o in enumerate(obs)]
    xy = [latlon_to_xy(float(o["lat"]), float(o["lon"]), float(obs[0]["lat"]),
                       float(obs[0]["lon"])) for o in obs]

    def dist(a: int, b: int) -> float:
        return float(math.hypot(xy[a][0] - xy[b][0], xy[a][1] - xy[b][1]))

    # best-agreeing pair = consensus core
    best = min(
        ((dist(i, j), i, j) for i in range(len(obs)) for j in range(i + 1, len(obs))),
        key=lambda t: t[0],
    )
    _, i0, j0 = best
    consensus = {i0, j0}
    quality = {names[i]: 1.0 for i in consensus}
    for i in range(len(obs)):
        if i in consensus:
            continue
        d = min(dist(i, c) for c in consensus)
        quality[names[i]] = float(np.exp(-d / _CROSS_SCALE_M))
    return quality


def compute_trust(scores: Dict[str, float], history: Optional[List[Any]] = None,
                  observations: Any = None) -> Dict[str, Any]:
    """Contract function: evidence scores → observation trust message (§2/§12–§13).

    Args:
        scores: Evidence scores from M1/M2 per data_schema.md §2 —
            any subset of {physical_consistency, anomaly_physical,
            temporal_consistency, anomaly_temporal, network_integrity,
            cross_sensor_agreement}. Missing keys are skipped (weights
            renormalized over the available evidence).
        history: Prior messages/trust dicts; the last one carrying
            ``trust.sensor_trust`` continues the §13 dynamic state. Empty on
            a cold start (per-sensor trust begins at the historical priors).
        observations: Optional per-sensor position/velocity estimates
            ({sensor: {"lat", "lon", "velocity"}} or equivalent). When given
            and ``cross_sensor_agreement`` is absent from *scores*, the engine
            derives it per sensor (Layer 5, §11 — see
            :func:`cross_sensor_qualities`). This is the additive third
            parameter; the two-argument contract call stays valid.

    Returns:
        {"trust": {"observation_trust": 0–100 (weakest-link, dynamic),
                   "sensor_reliability": historical prior baseline 0–100,
                   "sensor_weights": {sensor: weight} (Σ=1, fusion-ready),
                   "sensor_trust": {sensor: 0–100} (dynamic, per sensor),
                   "consensus_trust": 0–100 (weighted-mean diagnostic)},
         "alert": {"level": "GREEN|AMBER|RED", "message": str,
                   "possible_causes": [...], "recommended_action": str},
         "evidence": [{"check", "pass", "detail"}, ...]   (§15 explainability),
         "scores": {schema §2 scores actually used, including any derived
                   cross_sensor_agreement}}
    """
    doc = load_trust_weights()
    cfg = trust_settings()
    fusion_cfg = load_fusion_config()
    scores = {k: float(v) for k, v in (scores or {}).items()}

    # -- optional Layer-5 evidence: derive cross-sensor agreement (§11) ------
    cross_note: Optional[str] = None
    overrides: Dict[str, Dict[str, float]] = {}
    if observations is not None and "cross_sensor_agreement" not in scores:
        cq = cross_sensor_qualities(observations)
        if cq is not None:
            # per-sensor agreement for the POSITION sensors; sensors without a
            # position (e.g. "net") get None = evidence not applicable to them
            overrides["cross_sensor_agreement"] = {
                s: (float(q) if s in cq else None) for s, q in
                {**{k: float(v) for k, v in cq.items()},
                 **{s: None for s in doc["sensor_priors"] if s not in cq}}.items()
            }
            # observation-level score for causes/evidence: the weakest source
            scores["cross_sensor_agreement"] = float(min(cq.values()))
            outlier = min(cq, key=cq.get)
            cross_note = (f"derived from per-sensor estimates (§11): "
                          f"{outlier} is the disagreement outlier (q={cq[outlier]:.2f})")
    priors = doc["sensor_priors"]
    drop_rate = cfg["decay"]["drop_rate"]
    recovery_rate = cfg["decay"]["recovery_rate"]
    min_w = float(fusion_cfg.get("min_sensor_weight", cfg["min_sensor_weight"]))
    green = cfg["thresholds"]["green"]
    amber = cfg["thresholds"]["amber"]

    # -- evidence quality per sensor -----------------------------------------
    quality = _per_sensor_quality(scores, doc, overrides=overrides)

    # -- dynamic per-sensor trust (§13) ---------------------------------------
    prev_state = _extract_prev_state(history)
    prev_trust = (prev_state or {}).get("sensor_trust", {})
    sensor_trust: Dict[str, float] = {}
    for sensor, prior in priors.items():
        prev = float(prev_trust.get(sensor, 100.0 * float(prior)))
        target = 100.0 * quality[sensor]
        sensor_trust[sensor] = round(max(0.0, min(100.0, _step(prev, target, drop_rate, recovery_rate))), 1)

    # -- headline scores -------------------------------------------------------
    # Weakest link (§1): one legitimate-looking manipulated source must be able
    # to flag the observation; consensus (weighted mean) kept as a diagnostic.
    observation_trust = round(min(sensor_trust.values()), 1)
    consensus = round(sum(sensor_trust.values()) / len(sensor_trust), 1)

    # -- fusion weights (§14: influence ∝ current trust, floor, Σ=1) ----------
    raw = {s: max(t / 100.0, min_w) for s, t in sensor_trust.items()}
    total = sum(raw.values())
    sensor_weights = {s: round(w / total, 6) for s, w in raw.items()}

    # -- historical reliability baseline (schema §2 "sensor_reliability") -----
    reliability = round(
        100.0 * sum(float(priors[s]) * sensor_weights[s] for s in priors), 1
    )

    # -- alert (§2 + TASK 4) ----------------------------------------------------
    if observation_trust >= green:
        level = "GREEN"
    elif observation_trust >= amber:
        level = "AMBER"
    else:
        level = "RED"
    causes = _possible_causes(scores)
    if level == "RED":
        message = "INFORMATION INTEGRITY ALERT"
    elif level == "AMBER":
        message = "OBSERVATION INTEGRITY WARNING"
    else:
        message = "Observation trusted"
    if level != "GREEN" and not causes:
        # thresholds crossed without an obvious family — still honest wording
        causes = ["unexplained observation inconsistency"]
    alert = {
        "level": level,
        "message": message,
        "possible_causes": causes,
        "recommended_action": _RECOMMENDED[level],
    }

    # -- evidence entries (§15, dashboard-ready) --------------------------------
    evidence: List[Dict[str, Any]] = []
    attribution = doc["sensor_attribution"]
    for name in list(CONSISTENCY_KEYS) + list(ANOMALY_KEYS):
        if name not in scores:
            if name == "cross_sensor_agreement":
                evidence.append({
                    "check": "Cross-sensor agreement evidence",
                    "pass": True,
                    "detail": "PENDING: not provided by upstream modules yet and no "
                              "observations given — trust derived from physical/temporal/network evidence",
                })
            continue
        q = evidence_quality(name, scores[name])
        if name == "cross_sensor_agreement" and "cross_sensor_agreement" in overrides:
            detail = f"Cross-sensor agreement {cross_note}"
        else:
            top = sorted(
                attribution.get(name, {}).items(), key=lambda kv: kv[1], reverse=True
            )
            blamed = ", ".join(s for s, a in top if a >= 0.5) or "no single sensor"
            detail = f"{_SCORE_LABELS[name]} score {scores[name]:.2f} "
            detail += f"(evidence quality {q:.2f}) — most implicated: {blamed}"
        evidence.append({
            "check": f"{_SCORE_LABELS[name]} evidence",
            "pass": q >= 0.5,
            "detail": detail,
        })
    trend = "dropping" if prev_state and observation_trust < float(prev_state.get("observation_trust", observation_trust)) else (
        "recovering" if prev_state and observation_trust > float(prev_state.get("observation_trust", observation_trust)) else "stable")
    evidence.append({
        "check": "Dynamic trust trend",
        "pass": observation_trust >= amber,
        "detail": f"observation trust {observation_trust:.1f} ({trend}; "
                  f"drop_rate {drop_rate:.2f}, recovery_rate {recovery_rate:.2f} — "
                  "trust degrades fast and recovers gradually, never permanently blacklisted)",
    })
    evidence.append({
        "check": "Fusion influence redistribution",
        "pass": True,
        "detail": "sensor weights " + ", ".join(
            f"{s} {w:.2f}" for s, w in sensor_weights.items()
        ) + " (influence ∝ current observation trust, §14)",
    })

    return {
        "trust": {
            "observation_trust": observation_trust,
            "sensor_reliability": reliability,
            "sensor_weights": sensor_weights,
            "sensor_trust": sensor_trust,
            "consensus_trust": consensus,
        },
        "alert": alert,
        "evidence": evidence,
        # effective scores used for this call — includes values derived here
        # (e.g. cross_sensor_agreement from *observations*) so callers can
        # surface them in the schema §2 scores block
        "scores": scores,
    }
