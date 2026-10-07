"""Pure validation helpers for evaluator domain objects."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real

from .models import Scenario, TeamPlan


def _is_finite(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _validate_coordinate_pair(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and len(value) == 2
        and all(_is_finite(coordinate) for coordinate in value)
        and -180.0 <= value[0] <= 180.0
        and -90.0 <= value[1] <= 90.0
    )


def _validate_coordinate_array(value: object, *, minimum_positions: int = 1) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        return False
    return len(value) >= minimum_positions and all(_validate_coordinate_pair(point) for point in value)


def _validate_polygon_coordinates(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and bool(value)
        and all(
            isinstance(ring, Sequence)
            and not isinstance(ring, (str, bytes))
            and len(ring) >= 4
            and _validate_coordinate_pair(ring[0])
            and ring[0] == ring[-1]
            and all(_validate_coordinate_pair(point) for point in ring)
            for ring in value
        )
    )


def _validate_bus_presentation(bus_id: str, presentation: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    has_latitude = "latitude" in presentation
    has_longitude = "longitude" in presentation
    if has_latitude != has_longitude:
        errors.append(f"bus {bus_id} presentation requires latitude and longitude together")
    if has_latitude:
        latitude = presentation["latitude"]
        if not _is_finite(latitude):
            errors.append(f"bus {bus_id} presentation latitude must be finite")
        elif not -90.0 <= latitude <= 90.0:
            errors.append(
                f"bus {bus_id} presentation latitude must be within [-90, 90]"
            )
    if has_longitude:
        longitude = presentation["longitude"]
        if not _is_finite(longitude):
            errors.append(f"bus {bus_id} presentation longitude must be finite")
        elif not -180.0 <= longitude <= 180.0:
            errors.append(
                f"bus {bus_id} presentation longitude must be within [-180, 180]"
            )
    if "coordinates" in presentation:
        coordinates = presentation["coordinates"]
        if not _validate_coordinate_pair(coordinates):
            errors.append(f"bus {bus_id} presentation coordinates must be a finite coordinate pair")
    return errors


def _validate_corridor_presentation(
    corridor_id: str, presentation: Mapping[str, object]
) -> list[str]:
    errors: list[str] = []
    if "path" in presentation:
        path = presentation["path"]
        if isinstance(path, Sequence) and not isinstance(path, (str, bytes)) and not path:
            errors.append(f"corridor {corridor_id} presentation path must not be empty")
        elif not isinstance(path, Sequence) or isinstance(path, (str, bytes)):
            errors.append(f"corridor {corridor_id} presentation path must be a sequence")
        elif any(not _validate_coordinate_pair(point) for point in path):
            if any(
                isinstance(point, Sequence)
                and not isinstance(point, (str, bytes))
                and len(point) != 2
                for point in path
            ):
                errors.append(
                    f"corridor {corridor_id} presentation path points must be coordinate pairs"
                )
            else:
                errors.append(
                    f"corridor {corridor_id} presentation path coordinates must be finite"
                )
        elif len(path) < 2:
            errors.append(
                f"corridor {corridor_id} presentation path must contain at least two coordinate positions"
            )
    geometry = presentation.get("geometry")
    if geometry is not None:
        geometry_label = f"corridor {corridor_id} presentation geometry"
        if not isinstance(geometry, Mapping):
            errors.append(f"{geometry_label} must be a mapping")
        elif geometry.get("type") != "LineString":
            errors.append(f"{geometry_label} type must be LineString")
        elif "coordinates" not in geometry:
            errors.append(f"{geometry_label} coordinates must be a coordinate array")
        elif not _validate_coordinate_array(geometry["coordinates"], minimum_positions=2):
            errors.append(
                f"{geometry_label} coordinates must be finite coordinate pairs"
            )
    return errors


def _validate_map_presentation(presentation: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    footprint = presentation.get("footprint")
    if footprint is not None:
        if isinstance(footprint, Mapping):
            if footprint.get("type") != "Polygon":
                errors.append("presentation footprint type must be Polygon")
            elif "coordinates" not in footprint:
                errors.append("presentation footprint coordinates must be a coordinate array")
            elif not _validate_polygon_coordinates(footprint["coordinates"]):
                errors.append(
                    "presentation footprint coordinates must be finite coordinate pairs"
                )
        elif not _validate_coordinate_array(footprint):
            errors.append("presentation footprint must contain finite coordinate pairs")
    locator = presentation.get("locator")
    if locator is not None:
        if not isinstance(locator, Mapping):
            errors.append("presentation locator must be a mapping")
        else:
            outline = locator.get("outline")
            if outline is not None and not _validate_coordinate_array(outline):
                errors.append("presentation locator outline must contain finite coordinate pairs")
            marker = locator.get("ercot_marker")
            if marker is not None and not _validate_coordinate_pair(marker):
                errors.append(
                    "presentation locator ercot_marker must be a finite coordinate pair"
                )
    return errors


def validate_scenario(scenario: Scenario) -> list[str]:
    """Return deterministic, human-readable scenario validation errors."""
    errors: list[str] = []
    horizon = len(scenario.energy_price_per_mwh)

    if scenario.base_load_mw_by_time:
        if len(scenario.base_load_mw_by_time) != horizon:
            errors.append(
                "base_load_mw_by_time length must match "
                f"scenario time horizon ({horizon})"
            )
        if not all(_is_finite(value) for value in scenario.base_load_mw_by_time):
            errors.append("base_load_mw_by_time values must be finite")
        if any(_is_finite(value) and value < 0.0 for value in scenario.base_load_mw_by_time):
            errors.append("base_load_mw_by_time values must be non-negative")

    for bus in scenario.buses:
        if not isinstance(bus.bus_id, str):
            errors.append("bus_id must be a string")
        if len(bus.headroom_mw_by_time) != horizon:
            errors.append(
                f"bus {bus.bus_id} headroom_mw_by_time length must match "
                f"scenario time horizon ({horizon})"
            )
    for corridor in scenario.corridors:
        if not isinstance(corridor.corridor_id, str):
            errors.append("corridor_id must be a string")
        if len(corridor.capacity_mw_by_time) != horizon:
            errors.append(
                f"corridor {corridor.corridor_id} capacity_mw_by_time length "
                f"must match scenario time horizon ({horizon})"
            )
    if len(scenario.it_value_per_mwh) != horizon:
        errors.append(
            f"it_value_per_mwh length must match scenario time horizon ({horizon})"
        )
    for bus in scenario.buses:
        if not all(_is_finite(value) for value in bus.headroom_mw_by_time):
            errors.append(f"bus {bus.bus_id} headroom_mw_by_time values must be finite")
        if any(
            _is_finite(value) and value < 0.0
            for value in bus.headroom_mw_by_time
        ):
            errors.append(
                f"bus {bus.bus_id} headroom_mw_by_time values must be non-negative"
            )
        if isinstance(bus.presentation, Mapping):
            errors.extend(_validate_bus_presentation(bus.bus_id, bus.presentation))
        else:
            errors.append(f"bus {bus.bus_id} presentation must be a mapping")
    for corridor in scenario.corridors:
        if not all(_is_finite(value) for value in corridor.capacity_mw_by_time):
            errors.append(
                f"corridor {corridor.corridor_id} capacity_mw_by_time values must be finite"
            )
        if any(
            _is_finite(value) and value < 0.0
            for value in corridor.capacity_mw_by_time
        ):
            errors.append(
                f"corridor {corridor.corridor_id} capacity_mw_by_time values must be non-negative"
            )
        if isinstance(corridor.presentation, Mapping):
            errors.extend(
                _validate_corridor_presentation(corridor.corridor_id, corridor.presentation)
            )
        else:
            errors.append(f"corridor {corridor.corridor_id} presentation must be a mapping")
    if isinstance(scenario.presentation, Mapping):
        errors.extend(_validate_map_presentation(scenario.presentation))
    else:
        errors.append("scenario presentation must be a mapping")
    if not all(_is_finite(value) for value in scenario.energy_price_per_mwh):
        errors.append("energy_price_per_mwh values must be finite")
    if not all(_is_finite(value) for value in scenario.it_value_per_mwh):
        errors.append("it_value_per_mwh values must be finite")
    if not _is_finite(scenario.time_step_hours) or scenario.time_step_hours <= 0:
        errors.append("time_step_hours must be finite and greater than 0")
    return errors


def validate_plan(plan: TeamPlan, scenario: Scenario) -> list[str]:
    """Return deterministic, human-readable plan validation errors."""
    errors: list[str] = []
    horizon = len(scenario.energy_price_per_mwh)
    bus_ids = tuple(bus.bus_id for bus in scenario.buses)
    corridor_ids = tuple(corridor.corridor_id for corridor in scenario.corridors)

    if not isinstance(plan.team_id, str):
        errors.append("team_id must be a string")
    elif not plan.team_id:
        errors.append("team_id must not be empty")

    connections = tuple(plan.connections)
    generators = tuple(plan.generators)
    if not connections:
        errors.append("connections must not be empty")

    connection_ids = [connection.connection_id for connection in connections]
    errors.extend(
        f"duplicate connection_id: {connection_id}"
        for connection_id in sorted(
            {str(connection_id) for connection_id in connection_ids if connection_ids.count(connection_id) > 1}
        )
    )
    legacy_single_site = len(connections) == 1 and connections[0].connection_id == "connection-legacy"

    for connection in sorted(connections, key=lambda item: str(item.connection_id)):
        prefix = "" if legacy_single_site else f"connection {connection.connection_id}: "
        if not isinstance(connection.connection_id, str):
            errors.append(
                f"connection {connection.connection_id}: connection_id must be a string"
            )
        elif not connection.connection_id.strip():
            errors.append(
                f"connection {connection.connection_id}: connection_id must not be empty"
            )
        duplicate_corridors = sorted(
            {
                str(corridor_id)
                for corridor_id in connection.path_corridors
                if connection.path_corridors.count(corridor_id) > 1
            }
        )
        errors.extend(
            f"duplicate corridor_id in connection {connection.connection_id}: {corridor_id}"
            for corridor_id in duplicate_corridors
        )
        if connection.bus_id not in bus_ids:
            errors.append(f"{prefix}unknown bus_id: {connection.bus_id}")
        for index, corridor_id in enumerate(connection.path_corridors):
            if not isinstance(corridor_id, str):
                errors.append(
                    f"{prefix}path_corridors[{index}] must be a string"
                )
            elif corridor_id not in corridor_ids:
                errors.append(f"{prefix}unknown corridor_id: {corridor_id}")
        if not _is_finite(connection.capacity_mw) or connection.capacity_mw < 0:
            errors.append(f"{prefix}capacity_mw must be finite and non-negative")
        if any(not _is_finite(value) or value < 0 or value > 1 for value in connection.profile):
            errors.append(f"{prefix}profile values must be finite and within [0, 1]")
        if len(connection.profile) != horizon:
            errors.append(
                f"{prefix}profile length must match scenario time horizon ({horizon})"
            )

    generator_ids = [generator.generator_id for generator in generators]
    errors.extend(
        f"duplicate generator_id: {generator_id}"
        for generator_id in sorted(
            {str(generator_id) for generator_id in generator_ids if generator_ids.count(generator_id) > 1}
        )
    )
    known_connection_ids = {
        connection_id for connection_id in connection_ids if isinstance(connection_id, str)
    }
    for generator in sorted(generators, key=lambda item: str(item.generator_id)):
        prefix = (
            "generator "
            if legacy_single_site
            else f"generator {generator.generator_id}: "
        )
        if not isinstance(generator.generator_id, str):
            errors.append(
                f"generator {generator.generator_id}: generator_id must be a string"
            )
        elif not generator.generator_id.strip():
            errors.append(
                f"generator {generator.generator_id}: generator_id must not be empty"
            )
        if not isinstance(generator.connection_id, str):
            errors.append(
                f"generator {generator.generator_id}: connection_id must be a string"
            )
        elif generator.connection_id not in known_connection_ids:
            errors.append(
                f"generator {generator.generator_id} references unknown "
                f"connection_id: {generator.connection_id}"
            )
        if not _is_finite(generator.capacity_mw) or generator.capacity_mw < 0:
            errors.append(f"{prefix}capacity_mw must be finite and non-negative")
        if not _is_finite(generator.marginal_cost_per_mwh):
            errors.append(f"{prefix}marginal_cost_per_mwh must be finite")
        elif generator.marginal_cost_per_mwh < 0:
            errors.append(f"{prefix}marginal_cost_per_mwh must be non-negative")

    if not isinstance(plan.intervention_budget_k, int) or isinstance(
        plan.intervention_budget_k, bool
    ):
        errors.append("intervention_budget_k must be an integer")
    elif plan.intervention_budget_k < 0:
        errors.append("intervention_budget_k must be non-negative")
    elif plan.intervention_budget_k > horizon:
        errors.append(
            f"intervention_budget_k must not exceed scenario time horizon ({horizon})"
        )
    if (
        not _is_finite(plan.curtailment_depth_mu)
        or plan.curtailment_depth_mu < 0
        or plan.curtailment_depth_mu > 1
    ):
        errors.append("curtailment_depth_mu must be finite and within [0, 1]")
    if not _is_finite(plan.flexibility_fee_per_mwh):
        errors.append("flexibility_fee_per_mwh must be finite")
    elif plan.flexibility_fee_per_mwh < 0:
        errors.append("flexibility_fee_per_mwh must be non-negative")
    return errors
