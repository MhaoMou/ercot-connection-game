from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.zenodo_texas import dcopf
from tools.zenodo_texas.dcopf import DCOPFResult, load_prepared_artifact, solve_prepared_period
from tools.zenodo_texas.prepare_dispatch import prepare_dispatch_source


def _write(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _extracted_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "extracted"
    root.mkdir()
    _write(
        root / "bus.csv",
        ["bus_id", "Pd", "Qd", "zone_id", "baseKV", "Vmax", "Vmin"],
        [
            {"bus_id": "b1", "Pd": "25", "Qd": "5", "zone_id": "301", "baseKV": "115", "Vmax": "1.1", "Vmin": "0.9"},
            {"bus_id": "b2", "Pd": "75", "Qd": "15", "zone_id": "301", "baseKV": "230", "Vmax": "1.1", "Vmin": "0.9"},
        ],
    )
    _write(
        root / "zone.csv",
        ["zone_id", "zone_name", "interconnect"],
        [{"zone_id": "301", "zone_name": "Far West", "interconnect": "Texas"}],
    )
    _write(
        root / "demand.csv",
        ["UTC Time", "301"],
        [{"UTC Time": "2016-01-01 00:00:00", "301": "100"}],
    )
    _write(
        root / "plant.csv",
        ["plant_id", "bus_id", "Pmin", "Pmax", "Qmin", "Qmax", "ramp_10", "status", "type"],
        [{"plant_id": "p1", "bus_id": "b1", "Pmin": "0", "Pmax": "50", "Qmin": "-10", "Qmax": "10", "ramp_10": "20", "status": "1", "type": "ng"}],
    )
    _write(
        root / "gencost.csv",
        ["plant_id", "c2", "c1", "c0"],
        [{"plant_id": "p1", "c2": "0.1", "c1": "5", "c0": "10"}],
    )
    _write(
        root / "branch.csv",
        ["branch_id", "from_bus_id", "to_bus_id", "rateA", "status", "r", "x", "b", "branch_device_type"],
        [{"branch_id": "br1", "from_bus_id": "b1", "to_bus_id": "b2", "rateA": "100", "status": "1", "r": "0.01", "x": "0.1", "b": "0.02", "branch_device_type": "Line"}],
    )
    return root


def test_expands_zonal_demand_using_bus_pd_shares(tmp_path: Path):
    output = prepare_dispatch_source(_extracted_fixture(tmp_path), tmp_path / "prepared")

    with (tmp_path / "prepared" / "demand_bus.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{"UTC Time": "2016-01-01 00:00:00", "b1": "25.0", "b2": "75.0"}]
    assert output["demand_expansion"]["zone_count"] == 1
    assert output["demand_expansion"]["bus_count"] == 2


def test_writes_explicit_generator_and_branch_units(tmp_path: Path):
    prepare_dispatch_source(_extracted_fixture(tmp_path), tmp_path / "prepared")

    manifest = json.loads((tmp_path / "prepared" / "dispatch_manifest.json").read_text())
    assert manifest["units"]["generator_limits"]["p_max"] == "MW"
    assert manifest["units"]["branch_limits"]["thermal_limit"] == "MVA"
    assert manifest["generator_count"] == 1
    assert manifest["branch_count"] == 1

    with (tmp_path / "prepared" / "generator_limits.csv").open(newline="", encoding="utf-8") as handle:
        generator = next(csv.DictReader(handle))
    assert generator["p_max_mw"] == "50.0"
    assert generator["marginal_cost_c1_per_mwh"] == "5.0"


def test_rejects_zero_pd_zone_share(tmp_path: Path):
    root = _extracted_fixture(tmp_path)
    rows = [{"bus_id": "b1", "Pd": "0", "Qd": "0", "zone_id": "301", "baseKV": "115", "Vmax": "1.1", "Vmin": "0.9"}]
    _write(root / "bus.csv", ["bus_id", "Pd", "Qd", "zone_id", "baseKV", "Vmax", "Vmin"], rows)

    with pytest.raises(ValueError, match="zero base Pd"):
        prepare_dispatch_source(root, tmp_path / "prepared")


def test_copies_aligned_renewable_profiles_into_prepared_artifact(tmp_path: Path):
    root = _extracted_fixture(tmp_path)
    _write(root / "dcline.csv", ["status", "to_bus_id", "Pt"], [{"status": "0", "to_bus_id": "b1", "Pt": "0"}])
    _write(
        root / "solar.csv",
        ["UTC", "p1"],
        [{"UTC": "2016-01-01 00:00:00", "p1": "0"}],
    )
    _write(
        root / "wind.csv",
        ["UTC", "p-wind"],
        [{"UTC": "2016-01-01 00:00:00", "p-wind": "12"}],
    )
    _write(
        root / "hydro.csv",
        ["UTC", "p-hydro"],
        [{"UTC": "2016-01-01 00:00:00", "p-hydro": "7"}],
    )

    manifest = prepare_dispatch_source(root)

    artifact = load_prepared_artifact(str(root.resolve()))
    assert artifact.renewable_profile_mw_by_generator == {
        "p-hydro": (7.0,),
        "p-wind": (12.0,),
        "p1": (0.0,),
    }
    assert set(manifest["renewable_profiles"]) == {"solar.csv", "wind.csv", "hydro.csv"}
    for profile in manifest["renewable_profiles"].values():
        assert profile["timestamp_column"] == "UTC"
        assert profile["demand_timestamp_column"] == "UTC Time"
        assert profile["value_units"] == "MW"


def test_rejects_renewable_profile_timestamp_mismatch(tmp_path: Path):
    root = _extracted_fixture(tmp_path)
    _write(root / "dcline.csv", ["status", "to_bus_id", "Pt"], [{"status": "0", "to_bus_id": "b1", "Pt": "0"}])
    _write(
        root / "solar.csv",
        ["UTC", "p1"],
        [{"UTC": "2016-01-01 01:00:00", "p1": "0"}],
    )

    with pytest.raises(ValueError, match="solar.csv.*timestamp"):
        prepare_dispatch_source(root, tmp_path / "prepared")


def test_rejects_renewable_profile_row_count_mismatch(tmp_path: Path):
    root = _extracted_fixture(tmp_path)
    _write(
        root / "wind.csv",
        ["UTC", "p1"],
        [],
    )

    with pytest.raises(ValueError, match="wind.csv.*row count"):
        prepare_dispatch_source(root, tmp_path / "prepared")


def test_rejects_renewable_profile_with_unknown_timestamp_column(tmp_path: Path):
    root = _extracted_fixture(tmp_path)
    _write(
        root / "solar.csv",
        ["local_time", "p1"],
        [{"local_time": "2016-01-01 00:00:00", "p1": "0"}],
    )

    with pytest.raises(ValueError, match="solar.csv.*timestamp column"):
        prepare_dispatch_source(root, tmp_path / "prepared")


def test_zero_solar_profile_does_not_cap_classroom_dispatch(tmp_path: Path, monkeypatch):
    root = _extracted_fixture(tmp_path)
    _write(root / "dcline.csv", ["status", "to_bus_id", "Pt"], [{"status": "0", "to_bus_id": "b1", "Pt": "0"}])
    plant_rows = [{
        "plant_id": "p1",
        "bus_id": "b1",
        "Pmin": "0",
        "Pmax": "50",
        "Qmin": "-10",
        "Qmax": "10",
        "ramp_10": "20",
        "status": "1",
        "type": "solar",
    }]
    _write(root / "plant.csv", list(plant_rows[0]), plant_rows)
    _write(
        root / "solar.csv",
        ["UTC", "p1"],
        [{"UTC": "2016-01-01 00:00:00", "p1": "0"}],
    )
    prepare_dispatch_source(root)
    captured = []

    def fake_solve_dcopf(*, buses, generators, branches, fixed_injection_mw_by_bus, base_mva):
        captured.extend(generators)
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={generator.generator_id: 0.0 for generator in generators},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr(dcopf, "solve_dcopf", fake_solve_dcopf)
    solve_prepared_period(root, period_index=0)

    solar = next(generator for generator in captured if generator.generator_id == "p1")
    assert solar.p_max_mw == 50.0


def test_nonzero_solar_profile_does_not_cap_classroom_dispatch(tmp_path: Path, monkeypatch):
    root = _extracted_fixture(tmp_path)
    _write(root / "dcline.csv", ["status", "to_bus_id", "Pt"], [{"status": "0", "to_bus_id": "b1", "Pt": "0"}])
    plant_rows = [{
        "plant_id": "p1",
        "bus_id": "b1",
        "Pmin": "0",
        "Pmax": "50",
        "Qmin": "-10",
        "Qmax": "10",
        "ramp_10": "20",
        "status": "1",
        "type": "solar",
    }]
    _write(root / "plant.csv", list(plant_rows[0]), plant_rows)
    _write(
        root / "solar.csv",
        ["UTC", "p1"],
        [{"UTC": "2016-01-01 00:00:00", "p1": "30"}],
    )
    prepare_dispatch_source(root)
    captured = []

    def fake_solve_dcopf(*, buses, generators, branches, fixed_injection_mw_by_bus, base_mva):
        captured.extend(generators)
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={generator.generator_id: 0.0 for generator in generators},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr(dcopf, "solve_dcopf", fake_solve_dcopf)
    solve_prepared_period(root, period_index=0)

    solar = next(generator for generator in captured if generator.generator_id == "p1")
    assert solar.p_max_mw == 50.0


def test_nonrenewable_generator_keeps_nameplate_limit_with_profile_file(tmp_path: Path, monkeypatch):
    root = _extracted_fixture(tmp_path)
    _write(root / "dcline.csv", ["status", "to_bus_id", "Pt"], [{"status": "0", "to_bus_id": "b1", "Pt": "0"}])
    _write(
        root / "solar.csv",
        ["UTC", "p1"],
        [{"UTC": "2016-01-01 00:00:00", "p1": "0"}],
    )
    prepare_dispatch_source(root)
    captured = []

    def fake_solve_dcopf(*, buses, generators, branches, fixed_injection_mw_by_bus, base_mva):
        captured.extend(generators)
        return DCOPFResult(
            status="optimal",
            objective_cost=0.0,
            generation_mw={generator.generator_id: 0.0 for generator in generators},
            angle_by_bus={},
            flow_mw_by_branch={},
            balance_dual_by_bus={},
        )

    monkeypatch.setattr(dcopf, "solve_dcopf", fake_solve_dcopf)
    solve_prepared_period(root, period_index=0)

    nonrenewable = next(generator for generator in captured if generator.generator_id == "p1")
    assert nonrenewable.p_max_mw == 50.0
