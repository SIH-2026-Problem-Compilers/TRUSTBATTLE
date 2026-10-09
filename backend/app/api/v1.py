from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional

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
        "real_geolife",  # real GPS dataset (data/real/) through the pipeline
        "demo_story",     # §22 demo mode: clean -> spoof -> recovery generator
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


@router.post("/demo/advance/{session_id}")
def advance_scenario(
    session_id: str,
    service: TrustServiceABC = Depends(get_trust_service),
) -> TrustMessage:
    """Advance a playback session one step (used for real-data replay)."""
    msg = service.advance_playback(session_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="session unknown or playback finished")
    return msg


# ---------------------------------------------------------------------------
# real-data endpoints (live device GPS -> M1/M2/M3 pipeline)
# ---------------------------------------------------------------------------
class RealIngestRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    rows: List[Dict[str, Any]]


@router.post("/real/session")
def reset_real_session() -> dict:
    """Start a fresh live-capture session (clears buffer/trajectory)."""
    from backend.app.services.real_data import get_real_session
    get_real_session().reset()
    return {"status": "ok", "source": "real_device_gps"}


@router.post("/real/ingest")
def ingest_real_rows(body: RealIngestRequest) -> dict:
    """Ingest real sensor rows; scores them through the M1->M2->M3 pipeline."""
    from backend.app.services.real_data import get_real_session
    out = get_real_session().add_rows(body.rows)
    return {
        "accepted": out["accepted"],
        "total_rows": out["total_rows"],
        "trust": out["trust"],
        "source": "real_device_gps",
    }


@router.get("/real/trajectory", response_model=TrajectoryResponse)
def get_real_trajectory() -> TrajectoryResponse:
    from backend.app.services.real_data import get_real_session
    return get_real_session().trajectory()


@router.get("/real/datasets")
def list_real_datasets() -> dict:
    from backend.app.services.real_data import list_real_datasets as _list
    return {"datasets": _list(), "dir": "data/real"}


# ---------------------------------------------------------------------------
# TRUSTBATTLE LIVE — controlled live simulation (spec §2–§8, §12, §14)
# ---------------------------------------------------------------------------
@router.get("/live/status")
def live_status() -> dict:
    """Status panel + pipeline panel + event log state for the LIVE screen."""
    from backend.app.services.live_demo import get_live_controller
    return get_live_controller().status()


@router.post("/live/scenario/{scenario}", status_code=status.HTTP_202_ACCEPTED)
def live_set_scenario(scenario: str) -> dict:
    """Set the controlled INPUT scenario (NORMAL / GNSS SPOOF / REPLAY / ...
    / RESET). Only the input data changes — trust is computed by M1→M2→M3."""
    from backend.app.services.live_demo import get_live_controller, SCENARIOS
    ctl = get_live_controller()
    if scenario == "reset":
        out = ctl.reset()
    else:
        if scenario not in SCENARIOS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown live scenario '{scenario}'. Valid: "
                       f"{sorted(SCENARIOS | {'reset'})}")
        out = ctl.set_scenario(scenario)
    ctl.epoch  # expose via ws_stream_state through the trust service
    from backend.app.services import trust_service as ts
    svc = ts.get_trust_service()
    if hasattr(svc, "notify_live_epoch"):
        svc.notify_live_epoch()
    return out


@router.post("/live/auto", status_code=status.HTTP_202_ACCEPTED)
def live_auto() -> dict:
    """▶ RUN LIVE DEMO — automatic NORMAL → GNSS SPOOF → RECOVERY sequence.
    Drives input data only; every trust value is computed by the pipeline."""
    from backend.app.services.live_demo import get_live_controller
    out = get_live_controller().run_auto()
    from backend.app.services import trust_service as ts
    svc = ts.get_trust_service()
    if hasattr(svc, "notify_live_epoch"):
        svc.notify_live_epoch()
    return out


@router.post("/live/step", response_model=TrustMessage)
def live_step() -> TrustMessage:
    """Generate + score one window now (run_live_demo.py / polling clients)."""
    from backend.app.services.live_demo import get_live_controller
    return get_live_controller().step()


@router.get("/live/events")
def live_events(limit: int = Query(100, ge=1, le=500)) -> dict:
    from backend.app.services.live_demo import get_live_controller
    return {"events": get_live_controller().events(limit)}


@router.get("/live/trajectory")
def live_trajectory() -> dict:
    from backend.app.services.live_demo import get_live_controller
    return get_live_controller().trajectory()
