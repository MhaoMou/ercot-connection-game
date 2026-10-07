#!/usr/bin/env python3
"""Build the four browser-facing artifacts for a published results round.

The builder deliberately has no dependency on the evaluator.  It consumes the
prepared public dispatch directory and an evaluation/audit JSON document, then
projects those inputs into the small, selected-team-only contract used by the
read-only results viewer.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "results.v1"
MIN_AGGREGATE_TEAMS = 3
MIN_AGGREGATE_CELL_TEAMS = 2
ARTIFACT_NAMES = (
    "aggregate_grid_summary.json",
    "public_network.json",
    "round_metadata.json",
    "team_report.json",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _number(value: object) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _first_number(record: Mapping[str, object], names: Iterable[str]) -> int | float | None:
    for name in names:
        value = _number(record.get(name))
        if value is not None:
            return value
    return None


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _coordinate_lookup(network_path: Path) -> dict[str, tuple[float, float]]:
    """Return source coordinates keyed by bus ID, without geographic guesses."""
    coordinates: dict[str, tuple[float, float]] = {}
    bus_rows = _read_csv(network_path / "bus.csv")
    for row in bus_rows:
        lat = _first_number(row, ("lat", "latitude", "y"))
        lon = _first_number(row, ("lon", "longitude", "x"))
        if lat is not None and lon is not None:
            coordinates[row["bus_id"]] = (float(lat), float(lon))

    bus_to_sub = {
        row.get("bus_id", ""): row.get("sub_id", "")
        for row in _read_csv(network_path / "bus2sub.csv")
        if row.get("bus_id") and row.get("sub_id")
    }
    for row in _read_csv(network_path / "sub.csv"):
        lat = _first_number(row, ("lat", "latitude", "y"))
        lon = _first_number(row, ("lon", "longitude", "x"))
        if lat is None or lon is None:
            continue
        sub_id = row.get("sub_id", "")
        for bus_id, mapped_sub_id in bus_to_sub.items():
            if mapped_sub_id == sub_id and bus_id not in coordinates:
                coordinates[bus_id] = (float(lat), float(lon))
    return coordinates


def _build_network(network_path: Path) -> dict[str, object]:
    coordinates = _coordinate_lookup(network_path)
    buses: list[dict[str, object]] = []
    for row in _read_csv(network_path / "bus.csv"):
        bus_id = row.get("bus_id", "").strip()
        if not bus_id:
            continue
        record: dict[str, object] = {"bus_id": bus_id}
        if bus_id in coordinates:
            lat, lon = coordinates[bus_id]
            record.update({"lat": lat, "lon": lon})
        buses.append(record)

    limit_by_branch: dict[str, int | float] = {}
    limits_path = network_path / "branch_limits.csv"
    if limits_path.exists():
        for row in _read_csv(limits_path):
            value = _first_number(row, ("thermal_limit_mva", "rateA", "capacity_mw"))
            if row.get("branch_id") and value is not None:
                limit_by_branch[row["branch_id"]] = value

    branches: list[dict[str, object]] = []
    for row in _read_csv(network_path / "branch.csv"):
        branch_id = row.get("branch_id", "").strip()
        from_bus = row.get("from_bus_id", "").strip()
        to_bus = row.get("to_bus_id", "").strip()
        if not branch_id or not from_bus or not to_bus:
            continue
        capacity = limit_by_branch.get(branch_id)
        if capacity is None:
            capacity = _first_number(row, ("rateA", "capacity_mw", "thermal_limit_mva"))
        record: dict[str, object] = {
            "branch_id": branch_id,
            "from_bus": from_bus,
            "to_bus": to_bus,
        }
        if capacity is not None:
            record["capacity_mw"] = capacity
        branches.append(record)

    buses.sort(key=lambda item: str(item["bus_id"]))
    branches.sort(key=lambda item: str(item["branch_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "network_id": "zenodo-texas-dispatch-source-v1",
        "buses": buses,
        "branches": branches,
    }


def _team_score(evaluation: Mapping[str, object], team_id: str) -> dict[str, object]:
    scores = evaluation.get("team_scores", [])
    if not isinstance(scores, list):
        return {"team_id": team_id, "feasible": False, "score": None}
    for score in scores:
        if isinstance(score, Mapping) and score.get("team_id") == team_id:
            return dict(score)
    return {"team_id": team_id, "feasible": False, "score": None}


def _team_source_report(evaluation: Mapping[str, object], team_id: str) -> Mapping[str, object]:
    for key in ("team_report", "selected_team_report"):
        report = evaluation.get(key)
        if isinstance(report, Mapping) and report.get("team_id") == team_id:
            return report
    reports = evaluation.get("team_reports", [])
    if isinstance(reports, list):
        for report in reports:
            if isinstance(report, Mapping) and report.get("team_id") == team_id:
                return report
    diagnostics = evaluation.get("team_diagnostics", {})
    if isinstance(diagnostics, Mapping):
        diagnostic = diagnostics.get(team_id)
        if isinstance(diagnostic, Mapping):
            report = diagnostic.get("team_report")
            if isinstance(report, Mapping):
                return report
    return {}


def _records(report: Mapping[str, object], key: str, fields: tuple[str, ...]) -> list[dict[str, object]]:
    source = report.get(key, [])
    if not isinstance(source, list):
        return []
    result: list[dict[str, object]] = []
    for item in source:
        if not isinstance(item, Mapping):
            continue
        result.append({field: item[field] for field in fields if field in item})
    return sorted(result, key=lambda item: json.dumps(item, sort_keys=True))


def _submission_team_report(submission_path: Path, team_id: str) -> dict[str, list[dict[str, object]]]:
    """Project one team's CSV plan into privacy-safe map resource records."""
    sites: dict[str, dict[str, object]] = {}
    generators: dict[tuple[str, str], dict[str, object]] = {}
    storage: dict[tuple[str, str], dict[str, object]] = {}
    with submission_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("team_id", "").strip() != team_id:
                continue
            bus_id = row.get("bus_id", "").strip()
            if not bus_id:
                continue
            load = _number(row.get("load_mw"))
            site = sites.setdefault("site-" + bus_id, {"site_id": "site-" + bus_id, "bus_id": bus_id})
            if load is not None and ("load_mw" not in site or float(load) > float(site["load_mw"])):
                site["load_mw"] = load

            generator_id = row.get("generator_id", "").strip()
            if generator_id:
                key = (generator_id, bus_id)
                generator = generators.setdefault(key, {"generator_id": generator_id, "bus_id": bus_id})
                capacity = _number(row.get("generator_capacity_mw"))
                if capacity is not None and ("capacity_mw" not in generator or float(capacity) > float(generator["capacity_mw"])):
                    generator["capacity_mw"] = capacity

            storage_id = row.get("storage_id", "").strip()
            if storage_id:
                key = (storage_id, bus_id)
                device = storage.setdefault(key, {"storage_id": storage_id, "bus_id": bus_id})
                power = _number(row.get("storage_power_mw"))
                energy = _number(row.get("storage_energy_mwh"))
                if power is not None and ("power_mw" not in device or float(power) > float(device["power_mw"])):
                    device["power_mw"] = power
                if energy is not None and ("energy_mwh" not in device or float(energy) > float(device["energy_mwh"])):
                    device["energy_mwh"] = energy
    return {
        "sites": sorted(sites.values(), key=lambda item: str(item["site_id"])),
        "generators": sorted(generators.values(), key=lambda item: (str(item["generator_id"]), str(item["bus_id"]))),
        "storage": sorted(storage.values(), key=lambda item: (str(item["storage_id"]), str(item["bus_id"]))),
    }


def _build_team_report(
    evaluation: Mapping[str, object], team_id: str, submission_path: Path | None = None
) -> dict[str, object]:
    score = _team_score(evaluation, team_id)
    source = _team_source_report(evaluation, team_id)
    numeric_fields = (
        "score", "it_value", "energy_cost", "site_cost", "served_load_mwh",
        "generator_capital_cost", "generator_operating_cost",
        "storage_capital_cost", "storage_operating_cost",
    )
    breakdown = {
        field: score[field]
        for field in numeric_fields
        if field in score and isinstance(score[field], (int, float)) and math.isfinite(float(score[field]))
    }
    requested = _number(score.get("requested_load_mwh"))
    served = _number(score.get("served_load_mwh"))
    service_fraction = _number(score.get("service_fraction"))
    if service_fraction is None and requested not in (None, 0) and served is not None:
        service_fraction = max(0.0, min(1.0, float(served) / float(requested)))
    sites = _records(source, "sites", ("site_id", "bus_id", "load_mw"))
    generators = _records(source, "generators", ("generator_id", "bus_id", "capacity_mw"))
    storage = _records(source, "storage", ("storage_id", "bus_id", "power_mw", "energy_mwh"))
    if submission_path is not None and not sites and submission_path.exists():
        projected = _submission_team_report(submission_path, team_id)
        sites, generators, storage = projected["sites"], projected["generators"], projected["storage"]
    return {
        "schema_version": SCHEMA_VERSION,
        "team_id": team_id,
        "feasibility": "feasible" if score.get("feasible") is True else "infeasible",
        "service_fraction": service_fraction,
        "score": score.get("score"),
        "score_breakdown": breakdown,
        "sites": sites,
        "generators": generators,
        "storage": storage,
    }


def _verified_contributing_team_ids(evaluation: Mapping[str, object]) -> set[str]:
    """Return unique team IDs verified by the evaluator's score records."""
    scores = evaluation.get("team_scores", [])
    if not isinstance(scores, list):
        return set()
    team_ids: set[str] = set()
    for item in scores:
        if not isinstance(item, Mapping) or item.get("valid") is False:
            continue
        team_id = item.get("team_id")
        if isinstance(team_id, str) and team_id.strip():
            team_ids.add(team_id.strip())
    return team_ids


def _build_aggregate(
    evaluation: Mapping[str, object],
    *,
    network_path: Path | None = None,
    submissions_dir: Path | None = None,
) -> dict[str, object]:
    team_count = len(_verified_contributing_team_ids(evaluation))
    aggregate_source = evaluation.get("aggregate", {})
    if not isinstance(aggregate_source, Mapping):
        aggregate_source = {}
    metrics: dict[str, object] = {"team_count": team_count}
    diagnostics = evaluation.get("aggregate_diagnostics", {})
    if isinstance(diagnostics, Mapping):
        for key in ("dispatch_count", "period_count", "total_objective_cost"):
            value = _number(diagnostics.get(key))
            if value is not None:
                metrics[key] = value
    region_utilization = aggregate_source.get("region_utilization", [])
    if team_count < MIN_AGGREGATE_TEAMS or not isinstance(region_utilization, list):
        region_utilization = []
    else:
        region_utilization = [
            {"region_id": item["region_id"], "utilization": round(float(item["utilization"]), 3)}
            for item in region_utilization
            if isinstance(item, Mapping) and item.get("region_id") and _number(item.get("utilization")) is not None
        ]
    aggregate_plan: list[dict[str, object]] = []
    if network_path is not None and submissions_dir is not None and team_count >= MIN_AGGREGATE_TEAMS:
        coordinates = _coordinate_lookup(network_path)
        by_cell: dict[tuple[int, int], dict[str, object]] = {}
        for path in sorted(submissions_dir.glob("*.csv")):
            try:
                rows = _read_csv(path)
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
            team_ids = {str(row.get("team_id", "")).strip() for row in rows}
            valid_team_ids = team_ids & _verified_contributing_team_ids(evaluation)
            if not valid_team_ids:
                continue
            team_id = sorted(valid_team_ids)[0]
            team_cells: dict[tuple[int, int], dict[str, object]] = {}
            for row in rows:
                if str(row.get("team_id", "")).strip() != team_id:
                    continue
                bus_id = str(row.get("bus_id", "")).strip()
                point = coordinates.get(bus_id)
                if point is None:
                    continue
                lat, lon = point
                # Five-degree cells provide a deliberately coarse footprint;
                # the published layer never exposes an individual bus location.
                cell = (math.floor((lat + 2.5) / 5), math.floor(lon / 5))
                record = team_cells.setdefault(cell, {"load": 0.0, "resources": set()})
                load = _number(row.get("load_mw")) or 0.0
                record["load"] = max(float(record["load"]), float(load))
                record["resources"].add(bus_id)
            for cell, record in team_cells.items():
                aggregate = by_cell.setdefault(cell, {"teams": set(), "load": 0.0, "resources": 0})
                aggregate["teams"].add(team_id)
                aggregate["load"] += float(record["load"])
                aggregate["resources"] += len(record["resources"])
        for (lat_cell, lon_cell), record in sorted(by_cell.items()):
            contributing = len(record["teams"])
            if contributing < MIN_AGGREGATE_CELL_TEAMS:
                continue
            aggregate_plan.append({
                "cell_id": f"cell-{lat_cell}-{lon_cell}",
                "lat": lat_cell * 5,
                "lon": lon_cell * 5 + 2.5,
                "contributing_teams": contributing,
                "requested_load_mw": round(float(record["load"]), 3),
                "resource_count": int(record["resources"]),
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "privacy_policy": "Team-level strategies are not disclosed; aggregate metrics are suppressed below three contributing teams.",
        "metrics": metrics,
        "region_utilization": sorted(region_utilization, key=lambda item: str(item["region_id"])),
        "aggregate_plan": aggregate_plan,
        "stress_periods": [],
    }


def build_results_package(
    *,
    network_path: str | Path,
    evaluation_path: str | Path,
    output_dir: str | Path,
    team_id: str,
    submissions_dir: str | Path | None = None,
) -> list[Path]:
    """Build four deterministic, browser-safe JSON artifacts."""
    network_path = Path(network_path)
    evaluation = json.loads(Path(evaluation_path).read_text(encoding="utf-8"))
    if not isinstance(evaluation, Mapping):
        raise ValueError("evaluation artifact must be a JSON object")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    score = _team_score(evaluation, team_id)
    round_source = evaluation.get("round", {})
    if not isinstance(round_source, Mapping):
        round_source = {}
    round_id = str(round_source.get("round_id", evaluation.get("run_id", "unpublished")))
    horizon = str(round_source.get("horizon", evaluation.get("scenario_version", "unknown")))
    round_metadata = {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id,
        "round_name": str(round_source.get("round_name") or evaluation.get("round_name") or "Zenodo Texas pilot round"),
        "horizon_label": horizon,
        "team_id": team_id,
        "status": "published" if score.get("team_id") == team_id else "unavailable",
    }
    submission_path = Path(submissions_dir) / f"{team_id}.csv" if submissions_dir is not None else None
    artifacts = {
        "round_metadata.json": round_metadata,
        "public_network.json": _build_network(network_path),
        "team_report.json": _build_team_report(evaluation, team_id, submission_path),
        "aggregate_grid_summary.json": _build_aggregate(
            evaluation, network_path=network_path, submissions_dir=Path(submissions_dir) if submissions_dir is not None else None
        ),
    }
    paths: list[Path] = []
    for name in sorted(artifacts):
        path = output_dir / name
        _write_json(path, artifacts[name])
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", dest="network_path", required=True, type=Path)
    parser.add_argument("--evaluation", dest="evaluation_path", required=True, type=Path)
    parser.add_argument("--team", dest="team_id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--submissions-dir", type=Path, default=None)
    args = parser.parse_args()
    build_results_package(**vars(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
