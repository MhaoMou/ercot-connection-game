import json
import xml.dom.minidom

from ercot_game.grid_map import (
    MapBranch,
    served_load_by_bus,
    branch_loading,
    compute_layout,
    main,
    render_svg,
)

HEADER = "team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh\n"


def _block(tmp_path):
    block = tmp_path / "block"
    block.mkdir()
    (block / "bus.csv").write_text("bus_id,type\n1,3\n2,1\n3,1\n", encoding="utf-8")
    (block / "bus_load_base.csv").write_text("bus_id,base_load_mw\n1,10\n2,20\n3,30\n", encoding="utf-8")
    (block / "branch_limits.csv").write_text(
        "branch_id,from_bus_id,to_bus_id,reactance_pu,thermal_limit_mva,status\n"
        "b1,1,2,0.1,100,1\nb2,2,3,0.1,50,1\nb3,1,3,0.1,80,0\n",
        encoding="utf-8",
    )
    return block


WITHDRAWAL_HEADER = (
    "period_index,team_id,site_id,bus_id,load_mw,generation_mw,"
    "storage_discharge_mw,storage_charge_mw,net_withdrawal_mw\n"
)


def _evaluation(tmp_path, name="eval", rows=None):
    """An evaluator output: only scored (feasible) teams' sites, at served MW."""
    folder = tmp_path / name
    folder.mkdir()
    rows = rows or [
        # team-alpha served at 0.5 of 40 + 10 MW; team-beta in full; team-gone
        # was dropped by the minimum allocation (served 0 MW).
        ("team-alpha", "site-x", "2", 20.0),
        ("team-alpha", "site-y", "3", 5.0),
        ("team-beta", "site-z", "2", 25.0),
        ("team-gone", "site-w", "1", 0.0),
    ]
    lines = [
        f"{period},{team},{site},{bus},{mw},0,0,0,{mw}\n"
        for team, site, bus, mw in rows
        for period in range(2)
    ]
    (folder / "site_net_withdrawal.csv").write_text(WITHDRAWAL_HEADER + "".join(lines), encoding="utf-8")
    return folder


def test_served_load_is_aggregated_per_bus_and_dropped_teams_add_nothing(tmp_path):
    totals, sites = served_load_by_bus([_evaluation(tmp_path)])
    assert sites == 3
    assert totals == {"2": 45.0, "3": 5.0}


def test_submission_two_map_adds_submission_one_sites_but_not_rejected_files(tmp_path):
    # A rejected Submission 2 file (e.g. a reused Submission 1 site ID) is not
    # in the evaluator output, so only scored sites of both outputs appear.
    s1 = _evaluation(tmp_path, "s1")
    s2 = _evaluation(tmp_path, "s2", rows=[("team-beta", "site-new", "3", 7.5)])
    totals, _ = served_load_by_bus([s1, s2])
    assert totals == {"2": 45.0, "3": 12.5}


def test_branch_loading_reports_peak_ratio_and_hours_at_limit(tmp_path):
    dispatch = tmp_path / "dispatch"
    dispatch.mkdir()
    for hour, flows in enumerate(({"b1": 30.0, "b2": -50.0}, {"b1": -80.0, "b2": 10.0})):
        (dispatch / f"period_{hour}.json").write_text(json.dumps({"flow_mw_by_branch": flows}), encoding="utf-8")
    branches = (MapBranch("b1", "1", "2", 100.0), MapBranch("b2", "2", "3", 50.0))
    loading, hours = branch_loading(dispatch, branches)
    assert hours == 2
    assert loading["b1"] == (0.8, 0)
    assert loading["b2"] == (1.0, 1)


def test_layout_is_deterministic_and_normalized():
    buses = ("1", "2", "3", "4", "5")
    branches = tuple(MapBranch(f"b{i}", a, b, 1.0) for i, (a, b) in enumerate((("1", "2"), ("2", "3"), ("3", "4"), ("4", "5"))))
    first = compute_layout(buses, branches, iterations=50)
    assert first == compute_layout(buses, branches, iterations=50)
    assert all(0.0 <= value <= 1.0 for point in first.values() for value in point)


def test_svg_is_valid_interactive_and_hides_team_identity(tmp_path):
    block = _block(tmp_path)
    output = tmp_path / "map.svg"
    layout = tmp_path / "layout.json"
    assert main([
        "--artifact-dir", str(block),
        "--evaluation-dir", str(_evaluation(tmp_path)),
        "--layout", str(layout),
        "--title", "Week 2 Submission 1",
        "--output", str(output),
    ]) == 0
    svg = output.read_text(encoding="utf-8")
    xml.dom.minidom.parseString(svg)
    assert "team-" not in svg and "site-" not in svg
    assert "all teams): 45.0 MW" in svg
    assert "<title>" in svg and "<script>" in svg
    assert "b3" not in svg  # out-of-service branch is not drawn
    assert json.loads(layout.read_text(encoding="utf-8"))["positions"].keys() == {"1", "2", "3"}


def test_render_without_dispatch_draws_neutral_lines():
    svg = render_svg(
        positions={"1": (0.0, 0.0), "2": (1.0, 0.5)},
        branches=(MapBranch("b1", "1", "2", 10.0),),
        connection_by_bus={},
    )
    assert "Peak line loading" not in svg
    assert "#c9ced6" in svg


def test_loading_legend_reports_hours():
    svg = render_svg(
        positions={"1": (0.0, 0.0), "2": (1.0, 0.5)},
        branches=(MapBranch("b1", "1", "2", 10.0),),
        connection_by_bus={},
        loading_by_branch={"b1": (1.0, 3)},
        hours=120,
    )
    assert "Peak line loading over 120 h" in svg
    assert "at or near limit in 3 of 120 h" in svg


def test_geographic_layout_draws_background_outline_and_note(tmp_path):
    from ercot_game.grid_map import load_layout_background

    layout = tmp_path / "geo.json"
    layout.write_text(json.dumps({
        "positions": {"1": [0.1, 0.1], "2": [0.9, 0.5]},
        "background_paths": [[[0.0, 0.0], [1.0, 0.0], [1.0, 0.6], [0.0, 0.6]]],
        "provenance": {"kind": "approximate geographic"},
    }), encoding="utf-8")
    paths, kind = load_layout_background(layout)
    svg = render_svg(
        positions={"1": (0.1, 0.1), "2": (0.9, 0.5)},
        branches=(MapBranch("b1", "1", "2", 10.0),),
        connection_by_bus={"2": 5.0},
        background_paths=paths,
        layout_kind=kind,
    )
    xml.dom.minidom.parseString(svg)
    assert "<polygon" in svg
    assert "Approximate geographic layout" in svg
    assert "Schematic layout" not in svg
