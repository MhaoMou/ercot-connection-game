"""Validation and privacy boundary for read-only results artifacts.

The browser-facing package contains one selected team's report together with
public network data and privacy-preserving aggregates.  This module keeps the
contract deliberately small and rejects sensitive evaluator inputs before a
package can be handed to the web application.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import math
from typing import Any


class ResultsArtifactError(ValueError):
    """Raised when a results package is not safe or structurally valid."""


_REQUIRED_FIELDS = (
    "schema_version",
    "round",
    "network",
    "team_report",
    "aggregate",
    "privacy_policy",
)
_FORBIDDEN_KEYS = {
    "raw_submissions",
    "all_teams",
    "joint_csv",
    "audit_bundle",
    "audit_bundles",
    "unredacted_audit",
    "unredacted_audit_bundle",
    "unredacted_audit_bundles",
}
_ID_KEYS = {"id", "bus_id", "branch_id", "team_id", "site_id", "region_id"}

# The browser contract is intentionally narrower than the evaluator's internal
# result object.  These allowlists define the only fields that may cross the
# privacy boundary.  In particular, unknown nested fields are not forwarded
# merely because they passed generic JSON validation.
_ROUND_FIELDS = {"round_id", "horizon"}
_NETWORK_FIELDS = {"buses", "branches"}
_BUS_FIELDS = {"bus_id", "lon", "lat"}
_BRANCH_FIELDS = {"branch_id", "from_bus", "to_bus", "capacity_mw"}
_TEAM_REPORT_FIELDS = {"team_id", "score", "sites"}
_SITE_FIELDS = {"site_id", "bus_id", "load_mw"}
_AGGREGATE_FIELDS = {"team_count", "region_utilization", "aggregate_plan"}
_REGION_UTILIZATION_FIELDS = {"region_id", "utilization"}
_AGGREGATE_PLAN_FIELDS = {"cell_id", "lat", "lon", "contributing_teams", "requested_load_mw", "resource_count"}
_PRIVACY_POLICY_FIELDS = {"selected_team_only", "minimum_aggregate_teams"}


def _path(parent: str, child: object) -> str:
    return f"{parent}.{child}" if parent else str(child)


def _validate_json_tree(value: object, *, location: str = "package") -> object:
    """Validate JSON-compatible values and reject unsafe package keys."""
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ResultsArtifactError(f"{location} contains a non-string key")
            normalized_key = key.strip().lower().replace("-", "_")
            if normalized_key in _FORBIDDEN_KEYS:
                raise ResultsArtifactError(f"prohibited field {key!r} at {_path(location, key)}")
            if normalized_key in _ID_KEYS or normalized_key.endswith("_id"):
                if not isinstance(item, str) or not item.strip():
                    raise ResultsArtifactError(f"{_path(location, key)} must be a nonempty ID")
                result[key] = item
                continue
            result[key] = _validate_json_tree(item, location=_path(location, key))
        return result

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _validate_json_tree(item, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ResultsArtifactError(f"{location} must contain only finite numeric values")
        return value
    raise ResultsArtifactError(
        f"{location} contains unsupported value type {type(value).__name__}"
    )


def _require_mapping(payload: object, location: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ResultsArtifactError(f"{location} must be an object")
    return payload


def _require_nonempty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultsArtifactError(f"{location} must be a nonempty string")
    return value


def _require_records(value: object, location: str) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ResultsArtifactError(f"{location} must be a list")
    records: list[Mapping[str, object]] = []
    for index, item in enumerate(value):
        records.append(_require_mapping(item, f"{location}[{index}]"))
    return records


def _validate_network(network: Mapping[str, object]) -> None:
    buses = _require_records(network.get("buses"), "network.buses")
    branches = _require_records(network.get("branches"), "network.branches")
    if not buses:
        raise ResultsArtifactError("network.buses must contain at least one bus")

    bus_ids: set[str] = set()
    for index, bus in enumerate(buses):
        location = f"network.buses[{index}]"
        bus_id = _require_nonempty_string(bus.get("bus_id"), f"{location}.bus_id")
        if bus_id in bus_ids:
            raise ResultsArtifactError(f"duplicate bus_id {bus_id!r}")
        bus_ids.add(bus_id)
        for coordinate in ("lat", "lon"):
            value = bus.get(coordinate)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ResultsArtifactError(f"{location}.{coordinate} must be numeric")
            if not math.isfinite(float(value)):
                raise ResultsArtifactError(f"{location}.{coordinate} must be finite")

    branch_ids: set[str] = set()
    for index, branch in enumerate(branches):
        location = f"network.branches[{index}]"
        branch_id = _require_nonempty_string(
            branch.get("branch_id"), f"{location}.branch_id"
        )
        if branch_id in branch_ids:
            raise ResultsArtifactError(f"duplicate branch_id {branch_id!r}")
        branch_ids.add(branch_id)
        for endpoint in ("from_bus", "to_bus"):
            bus_id = _require_nonempty_string(
                branch.get(endpoint), f"{location}.{endpoint}"
            )
            if bus_id not in bus_ids:
                raise ResultsArtifactError(
                    f"{location}.{endpoint} references unknown bus {bus_id!r}"
                )


def _validate_team_sites(
    team_report: Mapping[str, object], bus_ids: set[str]
) -> None:
    """Ensure every selected-team site is attached to a public network bus."""
    if "sites" not in team_report:
        return
    sites = _require_records(team_report["sites"], "team_report.sites")
    for index, site in enumerate(sites):
        location = f"team_report.sites[{index}]"
        bus_id = _require_nonempty_string(site.get("bus_id"), f"{location}.bus_id")
        if bus_id not in bus_ids:
            raise ResultsArtifactError(
                f"{location}.bus_id references unknown bus {bus_id!r}"
            )


def _project_mapping(
    value: Mapping[str, object], allowed_fields: set[str]
) -> dict[str, object]:
    """Project a validated object to the explicitly public field set."""
    return {
        key: copy.deepcopy(value[key])
        for key in allowed_fields
        if key in value
    }


def _project_browser_package(payload: Mapping[str, object]) -> dict[str, object]:
    """Build the narrow JSON package that is safe to hand to the browser."""
    round_data = _require_mapping(payload["round"], "round")
    network = _require_mapping(payload["network"], "network")
    team_report = _require_mapping(payload["team_report"], "team_report")
    aggregate = _require_mapping(payload["aggregate"], "aggregate")
    privacy_policy = _require_mapping(
        payload["privacy_policy"], "privacy_policy"
    )

    projected_network = _project_mapping(network, _NETWORK_FIELDS)
    projected_network["buses"] = [
        _project_mapping(bus, _BUS_FIELDS)
        for bus in _require_records(network["buses"], "network.buses")
    ]
    projected_network["branches"] = [
        _project_mapping(branch, _BRANCH_FIELDS)
        for branch in _require_records(network["branches"], "network.branches")
    ]

    projected_team_report = _project_mapping(team_report, _TEAM_REPORT_FIELDS)
    if "sites" in team_report:
        projected_team_report["sites"] = [
            _project_mapping(site, _SITE_FIELDS)
            for site in _require_records(team_report["sites"], "team_report.sites")
        ]

    projected_aggregate = _project_mapping(aggregate, _AGGREGATE_FIELDS)
    if "region_utilization" in aggregate:
        projected_aggregate["region_utilization"] = [
            _project_mapping(region, _REGION_UTILIZATION_FIELDS)
            for region in _require_records(
                aggregate["region_utilization"],
                "aggregate.region_utilization",
            )
        ]
    if "aggregate_plan" in aggregate:
        projected_aggregate["aggregate_plan"] = [
            _project_mapping(cell, _AGGREGATE_PLAN_FIELDS)
            for cell in _require_records(aggregate["aggregate_plan"], "aggregate.aggregate_plan")
        ]

    return {
        "schema_version": payload["schema_version"],
        "round": _project_mapping(round_data, _ROUND_FIELDS),
        "network": projected_network,
        "team_report": projected_team_report,
        "aggregate": projected_aggregate,
        "privacy_policy": _project_mapping(
            privacy_policy, _PRIVACY_POLICY_FIELDS
        ),
    }


def validate_results_package(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate and return a detached, JSON-safe results package.

    The package is intentionally strict about network records because the
    viewer must never receive a branch that cannot be resolved to public bus
    endpoints.  Sensitive raw submissions and unredacted audit records are
    rejected recursively, including when nested in a team or aggregate field.
    """
    if not isinstance(payload, Mapping):
        raise ResultsArtifactError("results package must be an object")

    safe_payload = _validate_json_tree(payload)
    if not isinstance(safe_payload, dict):  # pragma: no cover - guarded above
        raise ResultsArtifactError("results package must be an object")

    for field in _REQUIRED_FIELDS:
        if field not in safe_payload:
            raise ResultsArtifactError(f"missing required field {field}")

    schema_version = _require_nonempty_string(
        safe_payload["schema_version"], "schema_version"
    )
    if schema_version != "results.v1":
        raise ResultsArtifactError(
            f"unsupported schema_version {schema_version!r}; expected 'results.v1'"
        )

    _require_mapping(safe_payload["round"], "round")
    network = _require_mapping(safe_payload["network"], "network")
    _validate_network(network)
    bus_ids = {
        str(bus["bus_id"])
        for bus in _require_records(network["buses"], "network.buses")
    }

    team_report = _require_mapping(safe_payload["team_report"], "team_report")
    _require_nonempty_string(team_report.get("team_id"), "team_report.team_id")
    _validate_team_sites(team_report, bus_ids)
    _require_mapping(safe_payload["aggregate"], "aggregate")
    privacy_policy = _require_mapping(
        safe_payload["privacy_policy"], "privacy_policy"
    )
    if "selected_team_only" not in privacy_policy:
        raise ResultsArtifactError("privacy_policy.selected_team_only is required")
    if privacy_policy["selected_team_only"] is not True:
        raise ResultsArtifactError(
            "privacy_policy.selected_team_only must be true for browser artifacts"
        )

    return copy.deepcopy(safe_payload)


def sanitize_results_package(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a detached browser-safe package after strict validation.

    Validation rejects malformed or explicitly prohibited input.  Projection
    then applies the positive browser contract so arbitrary evaluator fields,
    including nested data for other teams, cannot reach the client.
    """
    validated = validate_results_package(payload)
    return _project_browser_package(validated)
