from __future__ import annotations

import json

import pytest

from ercot_game.asset_state import AssetStateError
from ercot_game.game_state import GameState, RoundTransitionError
from ercot_game.models import ConnectionPlan, GeneratorPlan, StoragePlan, TeamPlan


def _plan(team_id: str = "team-a") -> TeamPlan:
    return TeamPlan(
        team_id=team_id,
        connections=(
            ConnectionPlan("site-1", "b0001", 40.0, (1.0,)),
        ),
        generators=(
            GeneratorPlan("gen-1", "site-1", 10.0, 16.0),
        ),
    )


def test_new_game_state_exposes_first_round() -> None:
    state = GameState.new()

    assert state.current_round_key is None
    assert state.next_round_key == "week-1-submission-1"
    assert GameState.new("half-year-6h").next_round_key == "2027_jan_jun"


def test_fresh_state_adopts_the_schedule_of_its_first_round() -> None:
    legacy = GameState.new().advance("2027_jan_jun", (_plan(),))
    assert legacy.schedule_id == "half-year-6h"
    assert legacy.next_round_key == "2027_jul_dec"

    state = GameState.new().advance("week-1-submission-1", (_plan(),))
    assert state.schedule_id == "representative"
    assert state.current_week_id == "week-1"
    assert state.current_submission_number == 1
    assert state.next_round_key == "week-1-submission-2"
    with pytest.raises(RoundTransitionError, match="expected week-1-submission-2"):
        state.advance("2027_jul_dec", ())


def test_carried_base_load_round_trips_and_resets_at_the_next_week() -> None:
    state = GameState(
        current_round_key="week-1-submission-1",
        completed_rounds=("week-1-submission-1",),
        carried_base_load_mw_by_bus={"b0001": (1.0, 2.0)},
    )
    restored = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert restored.carried_base_load_mw_by_bus == {"b0001": (1.0, 2.0)}
    assert restored.schedule_id == "representative"

    same_week = restored.advance("week-1-submission-2", ())
    assert same_week.carried_base_load_mw_by_bus == {"b0001": (1.0, 2.0)}
    next_week = same_week.advance("week-2-submission-1", ())
    assert next_week.carried_base_load_mw_by_bus == {}


def test_advance_persists_assets_and_moves_to_next_half_year() -> None:
    state = GameState.new().advance("2027_jan_jun", (_plan(),))

    assert state.current_round_key == "2027_jan_jun"
    assert state.current_week_id == "week-1"
    assert state.current_submission_number == 1
    assert state.next_round_key == "2027_jul_dec"
    assert state.next_week_id == "week-1"
    assert state.next_submission_number == 2
    assert state.asset_ledger.team("team-a").generators["gen-1"].bus_id == "b0001"

    next_state = state.advance("2027_jul_dec", (TeamPlan(team_id="team-a", connections=()),))
    assert next_state.current_round_key == "2027_jul_dec"
    assert next_state.asset_ledger.team("team-a").generators["gen-1"].capacity_mw == 10.0


def test_advance_resets_assets_at_the_start_of_the_next_weekly_match() -> None:
    state = GameState.new().advance("2027_jan_jun", (_plan(),))
    state = state.advance("2027_jul_dec", (TeamPlan(team_id="team-a", connections=()),))

    next_week = state.advance("2028_jan_jun", ())

    assert next_week.current_week_id == "week-2"
    assert next_week.asset_ledger.team_ids() == ()

def test_rounds_must_be_completed_in_order() -> None:
    state = GameState.new()

    with pytest.raises(RoundTransitionError, match="expected 2027_jan_jun"):
        state.advance("2028_jan_jun", ())

    state = state.advance("2027_jan_jun", ())
    with pytest.raises(RoundTransitionError, match="expected 2027_jul_dec"):
        state.advance("2027_jan_jun", ())


def test_duplicate_team_plans_are_rejected_before_asset_updates() -> None:
    state = GameState.new()

    with pytest.raises(RoundTransitionError, match="at most one plan"):
        state.advance("2027_jan_jun", (_plan("team-a"), _plan("team-a")))

    assert state.current_round_key is None
    assert state.asset_ledger.team_ids() == ()


@pytest.mark.parametrize(
    ("plan", "message"),
    (
        (
            TeamPlan(
                team_id="team-a",
                connections=(
                    ConnectionPlan("site-1", "b0001", 40.0, (1.0,)),
                    ConnectionPlan("site-1", "b0002", 40.0, (1.0,)),
                ),
            ),
            "duplicate connection site: site-1",
        ),
        (
            TeamPlan(
                team_id="team-a",
                connections=(ConnectionPlan("site-1", "b0001", 40.0, (1.0,)),),
                generators=(
                    GeneratorPlan("gen-1", "site-1", 10.0, 16.0),
                    GeneratorPlan("gen-1", "site-1", 10.0, 16.0),
                ),
            ),
            "duplicate generator asset: gen-1",
        ),
        (
            TeamPlan(
                team_id="team-a",
                connections=(ConnectionPlan("site-1", "b0001", 40.0, (1.0,)),),
                storages=(
                    StoragePlan("store-1", "site-1", 5.0, 20.0),
                    StoragePlan("store-1", "site-1", 5.0, 20.0),
                ),
            ),
            "duplicate storage asset: store-1",
        ),
    ),
)
def test_advance_rejects_duplicate_asset_ids(plan: TeamPlan, message: str) -> None:
    with pytest.raises(AssetStateError, match=message):
        GameState.new().advance("2027_jan_jun", (plan,))


def test_state_round_trip_is_json_safe() -> None:
    state = GameState.new().advance("2027_jan_jun", (_plan(),))
    restored = GameState.from_dict(json.loads(json.dumps(state.to_dict())))

    assert restored.to_dict() == state.to_dict()


def test_invalid_round_key_is_rejected() -> None:
    with pytest.raises(RoundTransitionError, match="released half-year"):
        GameState.new().advance("2018_jan_jun", ())


def test_asset_conflict_does_not_mutate_prior_state() -> None:
    state = GameState.new().advance("2027_jan_jun", (_plan(),))
    conflicting = TeamPlan(
        team_id="team-a",
        connections=(ConnectionPlan("site-1", "b0001", 40.0, (1.0,)),),
        generators=(GeneratorPlan("renamed-gen-1", "site-1", 11.0, 16.0),),
    )

    with pytest.raises(AssetStateError):
        state.advance("2027_jul_dec", (conflicting,))

    assert state.current_round_key == "2027_jan_jun"
    assert state.next_round_key == "2027_jul_dec"
