"""Tests for the TASK 4 score message (contract: score_observation)."""

import numpy as np
import pytest

from member1_physical.src.physical_module import PhysicalScorer, score_observation

EXPECTED_SCORE_KEYS = {"physical_consistency", "anomaly_physical"}
EXPECTED_EVIDENCE_KEYS = {"check", "pass", "detail"}


def _validate_message(msg):
    assert set(msg.keys()) == {"scores", "evidence"}
    assert set(msg["scores"].keys()) == EXPECTED_SCORE_KEYS
    for v in msg["scores"].values():
        assert isinstance(v, float)
        assert 0.0 <= v <= 1.0
    assert isinstance(msg["evidence"], list) and msg["evidence"]
    for e in msg["evidence"]:
        assert set(e.keys()) == EXPECTED_EVIDENCE_KEYS
        assert isinstance(e["check"], str) and e["check"]
        assert isinstance(e["pass"], bool)
        assert isinstance(e["detail"], str) and len(e["detail"]) > 5


def test_score_window_shape(normal_df):
    msg = score_observation(normal_df.head(50))
    _validate_message(msg)


def test_score_single_row_dict(spoof_df):
    row = spoof_df.iloc[500].to_dict()  # inside the attack window
    msg = score_observation(row)
    _validate_message(msg)


def test_score_list_of_dicts(normal_df):
    rows = normal_df.head(5).to_dict("records")
    msg = score_observation(rows)
    _validate_message(msg)


def test_empty_input_raises():
    import pandas as pd
    with pytest.raises(ValueError):
        score_observation(pd.DataFrame())


def test_clean_window_scores_well(normal_df):
    msg = score_observation(normal_df.head(50))
    assert msg["scores"]["physical_consistency"] > 0.7
    velocity_ev = next(e for e in msg["evidence"] if "velocity disagreement" in e["check"])
    assert velocity_ev["pass"] is True


def test_spoof_window_flagged(normal_df, spoof_df):
    clean = score_observation(normal_df.head(50))
    attack = score_observation(spoof_df.iloc[300:350])  # inside spoof window
    _validate_message(attack)
    assert attack["scores"]["physical_consistency"] < clean["scores"]["physical_consistency"]
    assert any(not e["pass"] for e in attack["evidence"])
    # the §7 story must be visible in human-readable evidence
    velocity_ev = next(e for e in attack["evidence"] if "velocity disagreement" in e["check"])
    assert "vs historical max" in velocity_ev["detail"]
    assert velocity_ev["pass"] is False


def test_heuristic_scorer_without_artifacts(normal_df, tmp_path):
    """No artifacts at the given paths -> heuristic path still returns a valid message."""
    scorer = PhysicalScorer(model_path=tmp_path / "none.pkl", scaler_path=tmp_path / "none2.pkl")
    assert scorer.model_available is False
    msg = scorer.score(normal_df.head(50))
    _validate_message(msg)


def test_trained_scorer_ranks_attack_higher(normal_df, spoof_df, trained):
    iso_p, sc_p = trained
    scorer = PhysicalScorer(model_path=iso_p, scaler_path=sc_p)
    assert scorer.model_available is True
    clean = scorer.score(normal_df.head(50))
    attack = scorer.score(spoof_df.iloc[300:350])
    assert attack["scores"]["anomaly_physical"] > clean["scores"]["anomaly_physical"]
    assert attack["scores"]["anomaly_physical"] > 0.5
    _validate_message(attack)
