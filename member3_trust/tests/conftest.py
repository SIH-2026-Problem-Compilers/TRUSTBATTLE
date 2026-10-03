"""Shared fixtures for member3_trust tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def clean_scores() -> dict:
    """Healthy-evidence scores (schema §2 keys M1/M2 emit)."""
    return {
        "physical_consistency": 0.95,
        "anomaly_physical": 0.05,
        "temporal_consistency": 0.97,
        "anomaly_temporal": 0.03,
        "network_integrity": 0.96,
    }


@pytest.fixture
def spoof_scores() -> dict:
    """GNSS spoof evidence: physical collapses, temporal/network stay clean."""
    return {
        "physical_consistency": 0.10,
        "anomaly_physical": 0.95,
        "temporal_consistency": 0.97,
        "anomaly_temporal": 0.03,
        "network_integrity": 0.96,
    }


@pytest.fixture
def clean_obs() -> dict:
    """Per-sensor positions within a few metres of each other."""
    return {
        "gnss": {"lat": 28.61000, "lon": 77.21000, "velocity": 6.0},
        "imu": {"lat": 28.61002, "lon": 77.21001, "velocity": 6.0},
        "visual": {"lat": 28.61001, "lon": 77.20998, "velocity": 6.0},
    }


@pytest.fixture
def spoof_obs() -> dict:
    """GNSS ~200 m off; imu/visual agree with each other (consensus pair)."""
    return {
        "gnss": {"lat": 28.61180, "lon": 77.21000, "velocity": 11.0},
        "imu": {"lat": 28.61002, "lon": 77.21001, "velocity": 6.0},
        "visual": {"lat": 28.61001, "lon": 77.20998, "velocity": 6.0},
    }
