"""Tests for the Step-3 replay/stale history context (CR #5).

M2's ``score_observation(window, history=None)`` already supported prior
rows; the integration adapters now pass them (``temporal.context_rows``), so
these tests pin the behaviour the wiring relies on:

* a re-delivered (stale) block is recognized through the "seen-before"
  freshness evidence when the original rows are in *history*;
* clean streams gain no false positives from extra context;
* frames carrying numpy arrays in ``.attrs`` do not crash the concat
  (regression: pd.concat element-wise compares attrs).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from member2_temporal.src.temporal_module import score_observation  # noqa: E402


def _fails(msg):
    return [e["check"] for e in msg["evidence"] if not e["pass"]]


def test_freshness_fires_when_original_is_in_history(replay_df):
    """A stale copy is only recognizable as re-broadcast with prior context.

    Without history the replayed rows are locally self-consistent; with the
    original rows in history the seen-before evidence must fire and push
    temporal_consistency down.
    """
    w0 = 320
    window = replay_df.iloc[w0:w0 + 50]
    history = replay_df.iloc[w0 - 150:w0]          # contains the copy sources
    with_hist = score_observation(window, history=history)
    without = score_observation(window)

    assert "Message freshness (no re-broadcast)" in _fails(with_hist)
    assert with_hist["scores"]["temporal_consistency"] < \
        without["scores"]["temporal_consistency"]
    assert with_hist["scores"]["anomaly_temporal"] > \
        without["scores"]["anomaly_temporal"]


def test_clean_stream_gains_no_false_positive(normal_df):
    """Extra context must not degrade a clean window's evidence."""
    window = normal_df.iloc[150:200]
    history = normal_df.iloc[0:150]
    with_hist = score_observation(window, history=history)
    without = score_observation(window)

    assert all(e["pass"] for e in with_hist["evidence"])
    assert with_hist["scores"]["temporal_consistency"] >= \
        without["scores"]["temporal_consistency"] - 0.02


def test_attrs_bearing_frames_do_not_crash(normal_df):
    """Regression: numpy arrays in .attrs made pd.concat raise
    \"truth value of an array ... is ambiguous\"."""
    window = normal_df.iloc[100:150].copy()
    history = normal_df.iloc[0:100].copy()
    window.attrs["truth_latitude"] = np.arange(50, dtype=float)
    history.attrs["truth_latitude"] = np.arange(100, dtype=float)
    msg = score_observation(window, history=history)
    assert set(msg["scores"]) == {
        "temporal_consistency", "anomaly_temporal", "network_integrity"}
    # caller frames keep their own attrs (never mutated by the scorer)
    assert "truth_latitude" in window.attrs and "truth_latitude" in history.attrs


def test_empty_history_matches_no_history_call(normal_df):
    """history=[] must behave exactly like the original 1-arg call."""
    window = normal_df.iloc[200:250]
    assert score_observation(window, history=pd.DataFrame()) == \
        score_observation(window)
