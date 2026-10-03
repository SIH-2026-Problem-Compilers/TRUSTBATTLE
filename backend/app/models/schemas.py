from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Scores(BaseModel):
    model_config = ConfigDict(extra="allow")
    physical_consistency: Optional[float] = None
    anomaly_physical: Optional[float] = None
    temporal_consistency: Optional[float] = None
    anomaly_temporal: Optional[float] = None
    network_integrity: Optional[float] = None
    cross_sensor_agreement: Optional[float] = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    check: str
    pass_: bool = Field(..., alias="pass")
    detail: Optional[str] = None


class TrustData(BaseModel):
    model_config = ConfigDict(extra="allow")
    observation_trust: float = 0.0
    sensor_reliability: Optional[float] = None
    sensor_weights: Dict[str, float] = Field(default_factory=dict)
    state_estimate: Dict[str, Any] = Field(default_factory=dict)
    sensor_trust: Optional[Dict[str, float]] = None
    consensus_trust: Optional[float] = None


class AlertData(BaseModel):
    model_config = ConfigDict(extra="allow")
    level: str = "GREEN"
    message: str = "Observations within normal integrity bounds."
    possible_causes: List[str] = Field(default_factory=list)
    recommended_action: Optional[str] = None


class TrustMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = "1.0"
    observation_id: Optional[str] = None
    sensor_id: Optional[str] = None
    timestamp: Optional[float] = None
    scores: Scores = Field(default_factory=Scores)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    trust: TrustData = Field(default_factory=TrustData)
    alert: AlertData = Field(default_factory=AlertData)
    status: Optional[str] = None


class AlertItem(BaseModel):
    id: str
    timestamp: float
    level: str
    message: str
    possible_causes: List[str] = Field(default_factory=list)
    observation_id: Optional[str] = None
    sensor_id: Optional[str] = None
    observation_trust: Optional[float] = None


class TrustHistoryPoint(BaseModel):
    timestamp: float
    observation_trust: float
    sensor_id: Optional[str] = None
    level: Optional[str] = None
    sensor_weights: Optional[Dict[str, float]] = None


class TrajectoryPoint(BaseModel):
    timestamp: float
    lat: float
    lon: float
    velocity: Optional[float] = None
    altitude: Optional[float] = None


class TrajectoryResponse(BaseModel):
    true_trajectory: List[TrajectoryPoint] = Field(default_factory=list)
    reported_trajectory: List[TrajectoryPoint] = Field(default_factory=list)
    fused_trajectory: List[TrajectoryPoint] = Field(default_factory=list)
    scenario: Optional[str] = None
