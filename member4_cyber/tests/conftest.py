"""Shared fixtures for member4_cyber tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def clean():
    """Small clean dataset for attack tests (fast; not the full 6000 rows)."""
    from member4_cyber.src.generate_data import make_clean_dataset
    return make_clean_dataset(n=1200)


@pytest.fixture(scope="session")
def full_clean():
    """The full canonical clean dataset (configs settings)."""
    from member4_cyber.src.generate_data import make_clean_dataset
    return make_clean_dataset()
