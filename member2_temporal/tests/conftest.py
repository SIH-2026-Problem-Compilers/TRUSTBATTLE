"""Shared fixtures for member2_temporal tests (schema-v1.0 stand-in data)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import joblib  # noqa: E402
import pytest  # noqa: E402

from member2_temporal.src.fallback_data import (  # noqa: E402
    make_network_anomaly,
    make_normal,
    make_replay,
    make_telemetry_manip,
)


@pytest.fixture(scope="session")
def normal_df():
    """Clean schema-v1.0 track (600 rows = 60 s @ 10 Hz)."""
    return make_normal(600, seed=7)


@pytest.fixture(scope="session")
def replay_df():
    """Replay/stale-data track (600 rows, attack from row 300)."""
    return make_replay(600, start=300, seed=7)


@pytest.fixture(scope="session")
def manip_df():
    """Telemetry-manipulation track (600 rows, attack from row 300)."""
    return make_telemetry_manip(600, start=300, seed=7)


@pytest.fixture(scope="session")
def netanom_df():
    """Network-anomaly track (600 rows, attack from row 300)."""
    return make_network_anomaly(600, start=300, seed=7)


@pytest.fixture(scope="session")
def trained(tmp_path_factory):
    """Train both IF models + scalers on clean data; save under canonical names.

    Returns the artifact directory (loadable via TemporalScorer(model_dir=...)).
    """
    from member2_temporal.src import model as m2_model
    from member2_temporal.src.features import extract_temporal_features

    clean = make_normal(3000, seed=99)
    feat = extract_temporal_features(clean)
    train, holdout = (feat.iloc[:2400].reset_index(drop=True),
                      feat.iloc[2400:].reset_index(drop=True))
    t_iso, t_scaler = m2_model.train_temporal_model(train)
    n_iso, n_scaler = m2_model.train_network_model(train)
    m2_model.calibrate_threshold(t_iso, t_scaler, holdout, fpr_target=0.01)
    m2_model.calibrate_threshold(n_iso, n_scaler, holdout, fpr_target=0.01)

    d = tmp_path_factory.mktemp("artifacts")
    joblib.dump(t_iso, d / "temporal_model.pkl")
    joblib.dump(t_scaler, d / "temporal_scaler.pkl")
    joblib.dump(n_iso, d / "network_model.pkl")
    joblib.dump(n_scaler, d / "network_scaler.pkl")
    return d
