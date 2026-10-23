"""Canonical student-game release configuration.

The released game is the ten-year representative-day release: one scenario
package of five representative days (120 one-hour periods) shared by all six
submissions (three weeks x two submissions).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CANONICAL_RELEASE = "representative"
CANONICAL_SCENARIO_PACKAGE = "data/processed/activsg2000_representative_v1"
CANONICAL_RULES = "data/teaching/dispatch_scoring_rules_representative_v1.json"
CANONICAL_RELEASE_CONFIG = "data/teaching/game_release_representative_v1.json"
CANONICAL_TIME_STEP_HOURS = 1
CANONICAL_HORIZON = 120
CANONICAL_STORAGE_BOUNDARY_MODE = "daily_exact_cycle"
CANONICAL_MAX_GENERATOR_TO_CONNECTION_RATIO = 0.5
# Daily run-hour budget of team generators (h x G MWh per representative day).
CANONICAL_GENERATOR_DAILY_ENERGY_HOURS = 2.0
CANONICAL_GENERATOR_CAPITAL_COST_PER_MW = 2_000_000.0
CANONICAL_PREVIEW_STRIDE = 1
# Week number -> whether grid purchases are charged at LMP in both submissions.
CANONICAL_ENERGY_COST_BY_WEEK = {1: False, 2: False, 3: True}

def repository_root() -> Path:
    """Return the source checkout root when running from the installed package."""

    return Path(__file__).resolve().parents[2]


def _base(root: str | Path | None) -> Path:
    return repository_root() if root is None else Path(root)


def canonical_release_artifact_dir(*, root: str | Path | None = None) -> Path:
    """Return the representative-day package used by every submission."""
    return _base(root) / CANONICAL_SCENARIO_PACKAGE


def canonical_release_rules_path(*, root: str | Path | None = None) -> Path:
    """Return the ten-year present-value scoring rules of the release."""
    return _base(root) / CANONICAL_RULES


def load_release_config(*, root: str | Path | None = None) -> dict[str, Any]:
    """Load the released game configuration JSON."""
    path = _base(root) / CANONICAL_RELEASE_CONFIG
    return json.loads(path.read_text(encoding="utf-8"))


def week_energy_cost_enabled(week: int | str) -> bool:
    """Return whether grid purchases are charged at LMP in ``week``.

    ``week`` is the week number (1-3) or a week id such as ``"week-3"``.
    """
    text = str(week)
    number = int(text.removeprefix("week-") if text.startswith("week-") else text)
    if number not in CANONICAL_ENERGY_COST_BY_WEEK:
        raise ValueError("week must be 1, 2, or 3")
    return CANONICAL_ENERGY_COST_BY_WEEK[number]
