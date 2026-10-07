"""JSON-safe response serializers for the local practice interface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from .models import EvaluationResult, Scenario


def _json_safe(value: object) -> object:
    """Return a detached tree containing only JSON-compatible containers."""
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("mapping keys must be strings")
            result[key] = _json_safe(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("JSON numbers must be finite")
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _period_index(scenario: Scenario, selected_period: int) -> int:
    horizon = len(scenario.energy_price_per_mwh)
    if isinstance(selected_period, bool) or not isinstance(selected_period, int):
        raise ValueError("selected period must be an integer")
    if selected_period < 0 or selected_period >= horizon:
        raise ValueError(f"selected period must be within [0, {horizon - 1}]")
    return selected_period


def _zone_metadata(scenario: Scenario, presentation: Mapping[str, object]) -> list[object]:
    configured = presentation.get("zone_labels")
    if configured is not None:
        safe_configured = _json_safe(configured)
        if isinstance(safe_configured, list):
            return safe_configured

    zones = sorted(
        {
            str(bus.presentation["zone"])
            for bus in scenario.buses
            if isinstance(bus.presentation, Mapping) and "zone" in bus.presentation
        }
    )
    return [{"zone": zone, "label": zone} for zone in zones]


def scenario_response(scenario: Scenario, *, selected_period: int = 0) -> dict:
    """Build the practice API scenario payload, including map and period data."""
    selected_period = _period_index(scenario, selected_period)
    presentation = _json_safe(scenario.presentation)
    if not isinstance(presentation, dict):
        presentation = {}

    buses = [
        {
            "bus_id": bus.bus_id,
            "headroom_mw_by_time": _json_safe(bus.headroom_mw_by_time),
            **(
                {"presentation": _json_safe(bus.presentation)}
                if bus.presentation
                else {}
            ),
            "selected_period_headroom_mw": bus.headroom_mw_by_time[selected_period],
        }
        for bus in scenario.buses
    ]
    corridors = [
        {
            "corridor_id": corridor.corridor_id,
            "capacity_mw_by_time": _json_safe(corridor.capacity_mw_by_time),
            **(
                {"presentation": _json_safe(corridor.presentation)}
                if corridor.presentation
                else {}
            ),
            "selected_period_capacity_mw": corridor.capacity_mw_by_time[selected_period],
        }
        for corridor in scenario.corridors
    ]

    bus_coordinates = {
        bus["bus_id"]: _json_safe(bus.get("presentation", {}))
        for bus in buses
        if bus.get("presentation")
    }
    corridor_paths = {
        corridor["corridor_id"]: _json_safe(corridor["presentation"]["path"])
        for corridor in corridors
        if isinstance(corridor.get("presentation"), Mapping)
        and "path" in corridor["presentation"]
    }

    metadata = _json_safe(scenario.metadata)
    rules: dict[str, object] = {
        "time_step_hours": _json_safe(scenario.time_step_hours)
    }
    if isinstance(metadata, Mapping) and "evaluation_config" in metadata:
        rules["evaluation_config"] = _json_safe(metadata["evaluation_config"])
    if scenario.base_load_mw_by_time:
        rules["base_load_mw_by_time"] = _json_safe(scenario.base_load_mw_by_time)

    map_payload = dict(presentation)
    zones = _zone_metadata(scenario, presentation)
    tutorial_hints = _json_safe(presentation.get("tutorial_hints", []))
    selected_period_payload = {
        "index": selected_period,
        "label": f"Period {selected_period + 1}",
        "buses": [
            {
                "bus_id": bus.bus_id,
                "headroom_mw": bus.headroom_mw_by_time[selected_period],
            }
            for bus in scenario.buses
        ],
        "corridors": [
            {
                "corridor_id": corridor.corridor_id,
                "capacity_mw": corridor.capacity_mw_by_time[selected_period],
            }
            for corridor in scenario.corridors
        ],
    }
    map_payload.update(
        {
            "footprint": _json_safe(presentation.get("footprint", [])),
            "locator": _json_safe(presentation.get("locator", {})),
            "bus_coordinates": bus_coordinates,
            "corridor_paths": corridor_paths,
            "zones": zones,
            "tutorial_hints": tutorial_hints,
            "selected_period": selected_period_payload,
        }
    )

    return {
        "scenario_id": scenario.scenario_id,
        "evaluator_version": scenario.evaluator_version,
        "planning_model": {
            "model_id": metadata.get("planning_model_id") if isinstance(metadata, Mapping) else None,
            "model_version": metadata.get("planning_model_version") if isinstance(metadata, Mapping) else None,
            "scenario_version": metadata.get("scenario_version") if isinstance(metadata, Mapping) else None,
            "plan_schema_version": metadata.get("plan_schema_version") if isinstance(metadata, Mapping) else None,
        },
        "time_horizon": len(scenario.energy_price_per_mwh),
        "buses": buses,
        "corridors": corridors,
        "planning_regions": [
            {
                "planning_region_id": bus["bus_id"],
                "label": bus.get("presentation", {}).get("label", bus["bus_id"]),
                "anchor": bus.get("presentation", {}).get("coordinates", []),
                "headroom_mw_by_time": bus["headroom_mw_by_time"],
            }
            for bus in buses
        ],
        "planning_interfaces": [
            {
                "planning_interface_id": corridor["corridor_id"],
                "from_region": corridor.get("presentation", {}).get("from_region"),
                "to_region": corridor.get("presentation", {}).get("to_region"),
                "capacity_mw_by_time": corridor["capacity_mw_by_time"],
                "path": corridor.get("presentation", {}).get("path", []),
            }
            for corridor in corridors
        ],
        "zones": zones,
        "selected_period": selected_period_payload,
        "tutorial_hints": tutorial_hints,
        "prices": {
            "energy_price_per_mwh": _json_safe(scenario.energy_price_per_mwh),
            "it_value_per_mwh": _json_safe(scenario.it_value_per_mwh),
        },
        "rules": rules,
        "metadata": metadata,
        "presentation": presentation,
        "map": map_payload,
    }


def evaluation_response(result: EvaluationResult) -> dict:
    """Build a JSON-safe canonical result envelope with legacy team fields intact."""
    aggregate = _json_safe(result.aggregate_diagnostics)
    if not isinstance(aggregate, dict):
        aggregate = {}

    team_results: list[dict[str, object]] = []
    connection_results: list[dict[str, object]] = []
    generator_dispatch: list[dict[str, object]] = []
    site_diagnostics: list[dict[str, object]] = []
    team_totals: list[dict[str, object]] = []

    safe_teams = sorted(
        (_json_safe(team) for team in result.team_results),
        key=lambda team: str(team.get("team_id", "")) if isinstance(team, dict) else "",
    )
    for safe_team in safe_teams:
        if not isinstance(safe_team, dict):
            continue
        team_id = safe_team.get("team_id")
        raw_connections = safe_team.get("connection_results", safe_team.get("site_results", []))
        connections = [item for item in raw_connections if isinstance(item, dict)] if isinstance(raw_connections, list) else []
        connections.sort(key=lambda item: str(item.get("connection_id", "")))
        raw_generators = safe_team.get("generator_dispatch_results", [])
        generators = [item for item in raw_generators if isinstance(item, dict)] if isinstance(raw_generators, list) else []
        generators.sort(
            key=lambda item: (
                item.get("marginal_cost_per_mwh", 0),
                str(item.get("generator_id", "")),
            )
        )

        safe_team["connection_results"] = connections
        # ``site_results`` and ``generator_dispatch`` are retained for the
        # Phase 2 browser and other legacy consumers.  The explicit plural
        # fields are the canonical multi-site API view.
        safe_team["site_results"] = connections
        safe_team["generator_dispatch_results"] = generators
        diagnostics: list[dict[str, object]] = []
        for connection in connections:
            diagnostics.append(
                {
                    "connection_id": connection.get("connection_id"),
                    "bus_id": connection.get("bus_id"),
                    "diagnostics": connection.get("diagnostics", {}),
                }
            )
            connection_results.append({"team_id": team_id, **connection})
        safe_team["site_diagnostics"] = diagnostics
        for generator in generators:
            generator_dispatch.append({"team_id": team_id, **generator})
        site_diagnostics.extend(
            {"team_id": team_id, **diagnostic} for diagnostic in diagnostics
        )

        score_breakdown = safe_team.get("score_breakdown", {})
        if not isinstance(score_breakdown, dict):
            score_breakdown = {}
        team_total = {
            "team_id": team_id,
            "feasible": bool(
                isinstance(safe_team.get("diagnostics"), dict)
                and safe_team["diagnostics"].get("feasible", False)
            ),
            "score_breakdown": score_breakdown,
            "total": score_breakdown.get("total"),
        }
        safe_team["team_totals"] = team_total
        team_totals.append(team_total)
        team_results.append(safe_team)

    return {
        "evaluator_version": aggregate.get("evaluator_version"),
        "scenario_id": result.scenario_id,
        "input_hash": result.input_hash,
        "team_results": team_results,
        "connection_results": connection_results,
        "generator_dispatch": generator_dispatch,
        "site_diagnostics": site_diagnostics,
        "team_totals": team_totals,
        "aggregate_diagnostics": aggregate,
    }


def error_response(
    code: str,
    message: str,
    *,
    evaluator_version: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Build a stable public error payload without exception implementation details."""
    error: dict[str, object] = {"code": code, "message": message}
    if evaluator_version is not None:
        error["evaluator_version"] = evaluator_version
    if request_id is not None:
        error["request_id"] = request_id
    return {"error": error}
