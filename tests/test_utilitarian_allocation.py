"""The utilitarian site allocation used when the plans do not fit together."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("highspy")

from ercot_game import batch_evaluation
from ercot_game.batch_evaluation import (
    BatchScoringRules,
    _utilitarian_allocation,
    evaluate_csv_batch,
)
from ercot_game.csv_submission import CANONICAL_CSV_COLUMNS, read_student_csv
from ercot_game.csv_validator import validate_csv_submission
from ercot_game.models import ConnectionPlan, GeneratorPlan, StoragePlan, TeamPlan
from tools.activsg2000.allocation import AllocationSite, _DayModel, allocate_sites
from tools.activsg2000.dcopf import (
    _prepared_period_inputs,
    clear_prepared_artifact_cache,
    load_prepared_artifact,
)

DAYS = 2
HORIZON = 24 * DAYS
PERIODS = tuple(range(HORIZON))
HEADER = ",".join(CANONICAL_CSV_COLUMNS)


def _artifact(root: Path, base_load_at_site_bus) -> Path:
    """Two buses joined by one 100 MW line; sites sit at bus 2.

    The hosting capacity of bus 2 in hour t is 100 MW minus
    ``base_load_at_site_bus(t)``.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "bus.csv").write_text("bus_id,type\n1,3\n2,1\n", encoding="utf-8")
    (root / "bus_load_base.csv").write_text("bus_id,base_load_mw\n1,0.0\n2,0.0\n", encoding="utf-8")
    (root / "branch_limits.csv").write_text(
        "branch_id,from_bus_id,to_bus_id,reactance_pu,thermal_limit_mva,status\n"
        "br1,1,2,0.1,100.0,1\n",
        encoding="utf-8",
    )
    (root / "dcline.csv").write_text("status,from_bus_id,to_bus_id,Pt\n", encoding="utf-8")
    generators = (
        "generator_id,bus_id,p_min_mw,p_max_mw,marginal_cost_c1_per_mwh,status,profile_type\n"
        "g1,1,0.0,1000.0,20.0,1,thermal\n"
    )
    (root / "generator_catalog.csv").write_text(generators, encoding="utf-8")
    (root / "generator_limits.csv").write_text(generators, encoding="utf-8")
    rows = ["period,1,2"] + [f"{t},0.0,{float(base_load_at_site_bus(t))}" for t in PERIODS]
    (root / "demand_bus.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    clear_prepared_artifact_cache()
    return root


def _dip(tmp_path: Path) -> Path:
    # 100 MW of room, except 75 MW in two evening hours a day.
    return _artifact(tmp_path / "dip", lambda t: 25.0 if t % 24 in (18, 19) else 0.0)


def _flat(tmp_path: Path) -> Path:
    # 70 MW of room in every hour.
    return _artifact(tmp_path / "flat", lambda t: 30.0)


def _plan(team_id: str, connection_mw: float, generator_mw: float = 0.0, power_mw: float = 0.0) -> TeamPlan:
    generators = (GeneratorPlan("gen", "s1", generator_mw, 150.0),) if generator_mw > 0 else ()
    storages = (StoragePlan("bat", "s1", power_mw, 4.0 * power_mw),) if power_mw > 0 else ()
    return TeamPlan(
        team_id,
        connections=(ConnectionPlan("s1", "2", connection_mw, (1.0,) * HORIZON),),
        generators=generators,
        storages=storages,
    )


def _fractions(artifact: Path, *plans: TeamPlan) -> dict[str, float]:
    result = _utilitarian_allocation(artifact, plans, PERIODS, PERIODS)
    assert result is not None
    return result.service_fraction_by_team


def test_a_constant_load_is_limited_by_its_worst_hour(tmp_path) -> None:
    assert _fractions(_dip(tmp_path), _plan("a", 100.0))["a"] == pytest.approx(0.75, abs=2e-4)


def test_an_off_grid_site_is_always_served_in_full(tmp_path) -> None:
    # G = C: the site never needs the grid, however large it is.
    assert _fractions(_flat(tmp_path), _plan("a", 1_000.0, generator_mw=1_000.0))["a"] == pytest.approx(1.0)


def test_identical_requests_split_the_room_evenly(tmp_path) -> None:
    fractions = _fractions(_flat(tmp_path), _plan("a", 100.0), _plan("b", 100.0))
    assert fractions["a"] == pytest.approx(0.35, abs=2e-4)
    assert fractions["b"] == pytest.approx(0.35, abs=2e-4)


def test_the_site_that_needs_less_grid_per_mw_is_served_first(tmp_path) -> None:
    # 70 MW of room: B's generator covers half its load, so each grid MW
    # serves two MW at B.  Maximizing served capacity fills B, then A.
    fractions = _fractions(_flat(tmp_path), _plan("a", 60.0), _plan("b", 60.0, generator_mw=30.0))
    assert fractions["b"] == pytest.approx(1.0, abs=2e-4)
    assert fractions["a"] == pytest.approx(40.0 / 60.0, abs=2e-4)


def test_a_battery_lifts_a_site_limited_by_two_evening_hours(tmp_path) -> None:
    artifact = _dip(tmp_path)
    without = _fractions(artifact, _plan("a", 100.0))["a"]
    with_battery = _fractions(artifact, _plan("a", 100.0, power_mw=25.0))["a"]
    assert with_battery > without + 0.1


def test_the_allocation_is_deterministic(tmp_path) -> None:
    artifact = _flat(tmp_path)
    plans = (_plan("a", 90.0), _plan("b", 40.0, power_mw=10.0), _plan("c", 70.0, generator_mw=20.0))
    first = _utilitarian_allocation(artifact, plans, PERIODS, PERIODS)
    second = _utilitarian_allocation(artifact, plans, PERIODS, PERIODS)
    assert first.diagnostics.site_fraction_by_team == second.diagnostics.site_fraction_by_team


def test_cut_gradients_match_finite_differences(tmp_path) -> None:
    artifact = _flat(tmp_path)
    sites = [
        AllocationSite("a", "s1", "2", 90.0, (90.0,) * 24),
        AllocationSite("b", "s1", "2", 60.0, (60.0,) * 24, generator_mw=30.0),
        AllocationSite("c", "s1", "2", 40.0, (40.0,) * 24, storage_power_mw=10.0, storage_energy_mwh=40.0),
    ]
    prepared_artifact = load_prepared_artifact(str(artifact.resolve()))
    prepared = tuple(
        _prepared_period_inputs(str(artifact.resolve()), prepared_artifact, period_index=t, validate_artifact=False)
        for t in range(24)
    )
    day = _DayModel(prepared, sites, range(24), time_step_hours=1.0, base_mva=100.0)
    point = [0.9, 0.8, 0.7]
    shed, gradient = day.shed(point)
    assert shed > 0.0
    for index in range(len(point)):
        lower = list(point)
        lower[index] -= 1e-4
        assert (shed - day.shed(lower)[0]) / 1e-4 == pytest.approx(gradient[index], rel=1e-5)


def test_allocate_sites_returns_none_when_the_base_network_does_not_fit(tmp_path) -> None:
    artifact = _artifact(tmp_path / "overloaded", lambda t: 150.0)
    sites = [AllocationSite("a", "s1", "2", 10.0, (10.0,) * HORIZON)]
    assert allocate_sites(artifact, sites, period_indices=PERIODS) is None


def _write(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


def test_capital_is_charged_on_the_allocated_capacities(tmp_path) -> None:
    artifact = _flat(tmp_path)
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    _write(submissions / "a.csv", ["team-a,s1,2,100,0,0,0"])
    _write(submissions / "b.csv", ["team-b,s1,2,100,0,0,0"])
    rules = BatchScoringRules(
        rules_version="test",
        it_value_per_mwh=(1_000.0,) * HORIZON,
        energy_price_per_mwh=(0.0,) * HORIZON,
        site_cost_per_mw=1_000.0,
        storage_boundary_mode="daily_exact_cycle",
    )
    evaluation = evaluate_csv_batch(
        submissions, artifact_dir=artifact, horizon=HORIZON, rules=rules, energy_cost_enabled=False
    )
    assert evaluation.competition_scope == "joint_projection"
    for score in evaluation.team_scores:
        assert score.site_cost == pytest.approx(35.0 * 1_000.0, rel=2e-4)
        assert score.served_load_mwh == pytest.approx(35.0 * HORIZON, rel=2e-4)
        # Each team's private summary lists the fractions of its own sites only.
        summary = batch_evaluation._classroom_team_summary(
            evaluation,
            score,
            week_id="week-1",
            submission_number=1,
            feedback_only=False,
            scored=True,
            all_team_ids={"team-a", "team-b"},
        )
        assert summary["projection"]["site_fraction"] == pytest.approx({"s1": 0.35}, abs=2e-4)


def test_a_team_may_request_at_most_one_gigawatt(tmp_path) -> None:
    within = _write(tmp_path / "within.csv", ["team-a,s1,2,600,600,0,0", "team-a,s2,2,400,0,0,0"])
    over = _write(tmp_path / "over.csv", ["team-a,s1,2,600,0,0,0", "team-a,s2,2,400.5,0,0,0"])
    assert read_student_csv(within, max_team_connection_capacity_mw=1_000.0).plan.team_id == "team-a"
    with pytest.raises(ValueError, match="1,000 MW per team"):
        read_student_csv(over, max_team_connection_capacity_mw=1_000.0)
    report = validate_csv_submission(over, bus_ids={"1", "2"}, max_team_connection_capacity_mw=1_000.0)
    assert not report.valid
    assert any("1,000 MW per team" in issue.message for issue in report.issues)


def test_submission_2_base_load_uses_each_sites_own_fraction(tmp_path) -> None:
    from ercot_game.base_load import site_net_withdrawal_rows

    artifact = _flat(tmp_path)
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    # 70 MW of room: the site with a 30 MW generator is served in full and
    # the other site of the same team gets the remaining 40 MW.
    _write(submissions / "a.csv", ["team-a,plain,2,60,0,0,0", "team-a,backed,2,60,30,0,0"])
    rules = BatchScoringRules(
        rules_version="test",
        it_value_per_mwh=(1_000.0,) * HORIZON,
        energy_price_per_mwh=(0.0,) * HORIZON,
        storage_boundary_mode="daily_exact_cycle",
    )
    evaluation = evaluate_csv_batch(
        submissions, artifact_dir=artifact, horizon=HORIZON, rules=rules, energy_cost_enabled=False
    )
    assert evaluation.competition_scope == "joint_projection"
    load = {
        row["site_id"]: row["load_mw"]
        for row in site_net_withdrawal_rows(evaluation)
        if row["period_index"] == 0
    }
    assert load == pytest.approx({"plain": 40.0, "backed": 60.0}, abs=0.02)
    net = sum(row["net_withdrawal_mw"] for row in site_net_withdrawal_rows(evaluation) if row["period_index"] == 0)
    assert net == pytest.approx(70.0, abs=0.02)


def test_no_room_gives_every_site_zero(tmp_path) -> None:
    # The base load already fills the 100 MW line in every hour.
    artifact = _artifact(tmp_path / "full", lambda t: 100.0)
    sites = [AllocationSite("a", "s1", "2", 50.0, (50.0,) * HORIZON), AllocationSite("b", "s1", "2", 30.0, (30.0,) * HORIZON)]
    result = allocate_sites(artifact, sites, period_indices=PERIODS)
    assert result is not None
    assert result.alpha_by_site == {("a", "s1"): 0.0, ("b", "s1"): 0.0}
