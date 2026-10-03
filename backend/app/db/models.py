from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    DateTime,
    Index,
)
from sqlalchemy.orm import relationship

from backend.app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DBObservation(Base):
    __tablename__ = "observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    observation_id = Column(String(64), unique=True, index=True, nullable=False)
    sensor_id = Column(String(64), index=True)
    timestamp = Column(Float, index=True)
    created_at = Column(DateTime, default=_utcnow)

    latitude = Column(Float)
    longitude = Column(Float)
    altitude = Column(Float)
    velocity = Column(Float)

    scores = Column(JSON, default=dict)
    raw = Column(JSON, default=dict)

    trust = relationship("DBTrustScore", back_populates="observation", uselist=False,
                         cascade="all, delete-orphan")
    evidences = relationship("DBEvidence", back_populates="observation",
                             cascade="all, delete-orphan")


class DBTrustScore(Base):
    __tablename__ = "trust_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    observation_id_fk = Column(Integer, ForeignKey("observations.id", ondelete="CASCADE"),
                               unique=True)
    observation_trust = Column(Float, index=True)
    sensor_reliability = Column(Float)
    sensor_weights = Column(JSON, default=dict)
    sensor_trust = Column(JSON, default=dict)
    state_estimate = Column(JSON, default=dict)
    level = Column(String(8), index=True)
    alert_message = Column(Text)
    possible_causes = Column(JSON, default=list)
    recommended_action = Column(Text)
    recorded_at = Column(Float, index=True)

    observation = relationship("DBObservation", back_populates="trust")


class DBAlert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(64), unique=True, index=True)
    timestamp = Column(Float, index=True)
    level = Column(String(8), index=True)
    message = Column(Text)
    possible_causes = Column(JSON, default=list)
    observation_id = Column(String(64))
    sensor_id = Column(String(64))
    observation_trust = Column(Float)
    active = Column(Integer, default=1, index=True)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_alerts_active_level", "active", "level"),
    )


class DBEvidence(Base):
    __tablename__ = "evidences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    observation_id_fk = Column(Integer, ForeignKey("observations.id", ondelete="CASCADE"))
    check = Column(String(128))
    pass_ = Column(Integer, name="pass")
    detail = Column(Text)

    observation = relationship("DBObservation", back_populates="evidences")
