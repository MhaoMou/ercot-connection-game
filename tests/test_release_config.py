import json

import pytest

from ercot_game.release_config import (
    CANONICAL_ENERGY_COST_BY_WEEK,
    CANONICAL_GENERATOR_CAPITAL_COST_PER_MW,
    CANONICAL_HORIZON,
    CANONICAL_MAX_GENERATOR_TO_CONNECTION_RATIO,
    CANONICAL_MAX_TEAM_CONNECTION_CAPACITY_MW,
    CANONICAL_PREVIEW_STRIDE,
    CANONICAL_STORAGE_BOUNDARY_MODE,
    CANONICAL_TIME_STEP_HOURS,
    canonical_release_artifact_dir,
    canonical_release_rules_path,
    load_release_config,
    week_energy_cost_enabled,
)
from ercot_game.calendars import CLASSROOM_SCHEDULE
from ercot_game.scenario_package import REPRESENTATIVE_PACKAGE_VERSION, require_validated_block


def test_canonical_release_is_the_hourly_representative_day_package() -> None:
    assert CANONICAL_TIME_STEP_HOURS == 1
    assert CANONICAL_HORIZON == 120
    assert CANONICAL_STORAGE_BOUNDARY_MODE == "daily_exact_cycle"
    assert CANONICAL_MAX_GENERATOR_TO_CONNECTION_RATIO == 1.0
    assert CANONICAL_MAX_TEAM_CONNECTION_CAPACITY_MW == 1_000.0
    assert CANONICAL_PREVIEW_STRIDE == 1
    manifest = require_validated_block(canonical_release_artifact_dir())
    assert manifest["package_version"] == REPRESENTATIVE_PACKAGE_VERSION
    assert manifest["horizon"] == CANONICAL_HORIZON
    rules = json.loads(canonical_release_rules_path().read_text(encoding="utf-8"))
    assert rules["rules_version"] == "dispatch-scoring-representative-v1"
    assert rules["max_generator_to_connection_ratio"] == CANONICAL_MAX_GENERATOR_TO_CONNECTION_RATIO
    assert rules.get("generator_daily_energy_hours") is None
    assert rules["max_team_connection_capacity_mw"] == CANONICAL_MAX_TEAM_CONNECTION_CAPACITY_MW
    assert rules["generator_capital_cost_per_mw"] == CANONICAL_GENERATOR_CAPITAL_COST_PER_MW


def test_release_json_matches_the_week_schedule_and_energy_switch() -> None:
    config = load_release_config()
    assert config["scenario_package"] == "data/processed/activsg2000_representative_v1"
    assert config["horizon"] == CANONICAL_HORIZON
    assert config["max_generator_to_connection_ratio"] == CANONICAL_MAX_GENERATOR_TO_CONNECTION_RATIO
    assert "generator_daily_energy_hours" not in config
    assert config["max_team_connection_capacity_mw"] == CANONICAL_MAX_TEAM_CONNECTION_CAPACITY_MW
    assert config["generator_capital_cost_per_mw"] == CANONICAL_GENERATOR_CAPITAL_COST_PER_MW
    weeks = config["weeks"]
    assert [week["week_id"] for week in weeks] == [match.week_id for match in CLASSROOM_SCHEDULE]
    assert [tuple(week["submissions"]) for week in weeks] == [match.round_keys for match in CLASSROOM_SCHEDULE]
    assert [week["energy_cost_enabled"] for week in weeks] == [
        match.energy_cost_enabled for match in CLASSROOM_SCHEDULE
    ]
    assert CANONICAL_ENERGY_COST_BY_WEEK == {1: False, 2: False, 3: True}
    assert [week_energy_cost_enabled(number) for number in (1, 2, 3)] == [False, False, True]
    assert week_energy_cost_enabled("week-3") is True
    with pytest.raises(ValueError):
        week_energy_cost_enabled(4)

