"""Shared fixtures for member1_physical tests (schema-v1.0 stand-in data)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import joblib  # noqa: E402
import pytest  # noqa: E402

from member1_physical.src.fallback_data import make_normal, make_spoof  # noqa: E402


@pytest.fixture(scope="session")
def normal_df():
    """Clean schema-v1.0 track (600 rows = 60 s @ 10 Hz)."""
    return make_normal(600, seed=7)


@pytest.fixture(scope="session")
def spoof_df():
    """GNSS-spoof track (600 rows, attack from row 300)."""
    return make_spoof(600, start=300, seed=7)


@pytest.fixture(scope="session")
def trained(tmp_path_factory):
    """Train IsolationForest + scaler on clean data; return artifact paths."""
    from member1_physical.src import model as m1_model
    from member1_physical.src.features import extract_physical_features

    clean = make_normal(3000, seed=99)
    feat = extract_physical_features(clean)
    train, holdout = feat.iloc[:2400].reset_index(drop=True), feat.iloc[2400:].reset_index(drop=True)
    scaler = m1_model.fit_scaler(train)
    iso = m1_model.train_model(train)
    m1_model.calibrate_threshold(iso, scaler, holdout, fpr_target=0.01)

    d = tmp_path_factory.mktemp("artifacts")
    iso_p, sc_p = d / "iso.pkl", d / "scaler.pkl"
    joblib.dump(iso, iso_p)
    joblib.dump(scaler, sc_p)
    return iso_p, sc_p
