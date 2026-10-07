from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from ercot_game.results_artifacts import (
    ResultsArtifactError,
    sanitize_results_package,
    validate_results_package,
)
from scripts.build_results_package import build_results_package


def write_source_fixture(tmp_path: Path) -> tuple[Path, Path]:
    network_dir = tmp_path / "network"
    network_dir.mkdir()
    with (network_dir / "bus.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bus_id", "baseKV"])
        writer.writeheader()
        writer.writerows([
            {"bus_id": "bus-1", "baseKV": "138"},
            {"bus_id": "bus-2", "baseKV": "138"},
        ])
    with (network_dir / "bus2sub.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bus_id", "sub_id"])
        writer.writeheader()
        writer.writerows([
            {"bus_id": "bus-1", "sub_id": "sub-1"},
            {"bus_id": "bus-2", "sub_id": "sub-2"},
        ])
    with (network_dir / "sub.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sub_id", "lat", "lon"])
        writer.writeheader()
        writer.writerows([
            {"sub_id": "sub-1", "lat": "30.2", "lon": "-97.5"},
            {"sub_id": "sub-2", "lat": "31.0", "lon": "-96.8"},
        ])
    with (network_dir / "branch.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["branch_id", "from_bus_id", "to_bus_id", "rateA"],
        )
        writer.writeheader()
        writer.writerow(
            {"branch_id": "branch-1", "from_bus_id": "bus-1", "to_bus_id": "bus-2", "rateA": "100"}
        )

    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text(json.dumps({
        "round": {
            "round_id": "fixture-round",
            "round_name": "Synthetic fixture only (not production Zenodo data)",
            "horizon": "2028-H1",
        },
        "team_scores": [{
            "team_id": "team-alpha", "score": 1250.5, "feasible": True,
            "served_load_mwh": 80.0, "it_value": 1600.0,
            "energy_cost": 250.0, "site_cost": 50.0,
            "generator_capital_cost": 0.0, "generator_operating_cost": 0.0,
            "storage_capital_cost": 0.0, "storage_operating_cost": 0.0,
        }],
        "team_reports": [{
            "team_id": "team-alpha",
            "sites": [{"site_id": "site-1", "bus_id": "bus-1", "load_mw": 40.0}],
        }],
        "aggregate": {
            "team_count": 1,
            "region_utilization": [{"region_id": "region-1", "utilization": 0.876}],
        },
    }))
    return network_dir, evaluation_path


def valid_package() -> dict[str, object]:
    return {
        "schema_version": "results.v1",
        "round": {
            "round_id": "round-01",
            "horizon": "2028-H1",
        },
        "network": {
            "buses": [
                {"bus_id": "bus-1", "lon": -97.5, "lat": 30.2},
                {"bus_id": "bus-2", "lon": -96.8, "lat": 31.0},
            ],
            "branches": [
                {
                    "branch_id": "branch-1",
                    "from_bus": "bus-1",
                    "to_bus": "bus-2",
                    "capacity_mw": 100.0,
                }
            ],
        },
        "team_report": {
            "team_id": "team-alpha",
            "score": 1250.5,
            "sites": [{"site_id": "site-1", "bus_id": "bus-1", "load_mw": 40.0}],
        },
        "aggregate": {
            "team_count": 3,
            "region_utilization": [{"region_id": "region-1", "utilization": 0.5}],
        },
        "privacy_policy": {
            "selected_team_only": True,
            "minimum_aggregate_teams": 3,
        },
    }


def test_valid_results_package_is_accepted_and_detached():
    payload = valid_package()

    result = validate_results_package(payload)

    assert result == payload
    assert result is not payload
    assert result["network"] is not payload["network"]


def test_results_package_requires_all_top_level_contract_fields():
    required = {
        "schema_version",
        "round",
        "network",
        "team_report",
        "aggregate",
        "privacy_policy",
    }

    for field in required:
        payload = valid_package()
        del payload[field]
        with pytest.raises(ResultsArtifactError, match=field):
            validate_results_package(payload)


@pytest.mark.parametrize("forbidden_key", ["raw_submissions", "all_teams", "joint_csv"])
def test_results_package_rejects_raw_or_cross_team_payloads(forbidden_key: str):
    payload = valid_package()
    payload["team_report"][forbidden_key] = {"team-beta": {"load": [1.0]}}

    with pytest.raises(ResultsArtifactError, match=forbidden_key):
        validate_results_package(payload)


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "audit_bundle",
        "audit_bundles",
        "unredacted_audit",
        "unredacted_audit_bundle",
        "unredacted_audit_bundles",
    ],
)
def test_results_package_rejects_unredacted_audit_bundles(forbidden_key: str):
    payload = valid_package()
    payload["aggregate"][forbidden_key] = {"team-alpha": {"raw_plan": []}}

    with pytest.raises(ResultsArtifactError, match=forbidden_key):
        validate_results_package(payload)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_results_package_rejects_non_finite_numeric_values(bad_value: float):
    payload = valid_package()
    payload["team_report"]["score"] = bad_value

    with pytest.raises(ResultsArtifactError, match="finite"):
        validate_results_package(payload)


@pytest.mark.parametrize("field", ["bus_id", "branch_id", "from_bus", "to_bus"])
def test_results_package_rejects_empty_identifiers(field: str):
    payload = valid_package()
    if field == "bus_id":
        payload["network"]["buses"][0][field] = "  "
    elif field == "branch_id":
        payload["network"]["branches"][0][field] = ""
    else:
        payload["network"]["branches"][0][field] = ""

    with pytest.raises(ResultsArtifactError, match=field):
        validate_results_package(payload)


def test_results_package_rejects_branch_endpoint_not_in_network():
    payload = valid_package()
    payload["network"]["branches"][0]["to_bus"] = "bus-missing"

    with pytest.raises(ResultsArtifactError, match="to_bus"):
        validate_results_package(payload)


def test_results_package_rejects_team_site_at_unknown_bus():
    payload = valid_package()
    payload["team_report"]["sites"][0]["bus_id"] = "bus-missing"

    with pytest.raises(ResultsArtifactError, match="team_report.sites.*bus_id"):
        validate_results_package(payload)


def test_results_package_rejects_non_finite_coordinates():
    payload = valid_package()
    payload["network"]["buses"][0]["lat"] = float("nan")

    with pytest.raises(ResultsArtifactError, match="lat.*finite"):
        validate_results_package(payload)


def test_sanitize_results_package_returns_safe_copy_without_mutating_input():
    payload = valid_package()
    original = copy.deepcopy(payload)

    sanitized = sanitize_results_package(payload)

    assert sanitized == original
    assert sanitized is not payload
    assert sanitized["team_report"] is not payload["team_report"]
    sanitized["team_report"]["score"] = 0
    assert payload["team_report"]["score"] == original["team_report"]["score"]


def test_sanitize_results_package_projects_unrecognized_nested_aggregate_data():
    payload = valid_package()
    payload["aggregate"]["plans"] = {"team-beta": {"sites": [{"bus_id": "bus-2"}]}}

    sanitized = sanitize_results_package(payload)

    assert "plans" not in sanitized["aggregate"]


def test_sanitize_results_package_projects_unrecognized_nested_team_data():
    payload = valid_package()
    payload["team_report"]["notes"] = {"other_team": {"strategy": "secret"}}

    sanitized = sanitize_results_package(payload)

    assert "notes" not in sanitized["team_report"]


def test_build_results_package_writes_four_sanitized_files(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)

    output = build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "results",
        team_id="team-alpha",
    )

    assert sorted(path.name for path in output) == [
        "aggregate_grid_summary.json",
        "public_network.json",
        "round_metadata.json",
        "team_report.json",
    ]


def test_build_results_package_preserves_real_coordinates_and_selected_team_only(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)
    output_dir = tmp_path / "results"

    build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=output_dir,
        team_id="team-alpha",
    )

    network = json.loads((output_dir / "public_network.json").read_text())
    assert network["buses"] == [
        {"bus_id": "bus-1", "lat": 30.2, "lon": -97.5},
        {"bus_id": "bus-2", "lat": 31.0, "lon": -96.8},
    ]
    assert network["branches"] == [{
        "branch_id": "branch-1", "from_bus": "bus-1", "to_bus": "bus-2",
        "capacity_mw": 100.0,
    }]
    team = json.loads((output_dir / "team_report.json").read_text())
    assert team["team_id"] == "team-alpha"
    assert "team-beta" not in json.dumps(team)


def test_build_results_package_can_project_selected_submission_into_map_resources(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)
    data = json.loads(evaluation_path.read_text())
    data["team_reports"] = []
    evaluation_path.write_text(json.dumps(data))
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    (submissions / "team-alpha.csv").write_text(
        "team_id,submission_id,period,bus_id,load_mw,generator_id,generator_capacity_mw,storage_id,storage_power_mw,storage_energy_mwh\n"
        "team-alpha,submission-1,1,bus-1,40,generator-1,10,storage-1,5,20\n"
        "team-alpha,submission-1,2,bus-1,30,generator-1,10,storage-1,5,20\n"
    )

    build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "results",
        team_id="team-alpha",
        submissions_dir=submissions,
    )

    team = json.loads((tmp_path / "results" / "team_report.json").read_text())
    assert team["sites"] == [{"site_id": "site-bus-1", "bus_id": "bus-1", "load_mw": 40.0}]
    assert team["generators"] == [{"generator_id": "generator-1", "bus_id": "bus-1", "capacity_mw": 10.0}]
    assert team["storage"] == [{"storage_id": "storage-1", "bus_id": "bus-1", "power_mw": 5.0, "energy_mwh": 20.0}]


def test_build_results_package_does_not_fabricate_missing_coordinates(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)
    with (network_path / "bus.csv").open("a", encoding="utf-8") as handle:
        handle.write("bus-3,230\n")

    build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "results",
        team_id="team-alpha",
    )

    buses = json.loads((tmp_path / "results" / "public_network.json").read_text())["buses"]
    bus = next(item for item in buses if item["bus_id"] == "bus-3")
    assert "lat" not in bus
    assert "lon" not in bus


def test_build_results_package_suppresses_small_aggregate_groups(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)
    data = json.loads(evaluation_path.read_text())
    data["aggregate"]["team_count"] = 99
    evaluation_path.write_text(json.dumps(data))

    build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "results",
        team_id="team-alpha",
    )

    aggregate = json.loads((tmp_path / "results" / "aggregate_grid_summary.json").read_text())
    assert aggregate["metrics"]["team_count"] == 1
    assert aggregate["region_utilization"] == []


def test_build_results_package_suppresses_aggregate_with_inflated_declared_count(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)
    data = json.loads(evaluation_path.read_text())
    data["aggregate"]["team_count"] = 99
    data["aggregate"]["region_utilization"] = [
        {"region_id": "region-1", "utilization": 0.876},
    ]
    evaluation_path.write_text(json.dumps(data))

    build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=tmp_path / "results",
        team_id="team-alpha",
    )

    aggregate = json.loads((tmp_path / "results" / "aggregate_grid_summary.json").read_text())
    assert aggregate["metrics"]["team_count"] == 1
    assert aggregate["region_utilization"] == []


def test_build_results_package_is_byte_for_byte_deterministic(tmp_path):
    network_path, evaluation_path = write_source_fixture(tmp_path)
    first_dir = tmp_path / "results-first"
    second_dir = tmp_path / "results-second"

    build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=first_dir,
        team_id="team-alpha",
    )
    build_results_package(
        network_path=network_path,
        evaluation_path=evaluation_path,
        output_dir=second_dir,
        team_id="team-alpha",
    )

    for name in (
        "aggregate_grid_summary.json",
        "public_network.json",
        "round_metadata.json",
        "team_report.json",
    ):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()
