import copy
import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from ercot_game import Bus, Corridor
from ercot_game.io import canonical_hash, scenario_from_dict, scenario_to_dict
from ercot_game.validate import validate_scenario


PROJECT_ROOT = Path(__file__).parents[1]
FIXTURE = PROJECT_ROOT / "data/fixtures/ercot_small.json"


def load_fixture():
    return scenario_from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_fixture_contains_map_and_resource_presentation_metadata():
    scenario = load_fixture()

    assert scenario.presentation["footprint"]
    assert scenario.presentation["locator"]["outline"]
    assert all({"latitude", "longitude", "zone"} <= bus.presentation.keys() for bus in scenario.buses)
    assert all({"path", "geometry"} <= corridor.presentation.keys() for corridor in scenario.corridors)
    assert validate_scenario(scenario) == []


def test_teaching_fixture_has_scale_diversity_and_stable_resource_references():
    scenario = load_fixture()
    bus_ids = [bus.bus_id for bus in scenario.buses]
    corridor_ids = [corridor.corridor_id for corridor in scenario.corridors]
    bus_id_set = set(bus_ids)

    assert 24 <= len(bus_ids) <= 36
    assert 40 <= len(corridor_ids) <= 60
    assert len(bus_ids) == len(bus_id_set)
    assert len(corridor_ids) == len(set(corridor_ids))
    assert len(scenario.energy_price_per_mwh) == 6
    assert len(scenario.it_value_per_mwh) == 6
    assert len(scenario.base_load_mw_by_time) == 6
    assert any(bus.presentation["resource_class"] == "constrained" for bus in scenario.buses)
    assert any(bus.presentation["resource_class"] == "unconstrained" for bus in scenario.buses)
    assert any(corridor.presentation["resource_class"] == "constrained" for corridor in scenario.corridors)
    assert any(corridor.presentation["resource_class"] == "unconstrained" for corridor in scenario.corridors)

    for bus in scenario.buses:
        assert bus.presentation["zone"]
        assert {"latitude", "longitude", "coordinates", "label", "tutorial_hint"} <= bus.presentation.keys()
        assert bus.presentation["coordinates"] == (bus.presentation["longitude"], bus.presentation["latitude"])
        assert len(bus.headroom_mw_by_time) == 6
        assert all(value >= 0.0 for value in bus.headroom_mw_by_time)

    for corridor in scenario.corridors:
        assert corridor.presentation["from_bus_id"] in bus_id_set
        assert corridor.presentation["to_bus_id"] in bus_id_set
        assert corridor.presentation["from_bus_id"] != corridor.presentation["to_bus_id"]
        assert corridor.presentation["path"] == corridor.presentation["geometry"]["coordinates"]
        assert corridor.presentation["geometry"]["type"] == "LineString"
        assert len(corridor.presentation["path"]) >= 2
        assert len(corridor.capacity_mw_by_time) == 6
        assert all(value >= 0.0 for value in corridor.capacity_mw_by_time)


def test_fixture_map_metadata_is_educational_and_geometry_is_valid():
    scenario = load_fixture()
    footprint = scenario.presentation["footprint"]
    locator = scenario.presentation["locator"]

    assert footprint["type"] == "Polygon"
    ring = footprint["coordinates"][0]
    assert len(ring) >= 4
    assert ring[0] == ring[-1]
    assert locator["outline"][0] == locator["outline"][-1]
    assert len(locator["outline"]) >= 4
    assert len(locator["ercot_marker"]) == 2
    assert scenario.presentation["educational_use_only"] is True
    assert scenario.presentation["tutorial_hints"]
    assert "operational" in scenario.metadata["source_description"]


def test_named_panhandle_and_coast_buses_match_teaching_zone_geometry():
    scenario = load_fixture()
    buses = {bus.bus_id: bus for bus in scenario.buses}

    assert buses["bus-panhandle-01"].presentation["short_label"] == "Panhandle North"
    assert buses["bus-panhandle-01"].presentation["latitude"] > 34.0
    assert buses["bus-coast-01"].presentation["short_label"] == "Coast Houston"
    assert 27.0 < buses["bus-coast-01"].presentation["latitude"] < 31.5
    assert all(
        25.5 <= bus.presentation["latitude"] <= 36.5
        and -106.0 <= bus.presentation["longitude"] <= -93.5
        for bus in (buses["bus-panhandle-01"], buses["bus-coast-01"])
    )


def test_each_corridor_path_anchors_to_its_referenced_bus_coordinates():
    scenario = load_fixture()
    coordinates = {
        bus.bus_id: tuple(bus.presentation["coordinates"])
        for bus in scenario.buses
    }

    for corridor in scenario.corridors:
        presentation = corridor.presentation
        path = tuple(tuple(point) for point in presentation["path"])
        assert path[0] == coordinates[presentation["from_bus_id"]]
        assert path[-1] == coordinates[presentation["to_bus_id"]]


def test_presentation_metadata_round_trips_through_scenario_serialization():
    scenario = load_fixture()

    payload = scenario_to_dict(scenario)
    round_tripped = scenario_from_dict(payload)

    assert round_tripped == scenario
    assert scenario_to_dict(round_tripped) == payload
    assert isinstance(payload["presentation"], dict)
    assert isinstance(payload["presentation"]["footprint"]["coordinates"], list)


def test_mutating_serialized_nested_presentation_does_not_change_scenario():
    scenario = load_fixture()
    payload = scenario_to_dict(scenario)

    payload["presentation"]["footprint"]["coordinates"][0][0][0] = 999.0
    payload["corridors"][0]["presentation"]["geometry"]["coordinates"][0][0] = 888.0

    assert scenario.presentation["footprint"]["coordinates"][0][0][0] == -106.0
    assert scenario.corridors[0].presentation["geometry"]["coordinates"][0][0] == -101.5


def test_mutating_source_payload_after_deserialization_does_not_change_scenario():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scenario = scenario_from_dict(payload)

    payload["presentation"]["footprint"]["coordinates"][0][0][0] = 999.0
    payload["buses"][0]["presentation"]["latitude"] = 888.0

    assert scenario.presentation["footprint"]["coordinates"][0][0][0] == -106.0
    assert scenario.buses[0].presentation["latitude"] == 31.2


def test_presentation_values_are_deeply_immutable_and_alias_isolated():
    presentation = {"nested": {"coordinates": [[-101.5, 31.2]]}}
    bus = Bus("bus-test", (10.0,), presentation)
    corridor_presentation = {"path": [[-101.5, 31.2], [-99.0, 31.0]]}
    corridor = Corridor(
        "corridor-test", (20.0,), corridor_presentation
    )
    scenario = load_fixture()
    scenario_presentation = {"nested": {"coordinates": [[-99.0, 31.0]]}}
    scenario = replace(scenario, presentation=scenario_presentation)

    presentation["nested"]["coordinates"][0][0] = 999.0
    corridor_presentation["path"][0][0] = 999.0
    scenario_presentation["nested"]["coordinates"][0][0] = 999.0
    assert bus.presentation["nested"]["coordinates"][0][0] == -101.5
    assert corridor.presentation["path"][0][0] == -101.5
    assert scenario.presentation["nested"]["coordinates"][0][0] == -99.0

    with pytest.raises(TypeError):
        bus.presentation["nested"] = {}
    with pytest.raises(TypeError):
        bus.presentation["nested"]["coordinates"][0][0] = 999.0
    with pytest.raises(TypeError):
        corridor.presentation["path"][0][0] = 999.0
    with pytest.raises(TypeError):
        scenario.presentation["nested"]["coordinates"] = ()


def test_named_bus_coordinates_use_longitude_and_latitude_bounds():
    scenario = load_fixture()
    invalid_longitude = replace(
        scenario.buses[0],
        presentation={"latitude": 31.2, "longitude": 180.1},
    )
    invalid_latitude = replace(
        scenario.buses[0],
        presentation={"latitude": -90.1, "longitude": -101.5},
    )

    assert validate_scenario(replace(scenario, buses=(invalid_longitude,) + scenario.buses[1:])) == [
        "bus bus-west-constrained presentation longitude must be within [-180, 180]"
    ]
    assert validate_scenario(replace(scenario, buses=(invalid_latitude,) + scenario.buses[1:])) == [
        "bus bus-west-constrained presentation latitude must be within [-90, 90]"
    ]


def test_changing_only_presentation_metadata_does_not_change_semantic_hash():
    scenario = load_fixture()
    original_payload = scenario_to_dict(scenario)
    changed_payload = copy.deepcopy(original_payload)
    changed_payload["presentation"]["footprint"]["coordinates"][0][0][0] += 1.0
    changed_payload["buses"][0]["presentation"]["zone"] = "Changed"
    changed_payload["corridors"][0]["presentation"]["path"][0][0] += 2.0

    assert canonical_hash(original_payload) == canonical_hash(changed_payload)


def test_changing_semantic_metadata_changes_canonical_hash():
    original_payload = scenario_to_dict(load_fixture())
    changed_payload = copy.deepcopy(original_payload)
    changed_payload["buses"][0]["headroom_mw_by_time"][0] += 1.0

    assert canonical_hash(original_payload) != canonical_hash(changed_payload)


def test_nested_metadata_presentation_changes_semantic_hash():
    original_payload = scenario_to_dict(load_fixture())
    changed_payload = copy.deepcopy(original_payload)
    changed_payload["metadata"]["presentation"] = {"meaning": "changed"}

    assert canonical_hash(original_payload) != canonical_hash(changed_payload)


def test_known_resource_presentation_fields_remain_hash_ignored():
    original_payload = scenario_to_dict(load_fixture())
    changed_payload = copy.deepcopy(original_payload)
    changed_payload["presentation"]["locator"]["ercot_marker"] = [-98.0, 30.0]
    changed_payload["buses"][0]["presentation"]["zone"] = "Changed"
    changed_payload["corridors"][0]["presentation"]["path"][0][0] = -100.0

    assert canonical_hash(original_payload) == canonical_hash(changed_payload)


@pytest.mark.parametrize(
    ("presentation_update", "expected_error"),
    [
        (
            {"locator": ["not", "a", "mapping"]},
            "presentation locator must be a mapping",
        ),
        (
            {"locator": {"ercot_marker": [math.nan, -99.0]}},
            "presentation locator ercot_marker must be a finite coordinate pair",
        ),
        (
            {"footprint": {"type": "MultiPolygon", "coordinates": []}},
            "presentation footprint type must be Polygon",
        ),
        (
            {"footprint": {"type": "Polygon"}},
            "presentation footprint coordinates must be a coordinate array",
        ),
    ],
)
def test_malformed_map_presentation_is_rejected_deterministically(
    presentation_update, expected_error
):
    scenario = load_fixture()
    presentation = dict(scenario.presentation)
    presentation.update(presentation_update)

    assert validate_scenario(replace(scenario, presentation=presentation)) == [expected_error]


@pytest.mark.parametrize(
    ("geometry", "expected_error"),
    [
        (
            {"type": "Polygon", "coordinates": [[-101.0, 31.0]]},
            "corridor corridor-west-central presentation geometry type must be LineString",
        ),
        (
            {"type": "LineString"},
            "corridor corridor-west-central presentation geometry coordinates must be a coordinate array",
        ),
    ],
)
def test_malformed_corridor_geometry_is_rejected_deterministically(
    geometry, expected_error
):
    scenario = load_fixture()
    corridor = replace(
        scenario.corridors[0],
        presentation={"path": [[-101.5, 31.2], [-99.0, 31.0]], "geometry": geometry},
    )

    assert validate_scenario(replace(scenario, corridors=(corridor,) + scenario.corridors[1:])) == [
        expected_error
    ]


@pytest.mark.parametrize(
    "coordinates",
    [
        [[-106.0, 29.0], [-93.5, 29.0]],
        [[[-106.0, 29.0], [-93.5, 29.0], [-93.5, 36.5]]],
        [[[-181.0, 29.0], [-93.5, 29.0], [-93.5, 36.5], [-181.0, 29.0]]],
        [[[-106.0, 29.0], [-93.5, 91.0], [-93.5, 36.5], [-106.0, 29.0]]],
        [[[-106.0, 29.0], [True, 29.0], [-93.5, 36.5], [-106.0, 29.0]]],
    ],
)
def test_polygon_coordinates_require_closed_rings_and_geojson_positions(coordinates):
    scenario = load_fixture()
    presentation = copy.deepcopy(scenario_to_dict(scenario)["presentation"])
    presentation["footprint"]["coordinates"] = coordinates

    errors = validate_scenario(replace(scenario, presentation=presentation))

    assert errors == ["presentation footprint coordinates must be finite coordinate pairs"]


@pytest.mark.parametrize(
    "coordinates",
    [
        [[-101.5, 31.2]],
        [[-181.0, 31.2], [-99.0, 31.0]],
        [[-101.5, 91.0], [-99.0, 31.0]],
        [[True, 31.2], [-99.0, 31.0]],
    ],
)
def test_linestring_coordinates_require_two_valid_geojson_positions(coordinates):
    scenario = load_fixture()
    corridor = replace(
        scenario.corridors[0],
        presentation={"geometry": {"type": "LineString", "coordinates": coordinates}},
    )

    errors = validate_scenario(replace(scenario, corridors=(corridor,) + scenario.corridors[1:]))

    assert errors == [
        "corridor corridor-west-central presentation geometry coordinates must be finite coordinate pairs"
    ]


def test_explicit_empty_corridor_path_is_rejected_but_omitted_path_is_legacy_valid():
    scenario = load_fixture()
    empty_path_corridor = replace(scenario.corridors[0], presentation={"path": []})

    assert validate_scenario(
        replace(scenario, corridors=(empty_path_corridor,) + scenario.corridors[1:])
    ) == ["corridor corridor-west-central presentation path must not be empty"]

    omitted_path_corridor = replace(scenario.corridors[0], presentation={})
    assert validate_scenario(
        replace(scenario, corridors=(omitted_path_corridor,) + scenario.corridors[1:])
    ) == []


def test_one_point_corridor_path_is_rejected():
    scenario = load_fixture()
    one_point_path_corridor = replace(
        scenario.corridors[0], presentation={"path": [[-101.5, 31.2]]}
    )

    assert validate_scenario(
        replace(scenario, corridors=(one_point_path_corridor,) + scenario.corridors[1:])
    ) == [
        "corridor corridor-west-central presentation path must contain at least two coordinate positions"
    ]


@pytest.mark.parametrize(
    ("scenario_object", "expected_error"),
    [
            (
                lambda: load_fixture().buses[0].__class__(
                    "bus-a",
                    (10.0,) * 6,
                    {"latitude": math.nan, "longitude": -101.0, "zone": "West"},
                ),
            "bus bus-a presentation latitude must be finite",
        ),
        (
                lambda: Corridor(
                    "corridor-1",
                    (20.0,) * 6,
                    {"path": [[-101.0, 31.0], [math.inf, 30.0]]},
                ),
            "corridor corridor-1 presentation path coordinates must be finite",
        ),
        (
                lambda: Corridor(
                    "corridor-1",
                    (20.0,) * 6,
                    {"path": [[-101.0, 31.0, 4.0]]},
                ),
            "corridor corridor-1 presentation path points must be coordinate pairs",
        ),
    ],
)
def test_malformed_presentation_metadata_is_rejected_deterministically(
    scenario_object, expected_error
):
    scenario = load_fixture()
    value = scenario_object()
    if isinstance(value, Bus):
        scenario = replace(scenario, buses=(value,) + scenario.buses[1:])
    else:
        scenario = replace(scenario, corridors=(value,) + scenario.corridors[1:])

    assert validate_scenario(scenario) == [expected_error]


@pytest.mark.parametrize(
    ("scenario_update", "expected_error"),
    [
        (
            {"presentation": {"locator": {"ercot_marker": [True, 31.0]}}},
            "presentation locator ercot_marker must be a finite coordinate pair",
        ),
        (
            {"buses": (replace(load_fixture().buses[0], presentation={"latitude": True, "longitude": -101.5}),)},
            "bus bus-west-constrained presentation latitude must be finite",
        ),
        (
            {"base_load_mw_by_time": (True,) + (12.0,) * 5},
            "base_load_mw_by_time values must be finite",
        ),
    ],
)
def test_boolean_numeric_presentation_values_are_rejected(scenario_update, expected_error):
    scenario = load_fixture()
    if "buses" in scenario_update:
        scenario = replace(scenario, buses=scenario_update["buses"] + scenario.buses[1:])
    else:
        scenario = replace(scenario, **scenario_update)

    assert expected_error in validate_scenario(scenario)
