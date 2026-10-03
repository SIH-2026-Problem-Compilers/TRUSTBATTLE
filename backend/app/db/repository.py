from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.db.models import (
    DBAlert,
    DBEvidence,
    DBObservation,
    DBTrustScore,
)
from backend.app.models.schemas import (
    AlertItem,
    EvidenceItem,
    TrustHistoryPoint,
    TrustMessage,
)


def store_trust_message(db: Session, msg: TrustMessage) -> DBObservation:
    existing = db.query(DBObservation).filter_by(observation_id=msg.observation_id or "").first()
    if existing:
        return existing

    obs = DBObservation(
        observation_id=msg.observation_id or f"obs_{id(msg)}",
        sensor_id=msg.sensor_id,
        timestamp=msg.timestamp,
        scores=msg.scores.model_dump(exclude_none=True),
        raw=msg.model_dump(mode="json"),
    )
    if msg.trust.state_estimate:
        se = msg.trust.state_estimate
        obs.latitude = se.get("lat")
        obs.longitude = se.get("lon")
        obs.altitude = se.get("altitude")
        obs.velocity = se.get("velocity")
    db.add(obs)
    db.flush()

    ts = DBTrustScore(
        observation_id_fk=obs.id,
        observation_trust=msg.trust.observation_trust,
        sensor_reliability=msg.trust.sensor_reliability,
        sensor_weights=dict(msg.trust.sensor_weights),
        sensor_trust=dict(msg.trust.sensor_trust or {}),
        state_estimate=dict(msg.trust.state_estimate),
        level=msg.alert.level,
        alert_message=msg.alert.message,
        possible_causes=list(msg.alert.possible_causes),
        recommended_action=msg.alert.recommended_action,
        recorded_at=msg.timestamp,
    )
    db.add(ts)

    for ev in msg.evidence:
        db.add(DBEvidence(
            observation_id_fk=obs.id,
            check=ev.check,
            pass_=1 if ev.pass_ else 0,
            detail=ev.detail,
        ))

    if msg.alert.level in ("AMBER", "RED"):
        import uuid as _uuid
        db.add(DBAlert(
            alert_id=f"alert_{_uuid.uuid4().hex[:10]}",
            timestamp=msg.timestamp or 0.0,
            level=msg.alert.level,
            message=msg.alert.message,
            possible_causes=list(msg.alert.possible_causes),
            observation_id=msg.observation_id,
            sensor_id=msg.sensor_id,
            observation_trust=msg.trust.observation_trust,
            active=1,
        ))

    db.commit()
    return obs


def list_trust_history(
    db: Session,
    sensor_id: Optional[str] = None,
    limit: int = 500,
) -> List[TrustHistoryPoint]:
    q = db.query(DBTrustScore, DBObservation).join(
        DBObservation, DBObservation.id == DBTrustScore.observation_id_fk
    ).order_by(DBTrustScore.recorded_at.desc())
    if sensor_id:
        q = q.filter(DBObservation.sensor_id == sensor_id)
    rows = q.limit(limit).all()
    result: List[TrustHistoryPoint] = []
    for ts, obs in rows:
        result.append(TrustHistoryPoint(
            timestamp=ts.recorded_at or obs.timestamp or 0.0,
            observation_trust=ts.observation_trust or 0.0,
            sensor_id=obs.sensor_id,
            level=ts.level,
            sensor_weights=dict(ts.sensor_weights or {}),
        ))
    return list(reversed(result))


def get_evidence_for(db: Session, observation_id: str) -> List[EvidenceItem]:
    obs = db.query(DBObservation).filter_by(observation_id=observation_id).first()
    if not obs:
        return []
    return [
        EvidenceItem(
            check=e.check,
            pass_=bool(e.pass_),
            detail=e.detail,
        )
        for e in obs.evidences
    ]


def list_alerts(db: Session, active_only: bool = True, limit: int = 100) -> List[AlertItem]:
    q = db.query(DBAlert).order_by(DBAlert.timestamp.desc())
    if active_only:
        q = q.filter(DBAlert.active == 1)
    rows = q.limit(limit).all()
    return [
        AlertItem(
            id=a.alert_id,
            timestamp=a.timestamp,
            level=a.level,
            message=a.message,
            possible_causes=list(a.possible_causes or []),
            observation_id=a.observation_id,
            sensor_id=a.sensor_id,
            observation_trust=a.observation_trust,
        )
        for a in rows
    ]
