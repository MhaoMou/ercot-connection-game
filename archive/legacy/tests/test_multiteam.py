from __future__ import annotations

import json
from pathlib import Path

import pytest

from ercot_game.cli import _load_scenario
from ercot_game.io import scenario_from_dict
import ercot_game.multiteam as multiteam
from ercot_game.multiteam import (
    APPROVED_EVALUATOR_VERSIONS,
    SHARED_RESOURCE_POLICY,
    build_audit_bundle,
    build_batch_input,
    canonicalize_submissions,
    evaluate_locked_round,
    rank_team_results,
    replay_audit_bundle,
)


FIXTURE = Path(__file__).parents[1] / "data/fixtures/phase3_round.json"
TEACHING_SCENARIO = Path(__file__).parents[1] / "data/teaching/ercot_connection_scenario_v2.json"


def load_round():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_locked_v2_round_accepts_variable_connection_profiles():
    scenario = _load_scenario(TEACHING_SCENARIO)
    result = evaluate_locked_round(
        scenario,
        [
            {
                "team_id": "team-variable-profile",
                "connections": [
                    {
                        "connection_id": "site-variable",
                        "bus_id": "SOUTH_TEXAS",
                        "path_corridors": ["CENTRAL_HIGHLANDS__SOUTH_TEXAS"],
                        "capacity_mw": 20.0,
                        "profile": [0.6, 0.7, 0.8, 0.8, 0.7, 0.6],
                    }
                ],
                "generators": [],
                "intervention_budget_k": 1,
                "curtailment_depth_mu": 0.1,
                "flexibility_fee_per_mwh": 0.0,
            }
        ],
    )

    assert result["status"] == "complete"
    assert result["ranked_results"][0]["validation"]["valid"] is True


def test_canonical_batch_is_order_invariant_and_uses_team_connection_order():
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])

    forward = build_batch_input(
        scenario,
        data["submissions"],
        policy_version=data["policy_version"],
        seed=data["seed"],
    )
    reversed_batch = build_batch_input(
        scenario,
        list(reversed(data["submissions"])),
        policy_version=data["policy_version"],
        seed=data["seed"],
    )

    assert forward["canonical_hash"] == reversed_batch["canonical_hash"]
    assert forward["canonical_json"] == reversed_batch["canonical_json"]
    assert [item["team_id"] for item in forward["submissions"]] == [
        "team-alpha",
        "team-bravo",
        "team-invalid",
    ]
    assert forward["submissions"][0]["connection_ids"] == ["connection-a", "connection-z"]


def test_locked_evaluation_zeroes_invalid_plan_but_keeps_evaluator_penalties():
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])

    result = evaluate_locked_round(
        scenario,
        data["submissions"],
        policy_version=data["policy_version"],
        seed=data["seed"],
    )
    by_team = {item["team_id"]: item for item in result["ranked_results"]}

    assert by_team["team-invalid"]["official_revenue"] == 0.0
    assert by_team["team-invalid"]["validation"]["valid"] is False
    assert by_team["team-alpha"]["official_revenue"] == pytest.approx(
        by_team["team-alpha"]["evaluator_result"]["score_breakdown"]["total"]
    )
    assert by_team["team-alpha"]["evaluator_result"]["recourse"]["total_unserved_mwh"] > 0.0
    assert result["status"] == "complete"
    assert result["input_hash"]
    assert result["output_hash"]
    assert result["batch_input"]["shared_resource_policy"] == SHARED_RESOURCE_POLICY
    assert by_team["team-bravo"]["evaluator_result"]["generator_dispatch_results"]
    assert by_team["team-alpha"]["evaluator_result"]["connection_results"]


def test_evaluate_locked_round_materializes_generator_once():
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    result = evaluate_locked_round(
        scenario,
        (submission for submission in data["submissions"]),
        policy_version=data["policy_version"],
        seed=data["seed"],
    )

    assert result["status"] == "complete"
    assert {item["team_id"] for item in result["ranked_results"]} == {
        "team-alpha", "team-bravo", "team-invalid"
    }


@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_valid_evaluator_results_fail_without_zero_fabrication(
    monkeypatch, duplicate
):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    original = multiteam.evaluate_week

    def incomplete_evaluator(scenario, config, plans):
        result = original(scenario, config, plans)
        results = list(result.team_results)
        if duplicate:
            if len(results) > 1:
                results[1] = dict(results[0])
        else:
            results = results[:1]
        from dataclasses import replace
        return replace(result, team_results=tuple(results))

    monkeypatch.setattr(multiteam, "evaluate_week", incomplete_evaluator)
    result = evaluate_locked_round(scenario, data["submissions"])

    assert result["status"] == "failed"
    assert result["error"]
    assert result["ranked_results"] == ()


@pytest.mark.parametrize("mutation", ["not_mapping", "missing_score", "missing_recourse"])
def test_malformed_or_incomplete_evaluator_entries_fail(monkeypatch, mutation):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    original = multiteam.evaluate_week

    def malformed_evaluator(scenario, config, plans):
        result = original(scenario, config, plans)
        entries = list(result.team_results)
        if len(entries) > 1:
            if mutation == "not_mapping":
                entries[0] = ["malformed"]
            elif mutation == "missing_score":
                entries[0] = {key: value for key, value in entries[0].items() if key != "score_breakdown"}
            else:
                entry = dict(entries[0])
                entry["recourse"] = {"total_unserved_mwh": 0.0}
                entries[0] = entry
        from dataclasses import replace
        return replace(result, team_results=tuple(entries))

    monkeypatch.setattr(multiteam, "evaluate_week", malformed_evaluator)
    result = evaluate_locked_round(scenario, data["submissions"])

    assert result["status"] == "failed"
    assert "evaluator team_results" in result["error"]
    assert result["ranked_results"] == ()


@pytest.mark.parametrize("mutation", ["bad_recourse_series", "bad_connection", "bad_dispatch", "bad_site"])
def test_nested_evaluator_shapes_are_strictly_validated(monkeypatch, mutation):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    original = multiteam.evaluate_week

    def malformed_evaluator(scenario, config, plans):
        result = original(scenario, config, plans)
        from dataclasses import replace
        entries = [dict(entry) for entry in result.team_results]
        entry = dict(entries[0])
        connections = [dict(connection) for connection in entry["connection_results"]]
        if mutation == "bad_recourse_series":
            recourse = dict(entry["recourse"])
            recourse["served_mw"] = [1.0]
            entry["recourse"] = recourse
        elif mutation == "bad_connection":
            connection = dict(connections[0])
            allocation = dict(connection["allocation"])
            allocation["resource_ratio_by_time"] = [1.0, "bad"]
            connection["allocation"] = allocation
            connections[0] = connection
            entry["connection_results"] = connections
        elif mutation == "bad_dispatch":
            dispatch = [dict(item) for item in entry["generator_dispatch_results"]]
            if not dispatch:
                dispatch = [{"generator_id": "bad", "connection_id": "bad", "capacity_mw": 1.0, "marginal_cost_per_mwh": 1.0, "dispatch_mw": [1.0], "total_mwh": 1.0}]
            else:
                dispatch[0]["dispatch_mw"] = [1.0]
            entry["generator_dispatch_results"] = dispatch
        else:
            recourse = dict(entry["recourse"])
            site = dict(recourse["site_results"][0])
            site.pop("served_mw", None)
            recourse["site_results"] = (site,)
            entry["recourse"] = recourse
        entries[0] = entry
        return replace(result, team_results=tuple(entries))

    monkeypatch.setattr(multiteam, "evaluate_week", malformed_evaluator)
    result = evaluate_locked_round(scenario, data["submissions"])

    assert result["status"] == "failed"
    assert "evaluator team_results" in result["error"]


def test_semantic_resource_conservation_and_allocation_are_enforced():
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    result = evaluate_locked_round(scenario, data["submissions"])
    assert result["status"] == "complete"
    assert scenario.evaluator_version in APPROVED_EVALUATOR_VERSIONS
    by_team = {item["team_id"]: item for item in result["ranked_results"] if item["validation"]["valid"]}
    for team_id, item in by_team.items():
        submission = next(item for item in data["submissions"] if item["team_id"] == team_id)
        by_connection = {connection["connection_id"]: connection for connection in item["evaluator_result"]["connection_results"]}
        for connection_spec in submission["connections"]:
            connection = by_connection[connection_spec["connection_id"]]
            ratio = connection["allocation"]["resource_ratio_by_time"]
            network = connection["diagnostics"]["network_available_capacity_mw"]
            requested = connection["diagnostics"]["requested_load_mw"]
            assert network == pytest.approx([connection_spec["capacity_mw"] * value for value in ratio])
            assert connection["allocation"]["curtailed_mw_by_time"] == pytest.approx(
                [requested[index] - network[index] for index in range(2)]
            )
            recourse = connection["recourse"]
            assert recourse["served_mw"] == pytest.approx(
                [requested[index] - recourse["curtailed_mw"][index] - recourse["residual_unserved_mw"][index] for index in range(2)]
            )
        assert item["evaluator_result"]["allocation"]["allocated_capacity_mw"] == pytest.approx(
            sum(connection["allocation"]["allocated_capacity_mw"] for connection in by_connection.values())
        )


@pytest.mark.parametrize("mutation", ["duplicate_connection_id", "swap_team_ids"])
def test_evaluator_team_and_connection_identity_is_exact(monkeypatch, mutation):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    original = multiteam.evaluate_week

    def adversarial_evaluator(scenario, config, plans):
        result = original(scenario, config, plans)
        from dataclasses import replace
        entries = [dict(entry) for entry in result.team_results]
        if mutation == "duplicate_connection_id":
            entry = dict(entries[0])
            connections = list(entry["connection_results"])
            connections[1] = connections[0]
            entry["connection_results"] = tuple(connections)
            entries[0] = entry
        else:
            first = dict(entries[0])
            second = dict(entries[1])
            first["team_id"], second["team_id"] = second["team_id"], first["team_id"]
            entries[0], entries[1] = first, second
        return replace(result, team_results=tuple(entries))

    monkeypatch.setattr(multiteam, "evaluate_week", adversarial_evaluator)
    result = evaluate_locked_round(scenario, data["submissions"])
    assert result["status"] == "failed"


def test_intervention_times_must_match_site_and_connection_levels(monkeypatch):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    original = multiteam.evaluate_week

    def adversarial_evaluator(scenario, config, plans):
        result = original(scenario, config, plans)
        from dataclasses import replace
        entries = [dict(entry) for entry in result.team_results]
        entry = dict(entries[0])
        recourse = dict(entry["recourse"])
        recourse["intervention_times"] = [0]
        entry["recourse"] = recourse
        entries[0] = entry
        return replace(result, team_results=tuple(entries))

    monkeypatch.setattr(multiteam, "evaluate_week", adversarial_evaluator)
    result = evaluate_locked_round(scenario, data["submissions"])
    assert result["status"] == "failed"


@pytest.mark.parametrize("mutation", [
    "generator_owner", "score_total", "dispatch_bounds", "dispatch_total",
    "recourse_total", "effective_capacity", "balance",
])
def test_authoritative_semantics_reject_adversarial_evaluator_output(monkeypatch, mutation):
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    original = multiteam.evaluate_week

    def adversarial_evaluator(scenario, config, plans):
        result = original(scenario, config, plans)
        from dataclasses import replace
        entries = [dict(entry) for entry in result.team_results]
        index = next(index for index, entry in enumerate(entries) if entry["team_id"] == "team-bravo")
        entry = dict(entries[index])
        if mutation == "generator_owner":
            dispatch = [dict(item) for item in entry["generator_dispatch_results"]]
            dispatch[0]["connection_id"] = "connection-a"
            entry["generator_dispatch_results"] = dispatch
        elif mutation == "score_total":
            score = dict(entry["score_breakdown"])
            score["total"] += 1.0
            entry["score_breakdown"] = score
        elif mutation in {"dispatch_bounds", "dispatch_total"}:
            dispatch = [dict(item) for item in entry["generator_dispatch_results"]]
            if mutation == "dispatch_bounds":
                dispatch[0]["dispatch_mw"] = [-1.0, 2.0]
            else:
                dispatch[0]["total_mwh"] += 1.0
            entry["generator_dispatch_results"] = dispatch
        elif mutation == "recourse_total":
            recourse = dict(entry["recourse"])
            recourse["total_curtailed_mwh"] += 1.0
            entry["recourse"] = recourse
        else:
            diagnostics = dict(entry["diagnostics"])
            if mutation == "effective_capacity":
                diagnostics["effective_available_capacity_mw"] = [value + 1.0 for value in diagnostics["effective_available_capacity_mw"]]
            else:
                diagnostics["balance_error_mw"] = [1.0, 0.0]
            entry["diagnostics"] = diagnostics
        entries[index] = entry
        return replace(result, team_results=tuple(entries))

    monkeypatch.setattr(multiteam, "evaluate_week", adversarial_evaluator)
    result = evaluate_locked_round(scenario, data["submissions"])
    assert result["status"] == "failed"
    assert result["ranked_results"] == ()


def test_arbitrary_evaluator_version_is_rejected():
    data = load_round()
    scenario = scenario_from_dict({**data["scenario"], "evaluator_version": "9.9.9"})
    with pytest.raises(ValueError, match="evaluator_version"):
        evaluate_locked_round(scenario, data["submissions"])


def test_shared_resource_allocation_is_joint_and_conserves_capacity():
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    assert data["shared_resource_policy"] == SHARED_RESOURCE_POLICY
    assert len(scenario.buses) == 2
    assert len(scenario.corridors) == 2
    assert len(scenario.energy_price_per_mwh) == 2
    result = evaluate_locked_round(scenario, data["submissions"])
    valid = [item for item in result["ranked_results"] if item["validation"]["valid"]]
    allocations = [item["evaluator_result"]["allocation"]["allocated_capacity_mw"] for item in valid]

    assert len(valid) == 2
    assert sum(allocations) <= sum(scenario.buses[0].headroom_mw_by_time) + sum(scenario.buses[1].headroom_mw_by_time)
    assert sum(allocations) <= sum(scenario.corridors[0].capacity_mw_by_time) + sum(scenario.corridors[1].capacity_mw_by_time)
    assert sum(
        connection["allocation"]["allocated_capacity_mw"]
        for item in valid
        for connection in item["evaluator_result"]["connection_results"]
    ) == pytest.approx(sum(allocations))
    connections = [
        connection
        for item in valid
        for connection in item["evaluator_result"]["connection_results"]
    ]
    for bus in scenario.buses:
        for time_index, limit in enumerate(bus.headroom_mw_by_time):
            used = sum(
                connection["diagnostics"]["network_available_capacity_mw"][time_index]
                for connection in connections if connection["bus_id"] == bus.bus_id
            )
            assert used <= limit + 1e-9
    for corridor in scenario.corridors:
        for time_index, limit in enumerate(corridor.capacity_mw_by_time):
            used = sum(
                connection["diagnostics"]["network_available_capacity_mw"][time_index]
                for connection in connections if corridor.corridor_id in connection["path_corridors"]
            )
            assert used <= limit + 1e-9
    for item in valid:
        evaluation = item["evaluator_result"]
        assert len(evaluation["allocation"]["resource_ratio_by_time"]) == 2
        assert all(0.0 <= ratio <= 1.0 for ratio in evaluation["allocation"]["resource_ratio_by_time"])
        assert len(evaluation["recourse"]["served_mw"]) == 2

    bravo = next(item for item in valid if item["team_id"] == "team-bravo")
    assert bravo["evaluator_result"]["generator_dispatch_results"][0]["dispatch_mw"] == [2.0, 2.0]
    assert bravo["evaluator_result"]["recourse"]["total_curtailed_mwh"] >= 0.0
    assert bravo["evaluator_result"]["recourse"]["intervention_times"] == [1]
    assert next(
        connection["recourse"]["intervention_times"]
        for connection in bravo["evaluator_result"]["connection_results"]
        if connection["connection_id"] == "connection-b"
    ) == [1]
    alpha = next(item for item in valid if item["team_id"] == "team-alpha")
    assert alpha["evaluator_result"]["recourse"]["intervention_times"] == []
    for item in valid:
        budget = next(
            submission["intervention_budget_k"]
            for submission in data["submissions"] if submission["team_id"] == item["team_id"]
        )
        times = item["evaluator_result"]["recourse"]["intervention_times"]
        assert len(times) <= budget
        assert times == sorted(set(times))
        assert all(isinstance(time, int) and 0 <= time < 2 for time in times)
        for connection in item["evaluator_result"]["connection_results"]:
            connection_times = connection["recourse"]["intervention_times"]
            assert len(connection_times) <= budget
            assert all(isinstance(time, int) and 0 <= time < 2 for time in connection_times)


def test_duplicate_locked_team_is_rejected():
    data = load_round()
    duplicate = list(data["submissions"]) + [data["submissions"][0]]

    with pytest.raises(ValueError, match="one locked submission"):
        canonicalize_submissions(duplicate)


def test_audit_bundle_replays_to_identical_results_and_hashes():
    data = load_round()
    scenario = scenario_from_dict(data["scenario"])
    evaluated = evaluate_locked_round(
        scenario,
        data["submissions"],
        policy_version=data["policy_version"],
        seed=data["seed"],
    )
    bundle = build_audit_bundle(evaluated)
    replayed = replay_audit_bundle(bundle)

    assert bundle["metadata"]["evaluator_version"] == "0.3.0"
    assert bundle["metadata"]["policy_version"] == data["policy_version"]
    assert bundle["metadata"]["seed"] == data["seed"]
    assert bundle["metadata"]["scenario_id"] == data["scenario"]["scenario_id"]
    assert bundle["metadata"]["shared_resource_policy"] == SHARED_RESOURCE_POLICY
    assert replayed["output_hash"] == bundle["metadata"]["output_hash"]
    assert replayed["ranked_results"] == bundle["results"]

    tampered = {**bundle, "batch_input": {**bundle["batch_input"], "seed": 18}}
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_audit_bundle(tampered)

    tamper_cases = [
        {**bundle, "scenario": {**bundle["scenario"], "scenario_id": "tampered"}},
        {**bundle, "metadata": {**bundle["metadata"], "policy_version": "other"}},
        {**bundle, "metadata": {**bundle["metadata"], "scenario_id": "other"}},
        {**bundle, "metadata": {**bundle["metadata"], "shared_resource_policy": "other"}},
        {**bundle, "results": ()},
    ]
    for tampered_bundle in tamper_cases:
        with pytest.raises(ValueError):
            replay_audit_bundle(tampered_bundle)

    malformed_structure = {**bundle, "format_version": "other"}
    with pytest.raises(ValueError, match="format_version"):
        replay_audit_bundle(malformed_structure)
    malformed_record = {**bundle, "batch_input": {**bundle["batch_input"], "submissions": [*bundle["batch_input"]["submissions"][:-1], {**bundle["batch_input"]["submissions"][-1], "team_id": "other"}]}}
    with pytest.raises(ValueError):
        replay_audit_bundle(malformed_record)


def test_default_ranking_assigns_equal_ranks_to_ties():
    ranked = rank_team_results(
        [
            {"team_id": "b", "official_revenue": 10.0},
            {"team_id": "a", "official_revenue": 10.0},
            {"team_id": "c", "official_revenue": 2.0},
        ]
    )

    assert [(item["team_id"], item["rank"]) for item in ranked] == [
        ("a", 1),
        ("b", 1),
        ("c", 3),
    ]


def test_seeded_ranking_reproducibly_breaks_ties_and_rejects_unknown_mode():
    tied = [
        {"team_id": "b", "official_revenue": 10.0},
        {"team_id": "a", "official_revenue": 10.0},
    ]
    first = rank_team_results(tied, tie_break_mode="seeded", seed=7)
    second = rank_team_results(list(reversed(tied)), tie_break_mode="seeded", seed=7)

    assert first == second
    assert [item["rank"] for item in first] == [1, 2]
    with pytest.raises(ValueError, match="tie_break_mode"):
        rank_team_results(tied, tie_break_mode="random")
