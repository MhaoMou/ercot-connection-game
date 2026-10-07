"""Canonical serialization and hashing for evaluator domain objects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from copy import deepcopy
from typing import Mapping, NotRequired, TypedDict, cast

from .models import Bus, ConnectionPlan, Corridor, GeneratorPlan, Scenario, TeamPlan


class BusPayload(TypedDict):
    bus_id: str
    headroom_mw_by_time: list[float]
    presentation: NotRequired[dict[str, object]]


class CorridorPayload(TypedDict):
    corridor_id: str
    capacity_mw_by_time: list[float]
    presentation: NotRequired[dict[str, object]]


class GeneratorPayload(TypedDict):
    generator_id: str
    connection_id: NotRequired[str]
    capacity_mw: float
    marginal_cost_per_mwh: float


class ConnectionPayload(TypedDict):
    connection_id: str
    bus_id: str
    path_corridors: list[str]
    capacity_mw: float
    profile: list[float]


class ScenarioPayload(TypedDict):
    scenario_id: str
    evaluator_version: str
    buses: list[BusPayload]
    corridors: list[CorridorPayload]
    energy_price_per_mwh: list[float]
    it_value_per_mwh: list[float]
    time_step_hours: float
    metadata: NotRequired[dict[str, object]]
    base_load_mw_by_time: NotRequired[list[float]]
    presentation: NotRequired[dict[str, object]]


class PlanPayload(TypedDict):
    team_id: str
    connections: list[ConnectionPayload]
    generators: list[GeneratorPayload]
    intervention_budget_k: int
    curtailment_depth_mu: float
    flexibility_fee_per_mwh: float
    bus_id: NotRequired[str]
    path_corridors: NotRequired[list[str]]
    capacity_mw: NotRequired[float]
    profile: NotRequired[list[float]]
    generator: NotRequired[GeneratorPayload | None]


class EvaluationConfigPayload(TypedDict):
    curtailment_cost_per_mwh: float
    unserved_penalty_per_mwh: float
    emergency_energy_cost_per_mwh: float


def _thaw_presentation(value: object) -> object:
    """Recursively copy frozen presentation data into plain JSON containers."""
    if isinstance(value, Mapping):
        return {key: _thaw_presentation(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_presentation(item) for item in value]
    return deepcopy(value)


def scenario_to_dict(scenario: Scenario) -> ScenarioPayload:
    """Convert a scenario to a JSON-compatible dictionary."""
    payload: ScenarioPayload = {
        "scenario_id": scenario.scenario_id,
        "evaluator_version": scenario.evaluator_version,
        "buses": [
            {
                "bus_id": bus.bus_id,
                "headroom_mw_by_time": list(bus.headroom_mw_by_time),
                **(
                    {"presentation": _thaw_presentation(bus.presentation)}
                    if bus.presentation
                    else {}
                ),
            }
            for bus in scenario.buses
        ],
        "corridors": [
            {
                "corridor_id": corridor.corridor_id,
                "capacity_mw_by_time": list(corridor.capacity_mw_by_time),
                **(
                    {"presentation": _thaw_presentation(corridor.presentation)}
                    if corridor.presentation
                    else {}
                ),
            }
            for corridor in scenario.corridors
        ],
        "energy_price_per_mwh": list(scenario.energy_price_per_mwh),
        "it_value_per_mwh": list(scenario.it_value_per_mwh),
        "time_step_hours": scenario.time_step_hours,
    }
    if scenario.metadata:
        payload["metadata"] = _thaw_presentation(scenario.metadata)
    if scenario.base_load_mw_by_time:
        payload["base_load_mw_by_time"] = list(scenario.base_load_mw_by_time)
    if scenario.presentation:
        payload["presentation"] = _thaw_presentation(scenario.presentation)
    return payload


def scenario_from_dict(payload: Mapping[str, object]) -> Scenario:
    """Build a scenario from its JSON-compatible dictionary form."""
    data = cast(ScenarioPayload, payload)
    metadata = cast(Mapping[str, object], data.get("metadata", {}))
    return Scenario(
        scenario_id=data["scenario_id"],
        evaluator_version=data["evaluator_version"],
        buses=tuple(
            Bus(
                bus_id=bus_payload["bus_id"],
                headroom_mw_by_time=tuple(bus_payload["headroom_mw_by_time"]),
                presentation=deepcopy(bus_payload.get("presentation", {})),
            )
            for bus_payload in data["buses"]
        ),
        corridors=tuple(
            Corridor(
                corridor_id=corridor_payload["corridor_id"],
                capacity_mw_by_time=tuple(
                    corridor_payload["capacity_mw_by_time"]
                ),
                presentation=deepcopy(corridor_payload.get("presentation", {})),
            )
            for corridor_payload in data["corridors"]
        ),
        energy_price_per_mwh=tuple(data["energy_price_per_mwh"]),
        it_value_per_mwh=tuple(data["it_value_per_mwh"]),
        time_step_hours=data["time_step_hours"],
        metadata=deepcopy(metadata),
        base_load_mw_by_time=tuple(data.get("base_load_mw_by_time", ())),
        presentation=deepcopy(data.get("presentation", {})),
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be a sequence")
    return value


def _connection_payload(value: object, index: int) -> ConnectionPayload:
    item = _mapping(value, f"connections[{index}]")
    if "connection_region_id" in item or "planning_interface_ids" in item:
        missing_aliases = [
            key for key in ("connection_region_id", "planning_interface_ids") if key not in item
        ]
        if missing_aliases:
            raise ValueError(
                f"connections[{index}] planning fields require {', '.join(missing_aliases)}"
            )
        item = dict(item)
        if "bus_id" in item and item["bus_id"] != item["connection_region_id"]:
            raise ValueError(f"connections[{index}] connection_region_id conflicts with bus_id")
        if "path_corridors" in item and list(item["path_corridors"]) != list(item["planning_interface_ids"]):
            raise ValueError(f"connections[{index}] planning_interface_ids conflicts with path_corridors")
        item.setdefault("bus_id", item["connection_region_id"])
        item.setdefault("path_corridors", item["planning_interface_ids"])
    required = ("connection_id", "bus_id", "path_corridors", "capacity_mw", "profile")
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"connections[{index}] is missing {', '.join(missing)}")
    return {
        "connection_id": cast(str, item["connection_id"]),
        "bus_id": cast(str, item["bus_id"]),
        "path_corridors": list(_sequence(item["path_corridors"], f"connections[{index}].path_corridors")),
        "capacity_mw": cast(float, item["capacity_mw"]),
        "profile": list(_sequence(item["profile"], f"connections[{index}].profile")),
    }


def _generator_payload(value: object, index: int, *, legacy: bool = False) -> GeneratorPayload:
    label = "generator" if legacy else f"generators[{index}]"
    item = _mapping(value, label)
    required = ("capacity_mw", "marginal_cost_per_mwh")
    if not legacy:
        required = ("generator_id", "connection_id", "capacity_mw", "marginal_cost_per_mwh")
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"{label} is missing {', '.join(missing)}")
    result: GeneratorPayload = {
        "generator_id": cast(str, item.get("generator_id", "generator-legacy")),
        "capacity_mw": cast(float, item["capacity_mw"]),
        "marginal_cost_per_mwh": cast(float, item["marginal_cost_per_mwh"]),
    }
    if not legacy:
        result["connection_id"] = cast(str, item["connection_id"])
    elif "connection_id" in item:
        result["connection_id"] = cast(str, item["connection_id"])
    return result


def _legacy_connection(payload: Mapping[str, object]) -> ConnectionPayload:
    required = ("bus_id", "path_corridors", "capacity_mw", "profile")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"legacy plan is missing {', '.join(missing)}")
    return {
        "connection_id": "connection-legacy",
        "bus_id": cast(str, payload["bus_id"]),
        "path_corridors": list(_sequence(payload["path_corridors"], "path_corridors")),
        "capacity_mw": cast(float, payload["capacity_mw"]),
        "profile": list(_sequence(payload["profile"], "profile")),
    }


def _legacy_generator(
    payload: Mapping[str, object],
    *,
    default_connection_id: str = "connection-legacy",
) -> GeneratorPayload | None:
    value = payload.get("generator")
    if value is None:
        return None
    generator = _generator_payload(value, 0, legacy=True)
    generator.setdefault("connection_id", default_connection_id)
    return generator


def _same_connection_values(
    canonical: ConnectionPayload, legacy: ConnectionPayload
) -> bool:
    return all(
        canonical[key] == legacy[key]
        for key in ("bus_id", "path_corridors", "capacity_mw", "profile")
    )


def _same_generator_values(
    canonical: GeneratorPayload, legacy: GeneratorPayload
) -> bool:
    return all(
        canonical[key] == legacy[key]
        for key in (
            "generator_id",
            "connection_id",
            "capacity_mw",
            "marginal_cost_per_mwh",
        )
    )


def normalize_plan_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Normalize canonical or legacy plan JSON into canonical arrays.

    A payload may contain both forms during migration only when their one-site
    values agree exactly.  This keeps compatibility responses round-trippable
    while rejecting ambiguous submissions.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("plan payload must be a mapping")

    planning_fields_present = any(
        "connection_region_id" in item or "planning_interface_ids" in item
        for item in payload.get("connections", ())
        if isinstance(item, Mapping)
    )
    if planning_fields_present:
        model_version = payload.get("planning_model_version")
        if not isinstance(model_version, str) or not model_version:
            raise ValueError("planning plans require planning_model_version")
        if payload.get("plan_schema_version") != "planning-plan.v1":
            raise ValueError("planning plans require plan_schema_version=planning-plan.v1")

    team_fields = (
        "team_id",
        "intervention_budget_k",
        "curtailment_depth_mu",
        "flexibility_fee_per_mwh",
    )
    missing_team_fields = [key for key in team_fields if key not in payload]
    if missing_team_fields:
        raise ValueError(f"plan is missing {', '.join(missing_team_fields)}")

    canonical_keys_present = "connections" in payload or "generators" in payload
    legacy_keys = {"bus_id", "path_corridors", "capacity_mw", "profile", "generator"}
    legacy_keys_present = bool(legacy_keys.intersection(payload))

    if canonical_keys_present:
        if "connections" not in payload or "generators" not in payload:
            raise ValueError("canonical plan requires connections and generators")
        connections = [
            _connection_payload(value, index)
            for index, value in enumerate(_sequence(payload["connections"], "connections"))
        ]
        generators = [
            _generator_payload(value, index)
            for index, value in enumerate(_sequence(payload["generators"], "generators"))
        ]
        if legacy_keys_present:
            if not legacy_keys.issubset(payload):
                raise ValueError("legacy compatibility fields must be supplied together")
            legacy_connection = _legacy_connection(payload)
            if len(connections) != 1 or not _same_connection_values(
                connections[0], legacy_connection
            ):
                raise ValueError("conflicting legacy and canonical connection values")
            legacy_generator = _legacy_generator(
                payload,
                default_connection_id=connections[0]["connection_id"],
            )
            expected_generators = [] if legacy_generator is None else [legacy_generator]
            if len(generators) != len(expected_generators) or (
                generators
                and not _same_generator_values(generators[0], expected_generators[0])
            ):
                raise ValueError("conflicting legacy and canonical generator values")
    else:
        if not legacy_keys.issubset(payload):
            raise ValueError("plan requires canonical arrays or the complete legacy shorthand")
        connections = [_legacy_connection(payload)]
        legacy_generator = _legacy_generator(payload)
        generators = [] if legacy_generator is None else [legacy_generator]

    connection_ids = [connection["connection_id"] for connection in connections]
    for generator in generators:
        if generator["connection_id"] not in connection_ids:
            raise ValueError(
                f"generator {generator['generator_id']} references unknown "
                f"connection_id: {generator['connection_id']}"
            )

    normalized: dict[str, object] = {
        "team_id": payload["team_id"],
        "connections": connections,
        "generators": generators,
        "intervention_budget_k": payload["intervention_budget_k"],
        "curtailment_depth_mu": payload["curtailment_depth_mu"],
        "flexibility_fee_per_mwh": payload["flexibility_fee_per_mwh"],
    }
    return normalized


def plan_to_dict(plan: TeamPlan) -> PlanPayload:
    """Convert a team plan to canonical JSON, with a one-site legacy view."""
    payload: PlanPayload = {
        "team_id": plan.team_id,
        "connections": [
            {
                "connection_id": connection.connection_id,
                "bus_id": connection.bus_id,
                "path_corridors": list(connection.path_corridors),
                "capacity_mw": connection.capacity_mw,
                "profile": list(connection.profile),
            }
            for connection in plan.connections
        ],
        "generators": [
            {
                "generator_id": generator.generator_id,
                "connection_id": generator.connection_id,
                "capacity_mw": generator.capacity_mw,
                "marginal_cost_per_mwh": generator.marginal_cost_per_mwh,
            }
            for generator in plan.generators
        ],
        "intervention_budget_k": plan.intervention_budget_k,
        "curtailment_depth_mu": plan.curtailment_depth_mu,
        "flexibility_fee_per_mwh": plan.flexibility_fee_per_mwh,
    }
    if len(plan.connections) == 1 and len(plan.generators) <= 1:
        connection = plan.connections[0]
        payload.update(
            {
                "bus_id": connection.bus_id,
                "path_corridors": list(connection.path_corridors),
                "capacity_mw": connection.capacity_mw,
                "profile": list(connection.profile),
                "generator": (
                    {
                        "generator_id": plan.generators[0].generator_id,
                        "capacity_mw": plan.generators[0].capacity_mw,
                        "marginal_cost_per_mwh": plan.generators[0].marginal_cost_per_mwh,
                    }
                    if plan.generators
                    else None
                ),
            }
        )
    return payload


def plan_from_dict(payload: Mapping[str, object]) -> TeamPlan:
    """Build a team plan from its JSON-compatible dictionary form."""
    data = cast(PlanPayload, normalize_plan_payload(payload))
    return TeamPlan(
        team_id=data["team_id"],
        connections=tuple(
            ConnectionPlan(
                connection_id=connection["connection_id"],
                bus_id=connection["bus_id"],
                path_corridors=tuple(connection["path_corridors"]),
                capacity_mw=connection["capacity_mw"],
                profile=tuple(connection["profile"]),
            )
            for connection in data["connections"]
        ),
        generators=tuple(
            GeneratorPlan(
                generator_id=generator["generator_id"],
                connection_id=generator["connection_id"],
                capacity_mw=generator["capacity_mw"],
                marginal_cost_per_mwh=generator["marginal_cost_per_mwh"],
            )
            for generator in data["generators"]
        ),
        intervention_budget_k=data["intervention_budget_k"],
        curtailment_depth_mu=data["curtailment_depth_mu"],
        flexibility_fee_per_mwh=data["flexibility_fee_per_mwh"],
    )


def canonical_hash(payload: Mapping[str, object]) -> str:
    """Return the lowercase SHA-256 of a canonical JSON representation."""
    semantic_payload = _without_presentation(payload)
    encoded = json.dumps(
        semantic_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _without_presentation(value: object) -> object:
    """Remove Scenario, Bus, and Corridor presentation fields.

    Evaluator input hashes wrap the serialized scenario under a ``scenario``
    key alongside configuration and plans.  Treat that wrapper as a scenario
    boundary so its map presentation is excluded without stripping arbitrary
    ``metadata.presentation`` values elsewhere in a payload.
    """
    if isinstance(value, Mapping):
        result: dict[object, object] = {}
        for key, item in value.items():
            if key == "presentation":
                continue
            if key == "scenario":
                result[key] = _without_presentation(item)
            elif key in {"buses", "corridors"} and isinstance(item, (list, tuple)):
                result[key] = [
                    _without_resource_presentation(resource) for resource in item
                ]
            else:
                result[key] = _without_nested_presentation(item)
        return result
    return _without_nested_presentation(value)


def _without_resource_presentation(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _without_nested_presentation(item)
            for key, item in value.items()
            if key != "presentation"
        }
    return _without_nested_presentation(value)


def _without_nested_presentation(value: object) -> object:
    """Canonicalize nested values without treating arbitrary metadata as presentation."""
    if isinstance(value, Mapping):
        return {key: _without_nested_presentation(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_nested_presentation(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_without_nested_presentation(item) for item in value)
    return value
