"""Deterministic orchestration for Phase 3 multi-team rounds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from .evaluator import EvaluationInputError, evaluate_week
from .io import plan_from_dict, plan_to_dict, scenario_from_dict, scenario_to_dict
from .models import EvaluationConfig, Scenario, TeamPlan


POLICY_VERSION = "phase3-canonical-v1"
SHARED_RESOURCE_POLICY = "canonical-team-connection-v1"
APPROVED_EVALUATOR_VERSIONS = frozenset({"0.3.0"})


@dataclass(frozen=True)
class CanonicalSubmission:
    """A locked submission after schema normalization and stable ordering."""

    team_id: str
    raw_payload: Mapping[str, object]
    canonical_payload: Mapping[str, object] | None
    plan: TeamPlan | None
    validation_errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.plan is not None and not self.validation_errors


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if hasattr(value, "value") and type(value).__module__ == "enum":
        return value.value
    return value


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(_json_value(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _batch_hash(batch: Mapping[str, object]) -> str:
    semantic = {key: value for key, value in batch.items() if key not in {"canonical_json", "canonical_hash"}}
    return hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()


def _submission_payload(item: Mapping[str, object]) -> Mapping[str, object]:
    payload = item.get("payload")
    if isinstance(payload, Mapping):
        return payload
    return item


def _team_id(payload: Mapping[str, object]) -> str:
    value = payload.get("team_id", "<missing-team-id>")
    return str(value)


def _normalize_payload(payload: Mapping[str, object]) -> tuple[Mapping[str, object] | None, TeamPlan | None, tuple[str, ...]]:
    try:
        plan = plan_from_dict(payload)
        data = dict(plan_to_dict(plan))
        connections = sorted(data["connections"], key=lambda item: str(item["connection_id"]))
        generators = sorted(data["generators"], key=lambda item: str(item["generator_id"]))
        data["connections"] = connections
        data["generators"] = generators
        plan = plan_from_dict(data)
        return data, plan, ()
    except (TypeError, ValueError, KeyError) as error:
        return None, None, (str(error),)


def canonicalize_submissions(submissions: Iterable[Mapping[str, object]]) -> tuple[CanonicalSubmission, ...]:
    """Normalize locked submissions and enforce exactly one per team."""
    canonical: list[CanonicalSubmission] = []
    seen: set[str] = set()
    for submitted in submissions:
        if not isinstance(submitted, Mapping):
            raise ValueError("locked submission must be an object")
        payload = _submission_payload(submitted)
        team_id = _team_id(payload)
        if team_id in seen:
            raise ValueError(f"one locked submission per team required: {team_id}")
        seen.add(team_id)
        normalized, plan, errors = _normalize_payload(payload)
        canonical.append(CanonicalSubmission(team_id, dict(payload), normalized, plan, errors))
    return tuple(sorted(canonical, key=lambda item: item.team_id))


def _config_payload(config: EvaluationConfig | Mapping[str, object] | None) -> object:
    if isinstance(config, EvaluationConfig):
        return asdict(config)
    if isinstance(config, Mapping):
        return dict(config)
    return None


def build_batch_input(
    scenario: Scenario,
    submissions: Iterable[Mapping[str, object]],
    *,
    config: EvaluationConfig | Mapping[str, object] | None = None,
    policy_version: str = POLICY_VERSION,
    seed: int | None = None,
    tie_break_mode: str = "default",
) -> dict[str, object]:
    """Build the immutable, JSON-compatible semantic input for a round."""
    if scenario.evaluator_version not in APPROVED_EVALUATOR_VERSIONS:
        raise ValueError(f"evaluator_version is not approved: {scenario.evaluator_version}")
    ordered = canonicalize_submissions(submissions)
    records = []
    for item in ordered:
        payload = item.canonical_payload if item.canonical_payload is not None else dict(item.raw_payload)
        records.append(
            {
                "team_id": item.team_id,
                "payload": payload,
                "connection_ids": sorted(
                    [str(connection["connection_id"]) for connection in payload.get("connections", [])]
                ) if isinstance(payload.get("connections", []), list) else [],
                "validation": {"valid": item.valid, "errors": list(item.validation_errors)},
            }
        )
    batch: dict[str, object] = {
        "scenario": scenario_to_dict(scenario),
        "evaluator_version": scenario.evaluator_version,
        "policy_version": policy_version,
        "shared_resource_policy": SHARED_RESOURCE_POLICY,
        "tie_break_mode": tie_break_mode,
        "seed": seed,
        "configuration": _config_payload(config),
        "submissions": records,
    }
    canonical_json = _canonical_json(batch)
    batch["canonical_json"] = canonical_json
    batch["canonical_hash"] = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return batch


def _result_total(result: Mapping[str, object]) -> float:
    breakdown = result["score_breakdown"]
    assert isinstance(breakdown, Mapping)
    total = breakdown["total"]
    assert isinstance(total, (int, float)) and not isinstance(total, bool)
    return float(total)


def _numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _series_close(actual: object, expected: list[float], tolerance: float = 1e-9) -> bool:
    return isinstance(actual, (list, tuple)) and len(actual) == len(expected) and all(
        _numeric(value) and math.isclose(float(value), expected[index], rel_tol=tolerance, abs_tol=tolerance)
        for index, value in enumerate(actual)
    )


def _series(value: object, length: int, *, name: str) -> str | None:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return f"evaluator team_results {name} must have length {length}"
    if not all(_numeric(item) for item in value):
        return f"evaluator team_results {name} contains a non-numeric value"
    return None


def _validate_score(score: object, *, name: str) -> str | None:
    required = {"it_value", "energy_cost", "generator_cost", "flexibility_fee", "curtailment_cost", "unserved_penalty", "total"}
    if not isinstance(score, Mapping) or not required.issubset(score) or not all(_numeric(score[field]) for field in required):
        return f"evaluator team_results {name} is missing an authoritative score"
    expected_total = float(score["it_value"]) - float(score["energy_cost"]) - float(score["generator_cost"]) - float(score["flexibility_fee"]) - float(score["curtailment_cost"]) - float(score["unserved_penalty"])
    if not math.isclose(float(score["total"]), expected_total, rel_tol=1e-9, abs_tol=1e-9):
        return f"evaluator team_results {name} total does not match score decomposition"
    return None


def _validate_recourse(recourse: object, horizon: int, time_step_hours: float, *, name: str, require_sites: bool = False, require_feasible: bool = False) -> str | None:
    if not isinstance(recourse, Mapping):
        return f"evaluator team_results {name} must be a mapping"
    for field in ("curtailed_mw", "served_mw", "residual_unserved_mw"):
        error = _series(recourse.get(field), horizon, name=f"{name}.{field}")
        if error:
            return error
        if any(float(value) < 0.0 for value in recourse[field]):
            return f"evaluator team_results {name}.{field} contains a negative physical quantity"
    if not _numeric(recourse.get("total_curtailed_mwh")) or not _numeric(recourse.get("total_unserved_mwh")):
        return f"evaluator team_results {name} has invalid totals"
    if float(recourse["total_curtailed_mwh"]) < 0.0 or float(recourse["total_unserved_mwh"]) < 0.0:
        return f"evaluator team_results {name} has negative totals"
    if not math.isclose(float(recourse["total_curtailed_mwh"]), math.fsum(float(value) for value in recourse["curtailed_mw"]) * time_step_hours, rel_tol=1e-9, abs_tol=1e-9) or not math.isclose(float(recourse["total_unserved_mwh"]), math.fsum(float(value) for value in recourse["residual_unserved_mw"]) * time_step_hours, rel_tol=1e-9, abs_tol=1e-9):
        return f"evaluator team_results {name} totals do not match time series"
    if require_feasible and not isinstance(recourse.get("feasible"), bool):
        return f"evaluator team_results {name} has invalid feasible flag"
    if require_sites:
        sites = recourse.get("site_results")
        if not isinstance(sites, (list, tuple)) or not all(isinstance(site, Mapping) for site in sites):
            return f"evaluator team_results {name} has invalid nested site results"
        site_ids = [site.get("connection_id") for site in sites]
        if len(site_ids) != len(set(site_ids)) or not all(isinstance(site_id, str) for site_id in site_ids):
            return f"evaluator team_results {name} has duplicate or invalid site IDs"
        for site in sites:
            if not isinstance(site.get("connection_id"), str):
                return f"evaluator team_results {name} has invalid site identity"
            site_error = _validate_recourse(site, horizon, time_step_hours, name=f"{name}.site_results[{site['connection_id']}]" )
            if site_error:
                return site_error
    times = recourse.get("intervention_times")
    if not isinstance(times, (list, tuple)) or not all(isinstance(time, int) and not isinstance(time, bool) for time in times):
        return f"evaluator team_results {name}.intervention_times is invalid"
    if list(times) != sorted(set(times)) or any(time < 0 or time >= horizon for time in times):
        return f"evaluator team_results {name}.intervention_times is out of bounds"
    return None


def _validate_allocation(allocation: object, horizon: int, *, name: str, require_curtailment: bool = True) -> str | None:
    if not isinstance(allocation, Mapping):
        return f"evaluator team_results {name} must be a mapping"
    if not _numeric(allocation.get("allocated_capacity_mw")):
        return f"evaluator team_results {name}.allocated_capacity_mw is invalid"
    ratios = allocation.get("resource_ratio_by_time")
    error = _series(ratios, horizon, name=f"{name}.resource_ratio_by_time")
    if error:
        return error
    if any(float(ratio) < 0.0 or float(ratio) > 1.0 for ratio in ratios):
        return f"evaluator team_results {name}.resource_ratio_by_time is out of bounds"
    if require_curtailment:
        error = _series(allocation.get("curtailed_mw_by_time"), horizon, name=f"{name}.curtailed_mw_by_time")
        if error:
            return error
    binding = allocation.get("binding_resources")
    if not isinstance(binding, (list, tuple)) or not all(isinstance(resource, str) for resource in binding):
        return f"evaluator team_results {name}.binding_resources is invalid"
    return None


def _validate_dispatch(dispatch: object, horizon: int, time_step_hours: float, expected_generator_ids: set[str], expected_generator_connections: Mapping[str, str], *, name: str) -> str | None:
    if not isinstance(dispatch, (list, tuple)):
        return f"evaluator team_results {name} must be a sequence"
    seen: set[str] = set()
    for item in dispatch:
        if not isinstance(item, Mapping):
            return f"evaluator team_results {name} contains a non-mapping entry"
        required = ("generator_id", "connection_id", "capacity_mw", "marginal_cost_per_mwh", "dispatch_mw", "total_mwh")
        if any(field not in item for field in required):
            return f"evaluator team_results {name} is missing generator fields"
        generator_id = item["generator_id"]
        if not isinstance(generator_id, str) or generator_id in seen or generator_id not in expected_generator_ids:
            return f"evaluator team_results {name} has an unexpected generator"
        if item["connection_id"] != expected_generator_connections[generator_id]:
            return f"evaluator team_results {name} generator has an unexpected owning connection"
        seen.add(generator_id)
        if not _numeric(item["capacity_mw"]) or not _numeric(item["marginal_cost_per_mwh"]) or not _numeric(item["total_mwh"]):
            return f"evaluator team_results {name} has invalid generator values"
        error = _series(item["dispatch_mw"], horizon, name=f"{name}.dispatch_mw")
        if error:
            return error
        if any(float(value) < 0.0 or float(value) > float(item["capacity_mw"]) for value in item["dispatch_mw"]):
            return f"evaluator team_results {name} dispatch is outside generator bounds"
        if not math.isclose(float(item["total_mwh"]), math.fsum(float(value) for value in item["dispatch_mw"]) * time_step_hours, rel_tol=1e-9, abs_tol=1e-9):
            return f"evaluator team_results {name} dispatch total does not match time series"
    if seen != expected_generator_ids:
        return f"evaluator team_results {name} does not match submitted generators"
    return None


def _validate_connection_result(connection: object, horizon: int, time_step_hours: float, expected: Mapping[str, object], expected_generator_ids: set[str], expected_generator_connections: Mapping[str, str], *, name: str) -> str | None:
    if not isinstance(connection, Mapping):
        return f"evaluator team_results {name} must be a mapping"
    for field in ("connection_id", "bus_id", "path_corridors", "allocation", "recourse", "diagnostics", "generator_dispatch", "score_breakdown"):
        if field not in connection:
            return f"evaluator team_results {name} is missing {field}"
    if connection["connection_id"] != expected["connection_id"] or connection["bus_id"] != expected["bus_id"]:
        return f"evaluator team_results {name} has unexpected connection identity"
    if not isinstance(connection["path_corridors"], (list, tuple)) or list(connection["path_corridors"]) != list(expected["path_corridors"]):
        return f"evaluator team_results {name}.path_corridors is invalid"
    error = _validate_allocation(connection["allocation"], horizon, name=f"{name}.allocation")
    if error:
        return error
    error = _validate_dispatch(connection["generator_dispatch"], horizon, time_step_hours, expected_generator_ids, expected_generator_connections, name=f"{name}.generator_dispatch")
    if error:
        return error
    error = _validate_recourse(connection["recourse"], horizon, time_step_hours, name=f"{name}.recourse")
    if error:
        return error
    if connection["recourse"].get("connection_id") != expected["connection_id"]:
        return f"evaluator team_results {name}.recourse has unexpected connection identity"
    error = _validate_score(connection["score_breakdown"], name=f"{name}.score_breakdown")
    if error:
        return error
    diagnostics = connection["diagnostics"]
    if not isinstance(diagnostics, Mapping):
        return f"evaluator team_results {name}.diagnostics must be a mapping"
    for field in ("requested_load_mw", "network_available_capacity_mw", "effective_available_capacity_mw", "grid_supply_mw", "balance_error_mw"):
        error = _series(diagnostics.get(field), horizon, name=f"{name}.diagnostics.{field}")
        if error:
            return error
    return None


def _validate_evaluator_entry(entry: object, scenario: Scenario, plan: TeamPlan) -> str | None:
    if not isinstance(entry, Mapping):
        return "evaluator team_results entry is not a mapping"
    if not isinstance(entry.get("team_id"), str):
        return "evaluator team_results entry has invalid team_id"
    required = {"score_breakdown", "recourse", "allocation", "diagnostics", "generator_dispatch", "generator_dispatch_results", "connection_results", "site_results"}
    missing = sorted(field for field in required if field not in entry)
    if missing:
        return f"evaluator team_results entry missing fields: {', '.join(missing)}"
    horizon = len(scenario.energy_price_per_mwh)
    error = _validate_score(entry["score_breakdown"], name="score_breakdown")
    if error:
        return error
    error = _validate_recourse(entry["recourse"], horizon, scenario.time_step_hours, name="recourse", require_sites=True, require_feasible=True)
    if error:
        return error
    error = _validate_allocation(entry["allocation"], horizon, name="allocation", require_curtailment=False)
    if error:
        return error
    if not isinstance(entry["diagnostics"], Mapping):
        return "evaluator team_results diagnostics must be a mapping"
    for field in ("requested_load_mw", "network_available_capacity_mw", "effective_available_capacity_mw", "grid_supply_mw", "balance_error_mw"):
        error = _series(entry["diagnostics"].get(field), horizon, name=f"diagnostics.{field}")
        if error:
            return error
    diagnostics = entry["diagnostics"]
    if not isinstance(diagnostics.get("feasible"), bool):
        return "evaluator team_results diagnostics.feasible is invalid"
    for field in ("binding_site_ids", "curtailed_site_ids"):
        if not isinstance(diagnostics.get(field), (list, tuple)) or not all(isinstance(value, str) for value in diagnostics[field]):
            return f"evaluator team_results diagnostics.{field} is invalid"
    if not isinstance(diagnostics.get("site_binding_diagnostics"), (list, tuple)) or not all(isinstance(value, Mapping) for value in diagnostics["site_binding_diagnostics"]):
        return "evaluator team_results diagnostics.site_binding_diagnostics is invalid"
    expected_connections = {connection.connection_id: plan_to_dict(TeamPlan(plan.team_id, connections=(connection,), generators=tuple(generator for generator in plan.generators if generator.connection_id == connection.connection_id), intervention_budget_k=plan.intervention_budget_k, curtailment_depth_mu=plan.curtailment_depth_mu, flexibility_fee_per_mwh=plan.flexibility_fee_per_mwh))["connections"][0] for connection in plan.connections}
    expected_generators_by_connection = {
        connection_id: {generator.generator_id for generator in plan.generators if generator.connection_id == connection_id}
        for connection_id in expected_connections
    }
    expected_generator_connections = {generator.generator_id: generator.connection_id for generator in plan.generators}
    bus_limits = {bus.bus_id: bus.headroom_mw_by_time for bus in scenario.buses}
    corridor_limits = {corridor.corridor_id: corridor.capacity_mw_by_time for corridor in scenario.corridors}
    connection_results = entry["connection_results"]
    connection_ids = [item.get("connection_id") if isinstance(item, Mapping) else None for item in connection_results] if isinstance(connection_results, (list, tuple)) else []
    if not isinstance(connection_results, (list, tuple)) or len(connection_ids) != len(expected_connections) or len(connection_ids) != len(set(connection_ids)) or set(connection_ids) != set(expected_connections):
        return "evaluator team_results connection_results do not match submitted connections"
    for connection in connection_results:
        error = _validate_connection_result(connection, horizon, scenario.time_step_hours, expected_connections[connection["connection_id"]], expected_generators_by_connection[connection["connection_id"]], expected_generator_connections, name=f"connection_results[{connection['connection_id']}]")
        if error:
            return error
        connection_spec = expected_connections[connection["connection_id"]]
        allocation = connection["allocation"]
        diagnostics = connection["diagnostics"]
        requested = diagnostics["requested_load_mw"]
        network = diagnostics["network_available_capacity_mw"]
        ratio = allocation["resource_ratio_by_time"]
        expected_requested = [connection_spec["capacity_mw"] * value for value in connection_spec["profile"]]
        expected_network = [
            expected_requested[index] * ratio[index]
            for index in range(horizon)
        ]
        if not _series_close(requested, expected_requested) or not _series_close(network, expected_network):
            return f"evaluator team_results {connection['connection_id']} violates allocation semantics"
        if not _series_close(allocation["curtailed_mw_by_time"], [requested[index] - network[index] for index in range(horizon)]):
            return f"evaluator team_results {connection['connection_id']} violates allocation conservation"
        for index in range(horizon):
            if network[index] > bus_limits[connection["bus_id"]][index] + 1e-9 or any(network[index] > corridor_limits[corridor][index] + 1e-9 for corridor in connection["path_corridors"]):
                return f"evaluator team_results {connection['connection_id']} exceeds a resource limit"
            recourse = connection["recourse"]
            dispatch_by_time = [sum(item["dispatch_mw"][index] for item in connection["generator_dispatch"]) for index in range(horizon)]
            if not _series_close(diagnostics["effective_available_capacity_mw"], [network[time] + dispatch_by_time[time] for time in range(horizon)]):
                return f"evaluator team_results {connection['connection_id']} effective capacity is inconsistent"
            if not _series_close(diagnostics["grid_supply_mw"], [recourse["served_mw"][time] - dispatch_by_time[time] for time in range(horizon)]):
                return f"evaluator team_results {connection['connection_id']} grid supply is inconsistent"
            if not _series_close(diagnostics["balance_error_mw"], [requested[time] - recourse["served_mw"][time] - recourse["curtailed_mw"][time] - recourse["residual_unserved_mw"][time] for time in range(horizon)]):
                return f"evaluator team_results {connection['connection_id']} balance is inconsistent"
            if not math.isclose(recourse["served_mw"][index] + recourse["curtailed_mw"][index] + recourse["residual_unserved_mw"][index], requested[index], rel_tol=1e-9, abs_tol=1e-9):
                return f"evaluator team_results {connection['connection_id']} violates recourse conservation"
    site_results = entry["site_results"]
    site_ids = [site.get("connection_id") for site in site_results] if isinstance(site_results, (list, tuple)) and all(isinstance(site, Mapping) for site in site_results) else []
    if not isinstance(site_results, (list, tuple)) or len(site_results) != len(connection_results) or len(site_ids) != len(set(site_ids)) or set(site_ids) != set(expected_connections):
        return "evaluator team_results site_results has the wrong shape"
    for site in site_results:
        if not isinstance(site, Mapping) or site.get("connection_id") not in expected_connections:
            return "evaluator team_results site_results has unexpected connection"
        error = _validate_connection_result(site, horizon, scenario.time_step_hours, expected_connections[site["connection_id"]], expected_generators_by_connection[site["connection_id"]], expected_generator_connections, name=f"site_results[{site['connection_id']}]")
        if error:
            return error
    connection_by_id = {connection["connection_id"]: connection for connection in connection_results}
    site_by_id = {site["connection_id"]: site for site in entry["recourse"]["site_results"]}
    if set(site_by_id) != set(connection_by_id):
        return "evaluator team_results recourse site results do not match connections"
    for connection_id, connection in connection_by_id.items():
        site = site_by_id[connection_id]
        if list(site["intervention_times"]) != list(connection["recourse"]["intervention_times"]):
            return "evaluator team_results intervention times disagree across levels"
    union_times = sorted({time for site in site_by_id.values() for time in site["intervention_times"]})
    if union_times != list(entry["recourse"]["intervention_times"]):
        return "evaluator team_results top-level intervention times disagree with sites"
    top_site_times = {site["connection_id"]: list(site["recourse"]["intervention_times"]) for site in entry["site_results"]}
    if top_site_times != {connection_id: list(connection["recourse"]["intervention_times"]) for connection_id, connection in connection_by_id.items()}:
        return "evaluator team_results site and connection intervention times disagree"
    top_times = entry["recourse"]["intervention_times"]
    if len(top_times) > plan.intervention_budget_k:
        return "evaluator team_results recourse exceeds intervention budget"
    for connection in connection_results:
        if len(connection["recourse"]["intervention_times"]) > plan.intervention_budget_k:
            return "evaluator team_results connection recourse exceeds intervention budget"
    for site in site_by_id.values():
        if len(site["intervention_times"]) > plan.intervention_budget_k:
            return "evaluator team_results site recourse exceeds intervention budget"
    for index in range(horizon):
        for bus_id, limits in bus_limits.items():
            used = sum(connection["diagnostics"]["network_available_capacity_mw"][index] for connection in connection_results if connection["bus_id"] == bus_id)
            if used > limits[index] + 1e-9:
                return f"evaluator team_results bus {bus_id} exceeds capacity at timestep {index}"
        for corridor_id, limits in corridor_limits.items():
            used = sum(connection["diagnostics"]["network_available_capacity_mw"][index] for connection in connection_results if corridor_id in connection["path_corridors"])
            if used > limits[index] + 1e-9:
                return f"evaluator team_results corridor {corridor_id} exceeds capacity at timestep {index}"
        for field in ("requested_load_mw", "network_available_capacity_mw", "effective_available_capacity_mw", "grid_supply_mw"):
            expected_total = sum(connection["diagnostics"][field][index] for connection in connection_results)
            if not math.isclose(entry["diagnostics"][field][index], expected_total, rel_tol=1e-9, abs_tol=1e-9):
                return f"evaluator team_results diagnostics.{field} is not conserved"
        for field in ("served_mw", "curtailed_mw", "residual_unserved_mw"):
            expected_total = sum(connection["recourse"][field][index] for connection in connection_results)
            if not math.isclose(entry["recourse"][field][index], expected_total, rel_tol=1e-9, abs_tol=1e-9):
                return f"evaluator team_results recourse.{field} is not conserved"
    if not math.isclose(entry["allocation"]["allocated_capacity_mw"], sum(connection["allocation"]["allocated_capacity_mw"] for connection in connection_results), rel_tol=1e-9, abs_tol=1e-9):
        return "evaluator team_results allocation is not conserved"
    for field in ("total_curtailed_mwh", "total_unserved_mwh"):
        expected_total = sum(connection["recourse"][field] for connection in connection_results)
        if not math.isclose(entry["recourse"][field], expected_total, rel_tol=1e-9, abs_tol=1e-9):
            return f"evaluator team_results recourse.{field} is not conserved"
    expected_generators = {generator.generator_id for generator in plan.generators}
    error = _validate_dispatch(entry["generator_dispatch_results"], horizon, scenario.time_step_hours, expected_generators, expected_generator_connections, name="generator_dispatch_results")
    if error:
        return error
    generator_dispatch = entry["generator_dispatch"]
    dispatch_error = None if not isinstance(generator_dispatch, Mapping) else _series(generator_dispatch.get("dispatch_mw"), horizon, name="generator_dispatch.dispatch_mw")
    if dispatch_error or not isinstance(generator_dispatch, Mapping) or not _numeric(generator_dispatch.get("total_mwh")) or (generator_dispatch.get("generator_id") is not None and generator_dispatch.get("generator_id") not in expected_generators):
        return "evaluator team_results generator_dispatch has the wrong shape"
    if any(float(value) < 0.0 for value in generator_dispatch["dispatch_mw"]):
        return "evaluator team_results generator_dispatch has negative dispatch"
    if not math.isclose(float(generator_dispatch["total_mwh"]), math.fsum(float(value) for value in generator_dispatch["dispatch_mw"]) * scenario.time_step_hours, rel_tol=1e-9, abs_tol=1e-9):
        return "evaluator team_results generator_dispatch total is inconsistent"
    expected_dispatch = [sum(item["dispatch_mw"][index] for item in entry["generator_dispatch_results"]) for index in range(horizon)]
    if not _series_close(generator_dispatch["dispatch_mw"], expected_dispatch):
        return "evaluator team_results generator dispatch is not conserved"
    return None


def _validate_batch_resource_conservation(evaluator_results: tuple[object, ...], scenario: Scenario) -> str | None:
    connections = [
        connection
        for entry in evaluator_results
        if isinstance(entry, Mapping)
        for connection in entry.get("connection_results", ())
        if isinstance(connection, Mapping)
    ]
    for bus in scenario.buses:
        for index, limit in enumerate(bus.headroom_mw_by_time):
            used = sum(connection["diagnostics"]["network_available_capacity_mw"][index] for connection in connections if connection["bus_id"] == bus.bus_id)
            if used > limit + 1e-9:
                return f"evaluator batch exceeds bus capacity: {bus.bus_id} at timestep {index}"
    for corridor in scenario.corridors:
        for index, limit in enumerate(corridor.capacity_mw_by_time):
            used = sum(connection["diagnostics"]["network_available_capacity_mw"][index] for connection in connections if corridor.corridor_id in connection["path_corridors"])
            if used > limit + 1e-9:
                return f"evaluator batch exceeds corridor capacity: {corridor.corridor_id} at timestep {index}"
    return None


def _validation_result(item: CanonicalSubmission) -> dict[str, object]:
    return {"valid": item.valid, "errors": list(item.validation_errors)}


def _serialize_result(result: object) -> object:
    return _json_value(result)


def _isolated_valid_submissions(scenario: Scenario, config: EvaluationConfig | Mapping[str, object] | None, items: tuple[CanonicalSubmission, ...]) -> tuple[CanonicalSubmission, ...]:
    valid: list[CanonicalSubmission] = []
    for item in items:
        if not item.valid:
            continue
        try:
            evaluate_week(scenario, config, (item.plan,))  # type: ignore[arg-type]
        except EvaluationInputError as error:
            valid.append(CanonicalSubmission(item.team_id, item.raw_payload, item.canonical_payload, None, error.errors))
        else:
            valid.append(item)
    return tuple(valid)


def rank_team_results(
    team_results: Iterable[Mapping[str, object]],
    *,
    tie_break_mode: str = "default",
    seed: int | None = None,
) -> tuple[dict[str, object], ...]:
    """Rank by authoritative revenue; default ties receive equal ranks."""
    if tie_break_mode not in {"default", "seeded"}:
        raise ValueError(f"invalid tie_break_mode: {tie_break_mode}")
    rows = [dict(item) for item in team_results]
    if tie_break_mode == "seeded":
        if seed is None:
            raise ValueError("seeded tie-breaking requires a seed")
        rows.sort(key=lambda item: hashlib.sha256(f"{seed}:{item['team_id']}".encode()).hexdigest())
    else:
        rows.sort(key=lambda item: str(item["team_id"]))
    rows.sort(key=lambda item: -float(item.get("official_revenue", 0.0)))
    last_score: float | None = None
    last_rank = 0
    for position, row in enumerate(rows, start=1):
        score = float(row.get("official_revenue", 0.0))
        if tie_break_mode == "seeded" or last_score is None or score != last_score:
            last_rank = position
        row["rank"] = last_rank
        row["tie_group"] = f"rank-{last_rank}"
        last_score = score
    return tuple(rows)


def evaluate_locked_round(
    scenario: Scenario,
    submissions: Iterable[Mapping[str, object]],
    *,
    config: EvaluationConfig | Mapping[str, object] | None = None,
    policy_version: str = POLICY_VERSION,
    seed: int | None = None,
    tie_break_mode: str = "default",
) -> dict[str, object]:
    """Evaluate a locked batch with invalid-plan zero scoring and no partial publication."""
    locked_submissions = tuple(submissions)
    batch = build_batch_input(
        scenario,
        locked_submissions,
        config=config,
        policy_version=policy_version,
        seed=seed,
        tie_break_mode=tie_break_mode,
    )
    ordered = canonicalize_submissions(locked_submissions)
    try:
        checked = _isolated_valid_submissions(scenario, config, ordered)
    except Exception as error:
        return {
            "status": "failed",
            "error": str(error),
            "input_hash": batch["canonical_hash"],
            "batch_input": batch,
            "ranked_results": (),
        }
    valid_items = tuple(item for item in checked if item.valid)
    invalid_items = tuple(item for item in checked if not item.valid)
    try:
        evaluation = evaluate_week(scenario, config, tuple(item.plan for item in valid_items if item.plan is not None)) if valid_items else None
    except Exception as error:
        return {
            "status": "failed",
            "error": str(error),
            "input_hash": batch["canonical_hash"],
            "batch_input": batch,
            "ranked_results": (),
        }
    expected_team_ids = {item.team_id for item in valid_items}
    evaluator_results = () if evaluation is None else evaluation.team_results
    plans_by_team = {item.team_id: item.plan for item in valid_items if item.plan is not None}
    validation_errors = [
        _validate_evaluator_entry(item, scenario, plans_by_team.get(item["team_id"]))
        if isinstance(item, Mapping) and item.get("team_id") in plans_by_team
        else "evaluator team_results entry has no matching valid submission"
        for item in evaluator_results
    ]
    if any(error is not None for error in validation_errors):
        return {
            "status": "failed",
            "error": next(error for error in validation_errors if error is not None),
            "input_hash": batch["canonical_hash"],
            "batch_input": batch,
            "ranked_results": (),
        }
    resource_error = _validate_batch_resource_conservation(tuple(evaluator_results), scenario)
    if resource_error:
        return {
            "status": "failed",
            "error": resource_error,
            "input_hash": batch["canonical_hash"],
            "batch_input": batch,
            "ranked_results": (),
        }
    returned_team_ids = [item["team_id"] for item in evaluator_results]
    if (
        len(returned_team_ids) != len(expected_team_ids)
        or returned_team_ids != sorted(expected_team_ids)
        or len(returned_team_ids) != len(set(returned_team_ids))
        or set(returned_team_ids) != expected_team_ids
        or any(not isinstance(item, Mapping) for item in evaluator_results)
    ):
        return {
            "status": "failed",
            "error": "evaluator team_results are missing or duplicate",
            "input_hash": batch["canonical_hash"],
            "batch_input": batch,
            "ranked_results": (),
        }
    evaluator_by_team = {str(item["team_id"]): _serialize_result(item) for item in evaluator_results}
    rows: list[dict[str, object]] = []
    for item in checked:
        evaluator_result = evaluator_by_team.get(item.team_id)
        rows.append(
            {
                "team_id": item.team_id,
                "official_revenue": 0.0 if not item.valid else _result_total(evaluator_result or {}),
                "validation": _validation_result(item),
                "evaluator_result": evaluator_result,
            }
        )
    ranked = rank_team_results(rows, tie_break_mode=tie_break_mode, seed=seed)
    output_payload = {"status": "complete", "ranked_results": ranked}
    output_json = _canonical_json(output_payload)
    return {
        "status": "complete",
        "batch_input": batch,
        "ranked_results": ranked,
        "input_hash": batch["canonical_hash"],
        "output_hash": hashlib.sha256(output_json.encode("utf-8")).hexdigest(),
        "metadata": {
            "scenario_id": scenario.scenario_id,
            "evaluator_version": scenario.evaluator_version,
            "policy_version": policy_version,
            "seed": seed,
            "canonical_hash": batch["canonical_hash"],
            "input_hash": batch["canonical_hash"],
            "output_hash": hashlib.sha256(output_json.encode("utf-8")).hexdigest(),
            "tie_break_mode": tie_break_mode,
            "shared_resource_policy": SHARED_RESOURCE_POLICY,
        },
    }


def build_audit_bundle(evaluation: Mapping[str, object]) -> dict[str, object]:
    """Create a self-contained JSON audit artifact."""
    batch = evaluation.get("batch_input")
    if not isinstance(batch, Mapping):
        raise ValueError("evaluation is missing batch input")
    metadata = dict(evaluation.get("metadata", {}))
    metadata["input_hash"] = evaluation.get("input_hash")
    metadata["output_hash"] = evaluation.get("output_hash")
    return {
        "format_version": "phase3-audit-v1",
        "metadata": metadata,
        "scenario": batch["scenario"],
        "batch_input": batch,
        "results": evaluation.get("ranked_results", ()),
    }


def replay_audit_bundle(bundle: Mapping[str, object]) -> dict[str, object]:
    """Verify and replay an audit bundle, rejecting tampering."""
    if bundle.get("format_version") != "phase3-audit-v1":
        raise ValueError("invalid audit format_version")
    required_bundle_keys = {"format_version", "metadata", "scenario", "batch_input", "results"}
    if not required_bundle_keys.issubset(bundle):
        raise ValueError("audit bundle is structurally incomplete")
    batch = bundle.get("batch_input")
    metadata = bundle.get("metadata")
    if not isinstance(batch, Mapping) or not isinstance(metadata, Mapping):
        raise ValueError("invalid audit bundle")
    stored_results = bundle.get("results")
    if not isinstance(stored_results, (list, tuple)) or not all(isinstance(result, Mapping) for result in stored_results):
        raise ValueError("audit results are structurally invalid")
    required_metadata = {"scenario_id", "evaluator_version", "policy_version", "seed", "tie_break_mode", "shared_resource_policy", "canonical_hash", "input_hash", "output_hash"}
    if not required_metadata.issubset(metadata):
        raise ValueError("audit metadata is structurally incomplete")
    required_batch = {"scenario", "evaluator_version", "policy_version", "shared_resource_policy", "tie_break_mode", "seed", "configuration", "submissions", "canonical_json", "canonical_hash"}
    if not required_batch.issubset(batch):
        raise ValueError("audit batch input is structurally incomplete")
    top_level_scenario = bundle.get("scenario")
    if not isinstance(top_level_scenario, Mapping) or top_level_scenario != batch.get("scenario"):
        raise ValueError("audit scenario duplication mismatch")
    canonical_json = batch.get("canonical_json")
    canonical_hash_value = batch.get("canonical_hash")
    if not isinstance(canonical_json, str) or hashlib.sha256(canonical_json.encode()).hexdigest() != canonical_hash_value:
        raise ValueError("audit input hash mismatch")
    if _batch_hash(batch) != canonical_hash_value:
        raise ValueError("audit canonical hash mismatch")
    scenario_payload = batch.get("scenario")
    if not isinstance(scenario_payload, Mapping):
        raise ValueError("audit scenario is invalid")
    if batch.get("evaluator_version") != scenario_payload.get("evaluator_version"):
        raise ValueError("audit evaluator version mismatch")
    if batch.get("shared_resource_policy") != SHARED_RESOURCE_POLICY:
        raise ValueError("audit shared-resource policy mismatch")
    if metadata.get("evaluator_version") != batch.get("evaluator_version"):
        raise ValueError("audit evaluator metadata mismatch")
    if metadata.get("scenario_id") != scenario_payload.get("scenario_id"):
        raise ValueError("audit scenario metadata mismatch")
    if scenario_payload.get("scenario_id") != batch.get("scenario", {}).get("scenario_id"):
        raise ValueError("audit scenario ID mismatch")
    if metadata.get("policy_version") != batch.get("policy_version"):
        raise ValueError("audit policy metadata mismatch")
    if metadata.get("seed") != batch.get("seed"):
        raise ValueError("audit seed metadata mismatch")
    if metadata.get("tie_break_mode") != batch.get("tie_break_mode"):
        raise ValueError("audit tie-break metadata mismatch")
    if metadata.get("shared_resource_policy") != batch.get("shared_resource_policy"):
        raise ValueError("audit shared-resource metadata mismatch")
    if metadata.get("canonical_hash") != canonical_hash_value:
        raise ValueError("audit canonical hash metadata mismatch")
    if metadata.get("input_hash") != canonical_hash_value:
        raise ValueError("audit input hash metadata mismatch")
    batch_submissions = batch.get("submissions")
    if not isinstance(batch_submissions, (list, tuple)):
        raise ValueError("audit submissions are structurally invalid")
    submissions: list[Mapping[str, object]] = []
    for record in batch_submissions:
        if not isinstance(record, Mapping) or not isinstance(record.get("payload"), Mapping) or not isinstance(record.get("team_id"), str) or not isinstance(record.get("connection_ids"), (list, tuple)) or not isinstance(record.get("validation"), Mapping):
            raise ValueError("audit submission record is structurally invalid")
        submissions.append(record["payload"])
    scenario = scenario_from_dict(scenario_payload)
    recomputed_batch = build_batch_input(
        scenario,
        submissions,
        config=batch.get("configuration"),
        policy_version=str(batch["policy_version"]),
        seed=batch.get("seed"),  # type: ignore[arg-type]
        tie_break_mode=str(batch["tie_break_mode"]),
    )
    if _json_value(recomputed_batch["submissions"]) != _json_value(batch_submissions):
        raise ValueError("audit submission records mismatch")
    if recomputed_batch["canonical_json"] != batch["canonical_json"] or recomputed_batch["canonical_hash"] != canonical_hash_value:
        raise ValueError("audit canonical input mismatch")
    replayed = evaluate_locked_round(
        scenario,
        submissions,
        config=batch.get("configuration"),
        policy_version=str(batch.get("policy_version", POLICY_VERSION)),
        seed=batch.get("seed"),  # type: ignore[arg-type]
        tie_break_mode=str(batch.get("tie_break_mode", "default")),
    )
    if replayed.get("input_hash") != metadata.get("input_hash") or replayed.get("output_hash") != metadata.get("output_hash"):
        raise ValueError("audit replay hash mismatch")
    if _json_value(replayed.get("ranked_results")) != _json_value(stored_results):
        raise ValueError("audit replay results mismatch")
    return replayed
