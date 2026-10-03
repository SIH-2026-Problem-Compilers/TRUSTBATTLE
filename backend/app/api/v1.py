from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional

from backend.app.core.config import settings
from backend.app.db import get_db
from backend.app.db.repository import (
    get_evidence_for,
    list_alerts,
    list_trust_history,
    store_trust_message,
)
from backend.app.models.schemas import (
    AlertItem,
    EvidenceItem,
    TrajectoryResponse,
    TrustHistoryPoint,
    TrustMessage,
)
from backend.app.services.trust_service import TrustServiceABC, get_trust_service

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "schema_version": "1.0"}


@router.get("/trust/current", response_model=TrustMessage)
def get_current_trust(
    service: TrustServiceABC = Depends(get_trust_service),
    db: Session = Depends(get_db),
) -> TrustMessage:
    msg = service.get_current_trust()
    try:
        if msg.observation_id:
            store_trust_message(db, msg)
    except Exception:
        pass
    return msg


@router.get("/trust/history", response_model=List[TrustHistoryPoint])
def get_trust_history(
    sensor_id: Optional[str] = Query(None, description="Filter by sensor id"),
    limit: int = Query(500, ge=1, le=10000),
    service: TrustServiceABC = Depends(get_trust_service),
    db: Session = Depends(get_db),
) -> List[TrustHistoryPoint]:
    try:
        stored = list_trust_history(db, sensor_id=sensor_id, limit=limit)
        if stored:
            return stored
    except Exception:
        pass
    return service.get_trust_history(sensor_id=sensor_id, limit=limit)


@router.get("/evidence/{observation_id}", response_model=List[EvidenceItem])
def get_evidence(
    observation_id: str,
    service: TrustServiceABC = Depends(get_trust_service),
    db: Session = Depends(get_db),
) -> List[EvidenceItem]:
    try:
        stored = get_evidence_for(db, observation_id)
        if stored:
            return stored
    except Exception:
        pass
    return service.get_evidence(observation_id)


@router.get("/alerts", response_model=List[AlertItem])
def get_alerts(
    active_only: bool = Query(True, description="Return only recent/active alerts"),
    limit: int = Query(100, ge=1, le=1000),
    service: TrustServiceABC = Depends(get_trust_service),
    db: Session = Depends(get_db),
) -> List[AlertItem]:
    try:
        stored = list_alerts(db, active_only=active_only, limit=limit)
        if stored:
            return stored
    except Exception:
        pass
    return service.get_alerts(active_only=active_only, limit=limit)


@router.get("/trajectory", response_model=TrajectoryResponse)
def get_trajectory(
    scenario: Optional[str] = Query(None, description="Scenario name to load"),
    service: TrustServiceABC = Depends(get_trust_service),
) -> TrajectoryResponse:
    return service.get_trajectory(scenario=scenario)


@router.post("/demo/attack/{scenario}", status_code=status.HTTP_202_ACCEPTED)
def start_attack_scenario(
    scenario: str,
    service: TrustServiceABC = Depends(get_trust_service),
) -> dict:
    valid_scenarios = {
        "normal", "gnss_spoof", "replay", "telemetry_manip",
        "network_anomaly", "sensor_malfunction", "cross_sensor_conflict",
        "mixed_c05", "mixed_c10", "mixed_c20", "mixed_c30",
    }
    if scenario not in valid_scenarios:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{scenario}'. Valid: {sorted(valid_scenarios)}",
        )
    return service.start_attack_scenario(scenario)


@router.post("/demo/stop/{session_id}", status_code=status.HTTP_200_OK)
def stop_scenario(
    session_id: str,
    service: TrustServiceABC = Depends(get_trust_service),
) -> dict:
    service.stop_playback(session_id)
    return {"status": "stopped", "session_id": session_id}
