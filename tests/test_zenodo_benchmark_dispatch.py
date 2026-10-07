from __future__ import annotations

import pytest

from tools.zenodo_texas.dispatch import (
    BranchSpec,
    BusSpec,
    DispatchInfeasible,
    GeneratorSpec,
    solve_dc_dispatch,
)


def _benchmark_inputs():
    buses = (
        BusSpec("source", 0.0, reference=True),
        BusSpec("load-a", 80.0),
    )
    generators = (
        GeneratorSpec("cheap", "source", 0.0, 80.0, 10.0),
        GeneratorSpec("local", "load-a", 0.0, 80.0, 30.0),
    )
    branches = (
        BranchSpec("source-a", "source", "load-a", 1.0, 40.0),
    )
    return buses, generators, branches


def test_dispatch_respects_branch_limit_and_uses_local_generation():
    buses, generators, branches = _benchmark_inputs()

    result = solve_dc_dispatch(buses, generators, branches)

    assert result.status == "optimal"
    assert result.generation_mw == {"cheap": 40.0, "local": 40.0}
    assert result.flow_mw_by_branch["source-a"] == 40.0
    assert result.objective_cost == 1600.0


def test_dispatch_rejects_insufficient_generation():
    buses, _, branches = _benchmark_inputs()
    generators = (GeneratorSpec("small", "source", 0.0, 20.0, 10.0),)

    with pytest.raises(DispatchInfeasible, match="no feasible dispatch"):
        solve_dc_dispatch(buses, generators, branches)


def test_dispatch_rejects_unknown_network_references():
    with pytest.raises(ValueError, match="unknown from_bus_id"):
        solve_dc_dispatch(
            (BusSpec("a", 0.0, reference=True),),
            (GeneratorSpec("g", "a", 0.0, 1.0, 1.0),),
            (BranchSpec("bad", "missing", "a", 1.0, 1.0),),
        )


def test_dispatch_has_no_load_shedding_mode():
    buses, _, branches = _benchmark_inputs()
    generators = (GeneratorSpec("small", "source", 0.0, 20.0, 10.0),)

    with pytest.raises(DispatchInfeasible, match="no feasible dispatch"):
        solve_dc_dispatch(buses, generators, branches)
