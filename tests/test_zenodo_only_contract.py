from dataclasses import fields

from ercot_game.models import ConnectionPlan, GeneratorPlan, StoragePlan, TeamPlan


def test_production_plan_model_contains_only_zenodo_dispatch_fields():
    assert [field.name for field in fields(ConnectionPlan)] == [
        "connection_id", "bus_id", "capacity_mw", "profile"
    ]
    assert [field.name for field in fields(GeneratorPlan)] == [
        "generator_id", "connection_id", "capacity_mw", "marginal_cost_per_mwh"
    ]
    assert [field.name for field in fields(StoragePlan)] == [
        "storage_id", "connection_id", "power_mw", "energy_mwh"
    ]
    assert [field.name for field in fields(TeamPlan)] == [
        "team_id", "connections", "generators", "storages"
    ]


def test_zenodo_plan_exposes_only_dispatch_and_asset_records():
    plan = TeamPlan(
        "team-a",
        connections=(ConnectionPlan("site-a", "3001001", 10.0, (1.0,)),),
        generators=(GeneratorPlan("g-a", "site-a", 2.0, 35.0),),
        storages=(StoragePlan("s-a", "site-a", 1.0, 2.0),),
    )
    assert plan.team_id == "team-a"
    assert len(plan.connections) == len(plan.generators) == len(plan.storages) == 1
    assert not hasattr(plan, "legacy_parameters")
