from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ercot_game.asset_state import AssetStateError
from ercot_game.game_state import GameState
from ercot_game.game_state_store import GameStateStore
from ercot_game.batch_evaluation import CapitalCostScope, ProjectionDiagnostics, TeamScore
from ercot_game.models import ConnectionPlan, GeneratorPlan, SitePlan, StoragePlan, TeamPlan
from ercot_game import round_coordinator
from ercot_game.round_coordinator import (
    ClassroomRoundInput,
    RoundCoordinatorError,
    evaluate_classroom,
    evaluate_round,
)


def _plan(team_id: str = "team-a", bus_id: str = "b0001") -> TeamPlan:
    return TeamPlan(
        team_id=team_id,
        connections=(ConnectionPlan("site-1", bus_id, 40.0, (1.0,)),),
        generators=(GeneratorPlan("gen-1", "site-1", 10.0, 16.0),),
    )


def _asset_plan(team_id: str = "team-a") -> TeamPlan:
    return TeamPlan(
        team_id=team_id,
        connections=(ConnectionPlan("site-old", "b0001", 40.0, (1.0,)),),
        generators=(GeneratorPlan("gen-old", "site-old", 10.0, 16.0),),
        storages=(StoragePlan("store-old", "site-old", 5.0, 20.0),),
    )


@dataclass(frozen=True)
class _MinimalDispatch:
    periods: tuple = (SimpleNamespace(storage_soc_mwh_by_team={}),)


@dataclass(frozen=True)
class _UsableEvaluation:
    rejected_submissions: tuple = ()
    dispatch: object = field(default_factory=_MinimalDispatch)
    projection_diagnostics: ProjectionDiagnostics | None = None
    team_scores: tuple = field(
        default_factory=lambda: (
            TeamScore(
                team_id="team-a",
                rank=1,
                valid=True,
                feasible=True,
                score=10.0,
                served_load_mwh=1.0,
                it_value=10.0,
                energy_cost=0.0,
                generator_operating_cost=0.0,
                generator_capital_cost=0.0,
                site_cost=0.0,
                competition_scope="joint",
            ),
        )
    )


def _loader(plans):
    def load(*args, **kwargs):
        return tuple(plans)

    return load


def test_successful_round_commits_advanced_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    seen: dict[str, object] = {}

    def evaluator(*args, **kwargs):
        seen["called"] = True
        return _UsableEvaluation()

    result = evaluate_round(
        state_path=state_path,
        round_key="week-1-submission-1",
        submissions=tmp_path / "submissions",
        artifact_dir=tmp_path / "artifacts",
        horizon=1,
        rules=object(),
        plan_loader=_loader((_plan(),)),
        evaluator=evaluator,
    )

    assert seen["called"] is True
    assert result.state.current_round_key == "week-1-submission-1"
    assert GameStateStore(state_path).load().current_round_key == "week-1-submission-1"


def test_evaluation_failure_does_not_change_existing_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    prior = GameState.new().advance("week-1-submission-1", (_plan(),))
    store = GameStateStore(state_path)
    store.save(prior)
    before = state_path.read_bytes()

    def evaluator(*args, **kwargs):
        raise RuntimeError("dispatch failed")

    with pytest.raises(RuntimeError, match="dispatch failed"):
        evaluate_round(
            state_path=state_path,
            round_key="week-1-submission-2",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=_loader((_plan(),)),
            evaluator=evaluator,
        )

    assert state_path.read_bytes() == before
    assert store.load().current_round_key == "week-1-submission-1"


def test_plan_loader_failure_does_not_create_state_file(tmp_path) -> None:
    state_path = tmp_path / "state.json"

    def loader(*args, **kwargs):
        raise RoundCoordinatorError("invalid submission")

    with pytest.raises(RoundCoordinatorError, match="invalid submission"):
        evaluate_round(
            state_path=state_path,
            round_key="week-1-submission-1",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=loader,
            evaluator=lambda *args, **kwargs: _UsableEvaluation(),
        )

    assert not state_path.exists()


def test_asset_conflict_does_not_change_existing_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    store = GameStateStore(state_path)
    store.save(GameState.new().advance("week-1-submission-1", (_plan(),)))
    before = state_path.read_bytes()

    with pytest.raises(AssetStateError):
        evaluate_round(
            state_path=state_path,
            round_key="week-1-submission-2",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=_loader((_plan(bus_id="b0002"),)),
            evaluator=lambda *args, **kwargs: _UsableEvaluation(),
        )

    assert state_path.read_bytes() == before


def test_rejected_result_does_not_commit_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    rejected = _UsableEvaluation(rejected_submissions=(object(),), dispatch=None)

    with pytest.raises(RoundCoordinatorError, match="usable dispatch"):
        evaluate_round(
            state_path=state_path,
            round_key="week-1-submission-1",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=_loader((_plan(),)),
            evaluator=lambda *args, **kwargs: rejected,
        )

    assert not state_path.exists()


@pytest.mark.parametrize("dispatch", (object(), SimpleNamespace(periods=None)))
def test_evaluation_without_period_collection_does_not_commit_state(tmp_path, dispatch) -> None:
    state_path = tmp_path / "state.json"
    evaluation = _UsableEvaluation(dispatch=dispatch)

    with pytest.raises(RoundCoordinatorError, match="usable dispatch"):
        evaluate_round(
            state_path=state_path,
            round_key="week-1-submission-1",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=_loader((_plan(),)),
            evaluator=lambda *args, **kwargs: evaluation,
        )

    assert not state_path.exists()


def test_evaluation_with_empty_period_collection_does_not_commit_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    evaluation = _UsableEvaluation(dispatch=SimpleNamespace(periods=()))

    with pytest.raises(RoundCoordinatorError, match="usable dispatch"):
        evaluate_round(
            state_path=state_path,
            round_key="week-1-submission-1",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=_loader((_plan(),)),
            evaluator=lambda *args, **kwargs: evaluation,
        )

    assert not state_path.exists()


def test_valid_teams_commit_when_rejected_team_is_isolated(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    evaluation = _UsableEvaluation(rejected_submissions=(object(),))

    result = evaluate_round(
        state_path=state_path,
        round_key="week-1-submission-1",
        submissions=tmp_path / "submissions",
        artifact_dir=tmp_path / "artifacts",
        horizon=1,
        rules=object(),
        plan_loader=_loader((_plan(),)),
        evaluator=lambda *args, **kwargs: evaluation,
    )

    assert result.state.current_round_key == "week-1-submission-1"
    assert GameStateStore(state_path).load().current_round_key == "week-1-submission-1"


def test_valid_teams_commit_even_when_evaluation_reports_rejected_team(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    rejected = _UsableEvaluation(rejected_submissions=(object(),))

    result = evaluate_round(
        state_path=state_path,
        round_key="week-1-submission-1",
        submissions=tmp_path / "submissions",
        artifact_dir=tmp_path / "artifacts",
        horizon=1,
        rules=object(),
        plan_loader=lambda *args, **kwargs: (_plan(),),
        evaluator=lambda *args, **kwargs: rejected,
    )

    assert result.state.current_round_key == "week-1-submission-1"
    assert GameStateStore(state_path).load().current_round_key == "week-1-submission-1"


def test_projection_diagnostics_cannot_add_rejected_team_to_round_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    diagnostics = ProjectionDiagnostics(
        service_fraction_by_team={"team-valid": 0.5, "team-rejected": 0.5},
        projected_capacity_mw_by_team={"team-valid": 1.0, "team-rejected": 1.0},
        capped_request_capacity_mw_by_team={"team-valid": 2.0, "team-rejected": 2.0},
        requested_load_mwh_by_team={"team-valid": 2.0, "team-rejected": 2.0},
        projected_load_mwh_by_team={"team-valid": 1.0, "team-rejected": 1.0},
        total_requested_load_mwh=4.0,
        total_projected_load_mwh=2.0,
        proportional_fair_utility=0.0,
        total_load_tolerance_mwh=1e-6,
    )

    with pytest.raises(RoundCoordinatorError, match="rejected or unknown team"):
        evaluate_round(
            state_path=state_path,
            round_key="week-1-submission-1",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=_loader((_plan("team-valid"),)),
            evaluator=lambda *args, **kwargs: _UsableEvaluation(
                projection_diagnostics=diagnostics
            ),
        )

    assert not state_path.exists()


def test_default_plan_loader_keeps_accepted_plans_when_one_file_is_rejected(monkeypatch, tmp_path) -> None:
    accepted = SimpleNamespace(submission=SimpleNamespace(plan=_plan()))
    rejected = SimpleNamespace(team_id="team-b", failure_reason="bad CSV")
    monkeypatch.setattr(round_coordinator, "load_bus_ids", lambda _path: frozenset({"b0001"}))
    monkeypatch.setattr(
        round_coordinator,
        "_collect_evaluation_inputs",
        lambda *args, **kwargs: SimpleNamespace(
            accepted=(accepted,),
            rejected=(rejected,),
        ),
    )

    plans = round_coordinator._default_plan_loader(
        tmp_path / "submissions",
        artifact_dir=tmp_path / "artifacts",
        horizon=1,
        rules=SimpleNamespace(default_generator_cost_per_mwh=16.0),
    )

    assert plans == (_plan(),)


def test_classroom_coordinator_evaluates_all_six_rounds_and_ranks_both_submissions_of_scored_weeks(
    tmp_path,
) -> None:
    state_path = tmp_path / "classroom-state.json"
    rounds = tuple(
        ClassroomRoundInput(
            round_key=round_key,
            submissions=tmp_path / round_key,
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
        )
        for round_key in (
            "week-1-submission-1",
            "week-1-submission-2",
            "week-2-submission-1",
            "week-2-submission-2",
            "week-3-submission-1",
            "week-3-submission-2",
        )
    )

    def evaluator(*args, **kwargs):
        return _UsableEvaluation()

    result = evaluate_classroom(
        state_path=state_path,
        rounds=rounds,
        plan_loader=_loader((_plan(),)),
        evaluator=evaluator,
    )

    assert [(item.week_id, item.submission_number) for item in result.submissions] == [
        ("week-1", 1),
        ("week-1", 2),
        ("week-2", 1),
        ("week-2", 2),
        ("week-3", 1),
        ("week-3", 2),
    ]
    assert [item.feedback_only for item in result.submissions] == [True, True, False, False, False, False]
    assert [item.scored for item in result.submissions] == [False, False, True, True, True, True]
    assert [item.ledger_reset for item in result.submissions] == [False, False, True, False, True, False]
    assert [ranking.week_id for ranking in result.weekly_rankings] == ["week-1", "week-2", "week-3"]
    assert result.weekly_rankings[0].rankings == ()
    assert [
        scores[0].team_id for scores in result.weekly_rankings[0].submission_results
    ] == ["team-a", "team-a"]
    assert all(ranking.rankings for ranking in result.weekly_rankings[1:])
    assert all(len(ranking.submission_results) == 2 for ranking in result.weekly_rankings)
    # Each scored week sums Submission 1 and Submission 2 (10 + 10).
    assert [ranking.rankings[0].score for ranking in result.weekly_rankings[1:]] == [20.0, 20.0]
    assert {score.team_id for score in result.final_rankings} == {"team-a"}
    assert result.final_rankings[0].rank == 1
    # Final = Week 2 S1 + Week 2 S2 + Week 3 S1 + Week 3 S2; Week 1 excluded.
    assert result.final_rankings[0].score == 40.0
    assert result.state.next_round_key is None


def test_final_ranking_sums_both_submissions_of_weeks_two_and_three_and_excludes_week_one(
    tmp_path,
) -> None:
    state_path = tmp_path / "classroom-state.json"
    round_keys = (
        "week-1-submission-1",
        "week-1-submission-2",
        "week-2-submission-1",
        "week-2-submission-2",
        "week-3-submission-1",
        "week-3-submission-2",
    )
    rounds = tuple(
        ClassroomRoundInput(
            round_key=round_key,
            submissions=tmp_path / round_key,
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
        )
        for round_key in round_keys
    )
    # team-b would win if Week 1 counted, and would also win if only
    # Submission 2 counted (50 + 30 > 20 + 40); it loses on the four-score sum.
    scores_by_round = {
        "week-1-submission-1": {"team-a": 0.0, "team-b": 1000.0},
        "week-1-submission-2": {"team-a": 0.0, "team-b": 1000.0},
        "week-2-submission-1": {"team-a": 10.0, "team-b": 5.0},
        "week-2-submission-2": {"team-a": 20.0, "team-b": 50.0},
        "week-3-submission-1": {"team-a": 30.0, "team-b": 1.0},
        "week-3-submission-2": {"team-a": 40.0, "team-b": 30.0},
    }

    def _score(team_id: str, value: float) -> TeamScore:
        return TeamScore(
            team_id=team_id,
            rank=0,
            valid=True,
            feasible=True,
            score=value,
            served_load_mwh=1.0,
            it_value=value,
            energy_cost=0.0,
            generator_operating_cost=0.0,
            generator_capital_cost=0.0,
            site_cost=0.0,
            competition_scope="joint",
        )

    def evaluator(*args, **kwargs):
        round_scores = scores_by_round[Path(args[0]).name]
        return _UsableEvaluation(
            team_scores=tuple(_score(team, value) for team, value in round_scores.items())
        )

    result = evaluate_classroom(
        state_path=state_path,
        rounds=rounds,
        plan_loader=_loader((_plan("team-a"), _plan("team-b", "b0002"))),
        evaluator=evaluator,
    )

    assert result.weekly_rankings[0].feedback_only is True
    assert result.weekly_rankings[0].rankings == ()
    assert [
        (score.team_id, score.score) for score in result.weekly_rankings[1].rankings
    ] == [("team-b", 55.0), ("team-a", 30.0)]
    assert [
        (score.team_id, score.score) for score in result.weekly_rankings[2].rankings
    ] == [("team-a", 70.0), ("team-b", 31.0)]
    assert [
        (score.team_id, score.rank, score.score) for score in result.final_rankings
    ] == [("team-a", 1, 100.0), ("team-b", 2, 86.0)]
    payload = result.to_public_dict()
    assert payload["weekly_rankings"]["week-2"]["submission_results"] == [
        {"team_count": 2, "valid_team_count": 2, "feasible_team_count": 2},
        {"team_count": 2, "valid_team_count": 2, "feasible_team_count": 2},
    ]
    assert [item["scored"] for item in payload["submissions"]] == [
        False, False, True, True, True, True,
    ]


def test_classroom_resume_starts_at_persisted_next_round_without_replay(tmp_path) -> None:
    state_path = tmp_path / "classroom-state.json"
    round_keys = (
        "week-1-submission-1",
        "week-1-submission-2",
        "week-2-submission-1",
        "week-2-submission-2",
        "week-3-submission-1",
        "week-3-submission-2",
    )
    rounds = tuple(
        ClassroomRoundInput(
            round_key=round_key,
            submissions=tmp_path / f"submissions-{index}",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
        )
        for index, round_key in enumerate(round_keys)
    )
    seen: list[str] = []
    calls = 0

    def interrupted_evaluator(*args, **kwargs):
        nonlocal calls
        calls += 1
        seen.append(Path(args[0]).name)
        if calls == 2:
            raise RuntimeError("simulated interruption")
        return _UsableEvaluation()

    with pytest.raises(RuntimeError, match="simulated interruption"):
        evaluate_classroom(
            state_path=state_path,
            rounds=rounds,
            plan_loader=_loader((_plan(),)),
            evaluator=interrupted_evaluator,
        )

    resumed: list[str] = []

    def resumed_evaluator(*args, **kwargs):
        resumed.append(Path(args[0]).name)
        return _UsableEvaluation()

    result = evaluate_classroom(
        state_path=state_path,
        rounds=rounds,
        plan_loader=_loader((_plan(),)),
        evaluator=resumed_evaluator,
    )

    assert seen == ["submissions-0", "submissions-1"]
    assert resumed == [f"submissions-{index}" for index in range(1, 6)]
    assert result.state.next_round_key is None


def test_classroom_resume_is_idempotent_after_all_rounds_are_complete(tmp_path) -> None:
    state_path = tmp_path / "classroom-state.json"
    round_keys = (
        "week-1-submission-1",
        "week-1-submission-2",
        "week-2-submission-1",
        "week-2-submission-2",
        "week-3-submission-1",
        "week-3-submission-2",
    )
    rounds = tuple(
        ClassroomRoundInput(
            round_key=round_key,
            submissions=tmp_path / round_key,
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
        )
        for round_key in round_keys
    )
    evaluate_classroom(
        state_path=state_path,
        rounds=rounds,
        plan_loader=_loader((_plan(),)),
        evaluator=lambda *args, **kwargs: _UsableEvaluation(),
    )
    complete_state = GameStateStore(state_path).load()

    def must_not_run(*args, **kwargs):
        raise AssertionError("completed classroom state was replayed")

    result = evaluate_classroom(
        state_path=state_path,
        rounds=rounds,
        plan_loader=_loader((_plan(),)),
        evaluator=must_not_run,
    )

    assert result.submissions == ()
    assert result.state == complete_state


def test_second_submission_is_rejected_before_loading_or_evaluating_without_predecessor(tmp_path) -> None:
    called = {"loader": False, "evaluator": False}

    def loader(*args, **kwargs):
        called["loader"] = True
        return (_plan(),)

    def evaluator(*args, **kwargs):
        called["evaluator"] = True
        return _UsableEvaluation()

    with pytest.raises(RoundCoordinatorError, match="submission 1.*week-1"):
        evaluate_round(
            state_path=tmp_path / "missing-state.json",
            round_key="week-1-submission-2",
            submissions=tmp_path / "submissions",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
            plan_loader=loader,
            evaluator=evaluator,
        )

    assert called == {"loader": False, "evaluator": False}


def test_classroom_output_summary_contains_only_team_scores_and_not_other_team_plans(tmp_path) -> None:
    state_path = tmp_path / "classroom-state.json"
    rounds = (
        ClassroomRoundInput(
            round_key="week-1-submission-1",
            submissions=tmp_path / "round-1",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
        ),
        ClassroomRoundInput(
            round_key="week-1-submission-2",
            submissions=tmp_path / "round-2",
            artifact_dir=tmp_path / "artifacts",
            horizon=1,
            rules=object(),
        ),
    )

    result = evaluate_classroom(
        state_path=state_path,
        rounds=rounds,
        plan_loader=_loader((_plan("team-a"), _plan("team-b"))),
        evaluator=lambda *args, **kwargs: _UsableEvaluation(),
    )

    payload = result.to_public_dict()
    assert payload["submissions"][0]["team_results"]["team_count"] == 1
    assert "plans" not in payload["submissions"][0]
    serialized = str(payload)
    assert "team-a" not in serialized
    assert "submission_key" not in serialized
    assert "week-1" in payload["weekly_rankings"]
