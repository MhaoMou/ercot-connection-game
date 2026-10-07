from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from ercot_game.models import ConnectionPlan, GeneratorPlan, StoragePlan, TeamPlan
from tools.zenodo_texas import batch_runner, plan_adapter
from tools.zenodo_texas.dcopf import DCOPFInfeasible, DCOPFResult

def test_zenodo_adapter_contract_documents_fixed_load_and_active_storage_features():
    adapter_source = (ROOT / "tools/zenodo_texas/plan_adapter.py").read_text(encoding="utf-8")
    dcopf_source = (ROOT / "tools/zenodo_texas/dcopf.py").read_text(encoding="utf-8")
    csv_source = (ROOT / "src/ercot_game/csv_submission.py").read_text(encoding="utf-8")
    normalized_adapter_source = " ".join(adapter_source.split())

    for phrase in ("no curtailment", "load shedding", "storage dispatch", "integer recourse"):
        assert phrase in normalized_adapter_source
    assert "does not introduce load-shedding or curtailment variables" in dcopf_source
    assert "Team-owned storage" in csv_source
    assert "storage power and energy must be positive" in csv_source


def _batch_plan(*, generator: GeneratorPlan | None = None) -> TeamPlan:
    return TeamPlan(
        "team-a",
        connections=(ConnectionPlan("site-a", "bus-a", (), 1.0, (1.0,)),),
        generators=() if generator is None else (generator,),
    )


@pytest.mark.parametrize(
    ("generator", "message"),
    (
        (GeneratorPlan("gen-a", "missing-site", 1.0, 10.0), "unknown connection"),
        (GeneratorPlan("gen-a", "site-a", math.nan, 10.0), "capacity must be finite"),
        (GeneratorPlan("gen-a", "site-a", -1.0, 10.0), "capacity must be finite and non-negative"),
        (GeneratorPlan("gen-a", "site-a", 1.0, math.inf), "cost must be finite"),
        (GeneratorPlan("gen-a", "site-a", 1.0, -1.0), "cost must be finite and non-negative"),
    ),
)
def test_batch_adapter_validates_generator_contract_before_solving(generator, message):
    with pytest.raises(ValueError, match=message):
        plan_adapter.evaluate_plans_with_prepared_dcopf(
            "unused",
            (_batch_plan(generator=generator),),
            period_indices=(0,),
        )


def test_batch_adapter_rejects_duplicate_period_indices_before_solving():
    with pytest.raises(ValueError, match="period_indices must not contain duplicates"):
        plan_adapter.evaluate_plans_with_prepared_dcopf(
            "unused",
            (_batch_plan(),),
            period_indices=(0, 0),
        )


@pytest.mark.parametrize("period_index", ("0", True, 1.5))
@pytest.mark.parametrize("batch", (False, True))
def test_adapter_rejects_non_integer_period_indices_in_single_and_batch_paths(
    period_index, batch
):
    with pytest.raises(ValueError, match="period_indices must contain integers"):
        if batch:
            plan_adapter.evaluate_plans_with_prepared_dcopf(
                "unused",
                (_batch_plan(),),
                period_indices=(period_index,),
            )
        else:
            plan_adapter.evaluate_plan_with_prepared_dcopf(
                "unused",
                _batch_plan(),
                period_indices=(period_index,),
            )


def test_plan_adapter_is_invariant_to_connection_and_generator_input_order(monkeypatch):
    calls = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        calls.append(
            (
                period_index,
                tuple(additional_demand_mw_by_bus.items()),
                tuple(generator.generator_id for generator in additional_generators),
            )
        )
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={
                generator.generator_id: float(index)
                for index, generator in enumerate(additional_generators)
            },
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    forward = TeamPlan(
        "team-1",
        connections=(
            ConnectionPlan("site-b", "bus-b", (), 2.0, (1.0,)),
            ConnectionPlan("site-a", "bus-a", (), 1.0, (1.0,)),
        ),
        generators=(
            GeneratorPlan("gen-b", "site-b", 1.0, 20.0),
            GeneratorPlan("gen-a", "site-a", 1.0, 10.0),
        ),
    )
    reversed_input = TeamPlan(
        "team-1",
        connections=tuple(reversed(forward.connections)),
        generators=tuple(reversed(forward.generators)),
    )

    forward_result = plan_adapter.evaluate_plan_with_prepared_dcopf(
        "unused", forward, period_indices=(0,)
    )
    forward_calls = calls[:]
    calls.clear()
    reversed_result = plan_adapter.evaluate_plan_with_prepared_dcopf(
        "unused", reversed_input, period_indices=(0,)
    )

    assert reversed_result == forward_result
    assert calls == forward_calls


def test_joint_batch_adapter_is_invariant_to_connection_input_order(monkeypatch):
    calls = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        calls.append(
            (
                period_index,
                tuple(additional_demand_mw_by_bus.items()),
                tuple(generator.generator_id for generator in additional_generators),
            )
        )
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={
                generator.generator_id: float(index)
                for index, generator in enumerate(additional_generators)
            },
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    forward = TeamPlan(
        "team-1",
        connections=(
            ConnectionPlan("site-b", "bus-b", (), 2.0, (1.0,)),
            ConnectionPlan("site-a", "bus-a", (), 1.0, (1.0,)),
        ),
        generators=(
            GeneratorPlan("gen-b", "site-b", 1.0, 20.0),
            GeneratorPlan("gen-a", "site-a", 1.0, 10.0),
        ),
    )
    reversed_input = TeamPlan(
        "team-1",
        connections=tuple(reversed(forward.connections)),
        generators=tuple(reversed(forward.generators)),
    )

    forward_result = plan_adapter.evaluate_plans_with_prepared_dcopf(
        "unused", (forward,), period_indices=(0,)
    )
    forward_calls = calls[:]
    calls.clear()
    reversed_result = plan_adapter.evaluate_plans_with_prepared_dcopf(
        "unused", (reversed_input,), period_indices=(0,)
    )

    assert reversed_result == forward_result
    assert calls == forward_calls


def test_zenodo_batch_runner_reexports_first_class_batch_evaluator():
    from ercot_game import batch_evaluation

    assert batch_runner.BatchScoringRules is batch_evaluation.BatchScoringRules
    assert batch_runner.evaluate_csv_batch is batch_evaluation.evaluate_csv_batch
    assert batch_runner._score_team is batch_evaluation._score_team


def test_joint_adapter_parallel_workers_preserve_period_order(monkeypatch):
    calls = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        calls.append(period_index)
        return DCOPFResult(
            status="optimal",
            objective_cost=float(period_index),
            generation_mw={},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    plan = TeamPlan(
        "team-a",
        connections=(ConnectionPlan("site-a", "bus-a", (), 1.0, (1.0, 1.0, 1.0)),),
    )

    serial = plan_adapter.evaluate_plans_with_prepared_dcopf(
        "unused", (plan,), period_indices=(2, 0, 1), workers=1
    )
    calls.clear()
    parallel = plan_adapter.evaluate_plans_with_prepared_dcopf(
        "unused", (plan,), period_indices=(2, 0, 1), workers=2
    )

    assert parallel == serial
    assert [period.period_index for period in parallel.periods] == [2, 0, 1]


def test_joint_adapter_early_stop_does_not_solve_periods_after_infeasibility(monkeypatch):
    calls = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        calls.append(period_index)
        if period_index == 0:
            raise DCOPFInfeasible("infeasible")
        raise AssertionError("period after the first failure was solved")

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    plan = TeamPlan(
        "team-a",
        connections=(ConnectionPlan("site-a", "bus-a", (), 1.0, (1.0, 1.0)),),
    )

    with pytest.raises(DCOPFInfeasible):
        plan_adapter.evaluate_plans_with_prepared_dcopf(
            "unused", (plan,), period_indices=(0, 1), stop_on_infeasible=True
        )

    assert calls == [0]


def test_prepared_artifact_loader_is_cached(tmp_path):
    from tools.zenodo_texas.dcopf import load_prepared_artifact

    for name, content in {
        "bus.csv": "bus_id,type\nbus-a,3\n",
        "demand_bus.csv": "period,bus-a\n0,1\n",
        "generator_limits.csv": "generator_id,bus_id,p_min_mw,p_max_mw,marginal_cost_c1_per_mwh,status\ngen-a,bus-a,0,2,1,1\n",
        "branch_limits.csv": "branch_id,from_bus_id,to_bus_id,reactance_pu,thermal_limit_mva,status\n",
        "dcline.csv": "from_bus_id,to_bus_id,Pt,status\n",
    }.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    first = load_prepared_artifact(tmp_path)
    second = load_prepared_artifact(tmp_path)
    assert first is second


def test_storage_schedule_respects_discharge_and_terminal_energy_constraints():
    plan = TeamPlan(
        "team-storage",
        connections=(ConnectionPlan("site-a", "bus-a", (), 4.0, (0.25, 0.5, 0.75, 1.0)),),
        storages=(StoragePlan("storage-a", "site-a", 2.0, 4.0),),
    )

    schedule = plan_adapter._storage_schedule(plan, plan.connections, (0, 1, 2, 3))["storage-a"]
    soc = 2.0
    for period in range(4):
        discharge = schedule["discharge"][period]
        assert 0.0 <= discharge <= soc
        soc += schedule["charge"][period] - discharge
        assert 0.0 <= soc <= 4.0
    assert schedule["soc"][3] >= 2.0


def test_storage_schedule_is_time_step_aware_and_bounds_discharge_by_local_site_load():
    plan = TeamPlan(
        "team-storage",
        connections=(ConnectionPlan("site-a", "bus-a", (), 1.0, (0.0, 0.5, 1.0)),),
        storages=(StoragePlan("storage-a", "site-a", 2.0, 4.0),),
    )

    schedule = plan_adapter._storage_schedule(
        plan,
        plan.connections,
        (0, 1, 2),
        time_step_hours=2.0,
    )["storage-a"]

    previous_soc = 2.0
    for period in (0, 1, 2):
        charge = schedule["charge"][period]
        discharge = schedule["discharge"][period]
        assert charge == 0.0 or discharge == 0.0
        assert discharge <= plan.connections[0].capacity_mw * plan.connections[0].profile[period]
        expected_soc = previous_soc + (charge - discharge) * 2.0
        assert schedule["soc"][period] == pytest.approx(expected_soc)
        assert 0.0 <= expected_soc <= 4.0
        previous_soc = expected_soc
    assert schedule["soc"][2] >= 2.0


def test_storage_schedule_aggregates_discharge_limit_for_storages_at_one_site():
    plan = TeamPlan(
        "team-storage",
        connections=(ConnectionPlan("site-a", "bus-a", (), 1.0, (0.0, 1.0)),),
        storages=(
            StoragePlan("storage-a", "site-a", 1.0, 4.0),
            StoragePlan("storage-b", "site-a", 1.0, 4.0),
        ),
    )

    schedules = plan_adapter._storage_schedule(plan, plan.connections, (0, 1))

    assert sum(values["discharge"][1] for values in schedules.values()) <= 1.0
    assert sum(values["discharge"][1] for values in schedules.values()) > 0.0


def test_owned_generator_capacity_is_capped_by_each_teams_local_net_load(monkeypatch):
    captured = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        captured.append(tuple((generator.generator_id, generator.p_max_mw) for generator in additional_generators))
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={generator.generator_id: 0.0 for generator in additional_generators},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    plans = (
        TeamPlan(
            "team-a",
            connections=(ConnectionPlan("site-a", "bus-a", (), 1.0, (1.0,)),),
            generators=(
                GeneratorPlan("gen-a", "site-a", 5.0, 10.0),
                GeneratorPlan("gen-b", "site-a", 5.0, 10.0),
            ),
        ),
        TeamPlan(
            "team-b",
            connections=(ConnectionPlan("site-b", "bus-a", (), 20.0, (1.0,)),),
        ),
    )

    plan_adapter.evaluate_plans_with_prepared_dcopf("unused", plans, period_indices=(0,))

    assert captured == [
        (
            ("student:6:team-a5:gen-a", 1.0),
            ("student:6:team-a5:gen-b", 0.0),
        )
    ]


def test_storage_falls_back_to_idle_when_peak_shaving_makes_dispatch_infeasible(monkeypatch):
    calls = []

    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        calls.append(dict(additional_demand_mw_by_bus))
        if period_index == 0 and additional_demand_mw_by_bus["bus-a"] > 0.0:
            raise DCOPFInfeasible("forced charging is infeasible")
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    plan = TeamPlan(
        "team-storage",
        connections=(ConnectionPlan("site-a", "bus-a", (), 1.0, (0.0, 1.0)),),
        storages=(StoragePlan("storage-a", "site-a", 1.0, 4.0),),
    )

    result = plan_adapter.evaluate_plan_with_prepared_dcopf(
        "unused", plan, period_indices=(0, 1)
    )

    assert len(calls) == 3
    assert all(period.submitted_load_mw in (0.0, 1.0) for period in result.periods)
    assert result.periods[0].submitted_load_mw == 0.0
    assert result.periods[1].submitted_load_mw == 1.0


def test_single_and_batch_submitted_load_exclude_storage_activity(monkeypatch):
    def fake_solve(_artifact_dir, *, period_index, additional_demand_mw_by_bus, additional_generators):
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr("tools.zenodo_texas.plan_adapter.solve_prepared_period", fake_solve)
    plan = TeamPlan(
        "team-storage",
        connections=(ConnectionPlan("site-a", "bus-a", (), 2.0, (0.0, 2.0)),),
        storages=(StoragePlan("storage-a", "site-a", 1.0, 4.0),),
    )

    single = plan_adapter.evaluate_plan_with_prepared_dcopf(
        "unused", plan, period_indices=(0, 1)
    )
    batch = plan_adapter.evaluate_plans_with_prepared_dcopf(
        "unused", (plan,), period_indices=(0, 1)
    )

    assert [period.submitted_load_mw for period in single.periods] == [
        batch_period.submitted_load_mw_by_team["team-storage"]
        for batch_period in batch.periods
    ]
