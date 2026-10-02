"""Tests for the TASK 5 score message (contract: score_observation)."""

import numpy as np
import pytest

from member2_temporal.src.temporal_module import TemporalScorer, score_observation

EXPECTED_SCORE_KEYS = {"temporal_consistency", "anomaly_temporal", "network_integrity"}
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


def test_score_single_row_dict(replay_df):
    row = replay_df.iloc[500].to_dict()  # inside the replay window
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
    assert msg["scores"]["temporal_consistency"] > 0.7
    assert msg["scores"]["network_integrity"] > 0.7
    assert all(e["pass"] for e in msg["evidence"])


def test_replay_window_flagged(normal_df, replay_df):
    clean = score_observation(normal_df.head(50))
    # inside the replay window, WITH prior context — a re-delivered block is
    # locally self-consistent, so detection needs the seen-before evidence
    attack = score_observation(replay_df.iloc[320:370], history=replay_df.iloc[200:320])
    _validate_message(attack)
    assert attack["scores"]["temporal_consistency"] < clean["scores"]["temporal_consistency"]
    assert any(not e["pass"] for e in attack["evidence"])
    # the replay story must be visible in human-readable evidence
    freshness = next(e for e in attack["evidence"] if "freshness" in e["check"])
    assert freshness["pass"] is False
    assert "replay" in freshness["detail"].lower()


def test_replay_detected_without_history_via_sticky_staleness(replay_df):
    """Even with no history, a window containing a rewind/duplicate stays suspect.

    The re-delivered frames themselves are locally self-consistent (freshness
    needs cross-window history), but the clock rewinds are in-window evidence.
    """
    attack = score_observation(replay_df.iloc[300:360])  # attack starts at 300
    mono = next(e for e in attack["evidence"] if "monotonicity" in e["check"])
    assert mono["pass"] is False
    assert any(not e["pass"] for e in attack["evidence"])


def test_network_anomaly_window_flagged(normal_df, netanom_df):
    clean = score_observation(normal_df.head(50))
    attack = score_observation(netanom_df.iloc[320:370])  # inside attack window
    _validate_message(attack)
    assert attack["scores"]["network_integrity"] < clean["scores"]["network_integrity"]
    spike = next(e for e in attack["evidence"] if "inter-arrival" in e["check"].lower())
    assert spike["pass"] is False
    # the §10 story must be visible: spike magnitude vs normal baseline
    assert "ms" in spike["detail"] and "normal" in spike["detail"].lower()


def test_clean_track_network_intact(normal_df):
    msg = score_observation(normal_df.head(50))
    spike = next(e for e in msg["evidence"] if "inter-arrival" in e["check"].lower())
    assert spike["pass"] is True


def test_heuristic_scorer_without_artifacts(normal_df, tmp_path):
    """No artifacts in the given dir -> heuristic path still returns a valid message."""
    scorer = TemporalScorer(model_dir=tmp_path / "empty")
    assert scorer.model_available is False
    msg = scorer.score(normal_df.head(50))
    _validate_message(msg)


def test_trained_scorer_ranks_attacks_higher(normal_df, replay_df, netanom_df, trained):
    scorer = TemporalScorer(model_dir=trained)
    assert scorer.model_available is True
    clean = scorer.score(normal_df.head(50))
    replay = scorer.score(replay_df.iloc[320:370])
    netanom = scorer.score(netanom_df.iloc[320:370])
    assert replay["scores"]["anomaly_temporal"] > clean["scores"]["anomaly_temporal"]
    assert replay["scores"]["anomaly_temporal"] > 0.3
    assert netanom["scores"]["network_integrity"] < clean["scores"]["network_integrity"]
    _validate_message(replay)
    _validate_message(netanom)


def test_score_message_summary(normal_df):
    from member2_temporal.src.temporal_module import score_message_summary
    text = score_message_summary(score_observation(normal_df.head(50)))
    assert "temporal_consistency=" in text
