"""Validation contract for the ACTIVSg2000 and IEEE-14 demo scenario packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ScenarioPackageError(ValueError):
    """Raised when a scenario package is incomplete or unvalidated."""


EXPECTED_HORIZONS = {
    "2027-jan_jun": 4344,
    "2027-jul_dec": 4416,
    "2028-jan_jun": 4368,
    "2028-jul_dec": 4416,
    "2029-jan_jun": 4344,
    "2029-jul_dec": 4416,
}

AGGREGATED_TIME_STEP_HOURS = 6
AGGREGATED_EXPECTED_HORIZONS = {
    block: horizon // AGGREGATED_TIME_STEP_HOURS
    for block, horizon in EXPECTED_HORIZONS.items()
}
# The ten-year game package: five representative days of 24 one-hour periods,
# materialized in demand_bus.csv.
REPRESENTATIVE_PACKAGE_VERSION = "activsg2000-representative-v1"
REPRESENTATIVE_BLOCK = "representative"
REPRESENTATIVE_DAY_COUNT = 5
REPRESENTATIVE_TIME_STEP_HOURS = 1
REPRESENTATIVE_HORIZON = REPRESENTATIVE_DAY_COUNT * 24
REPRESENTATIVE_EXPECTED_HORIZONS = {REPRESENTATIVE_BLOCK: REPRESENTATIVE_HORIZON}
# The IEEE-14 teaching demo uses the same representative-day format (same five
# days and weights) on the 14-bus network.  It is not a game network.
IEEE14_DEMO_PACKAGE_VERSION = "ieee14-demo-representative-v1"
REPRESENTATIVE_PACKAGE_VERSIONS = frozenset({REPRESENTATIVE_PACKAGE_VERSION, IEEE14_DEMO_PACKAGE_VERSION})
SUPPORTED_PACKAGE_VERSIONS = frozenset(
    {
        "activsg2000-scenarios-v1",
        "activsg2000-scenarios-v2-6h",
        IEEE14_DEMO_PACKAGE_VERSION,
        REPRESENTATIVE_PACKAGE_VERSION,
    }
)
# Single-block packages whose manifest.json is both package and block manifest.
_SINGLE_BLOCK_PACKAGES = {
    version: (REPRESENTATIVE_EXPECTED_HORIZONS, REPRESENTATIVE_TIME_STEP_HOURS)
    for version in REPRESENTATIVE_PACKAGE_VERSIONS
}


def expected_horizons_for_manifest(payload: dict[str, Any]) -> dict[str, int]:
    """Return the horizon contract selected by a scenario manifest."""
    version = payload.get("package_version")
    if version == "activsg2000-scenarios-v1":
        return EXPECTED_HORIZONS
    if version == "activsg2000-scenarios-v2-6h":
        return AGGREGATED_EXPECTED_HORIZONS
    if version in _SINGLE_BLOCK_PACKAGES:
        return _SINGLE_BLOCK_PACKAGES[version][0]
    raise ScenarioPackageError("unsupported scenario package_version")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_scenario_manifest(root: str | Path, *, require_validated: bool = True) -> dict[str, Any]:
    package_root = Path(root)
    path = package_root / "manifest.json"
    if not path.is_file():
        raise ScenarioPackageError(f"scenario manifest is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioPackageError(f"cannot read scenario manifest: {exc}") from exc
    expected_horizons = expected_horizons_for_manifest(payload)
    if require_validated and payload.get("validation_status") != "passed":
        raise ScenarioPackageError("scenario manifest validation_status is not passed")
    blocks = payload.get("blocks")
    if not isinstance(blocks, dict) or set(blocks) != set(expected_horizons):
        if payload.get("package_version") in REPRESENTATIVE_PACKAGE_VERSIONS:
            raise ScenarioPackageError("representative manifest must contain exactly the representative block")
        raise ScenarioPackageError("scenario manifest must contain all six half-year blocks")
    for block, horizon in expected_horizons.items():
        entry = blocks.get(block)
        if not isinstance(entry, dict) or entry.get("horizon") != horizon:
            raise ScenarioPackageError(f"invalid horizon for scenario block {block}")
        if payload.get("package_version") == "activsg2000-scenarios-v2-6h" and entry.get("time_step_hours") != AGGREGATED_TIME_STEP_HOURS:
            raise ScenarioPackageError(f"invalid time_step_hours for scenario block {block}")
        single_block = _SINGLE_BLOCK_PACKAGES.get(payload.get("package_version"))
        if single_block is not None and entry.get("time_step_hours") != single_block[1]:
            raise ScenarioPackageError(f"invalid time_step_hours for scenario block {block}")
        if not isinstance(entry.get("sha256"), str) or not entry["sha256"]:
            raise ScenarioPackageError(f"missing hash for scenario block {block}")
    network = payload.get("network")
    if not isinstance(network, dict) or not network.get("files") or not isinstance(network.get("sha256"), dict):
        raise ScenarioPackageError("scenario manifest has no network file hashes")
    for relative in network["files"]:
        file_path = package_root / relative
        if not file_path.is_file():
            raise ScenarioPackageError(f"scenario network file is missing: {relative}")
        expected = network["sha256"].get(relative)
        if expected and expected != sha256_file(file_path):
            raise ScenarioPackageError(f"scenario network hash mismatch: {relative}")
    return payload


def require_validated_block(root: str | Path) -> dict[str, Any]:
    """Load a block artifact manifest and fail closed until it is validated."""
    path = Path(root) / "manifest.json"
    if not path.is_file():
        raise ScenarioPackageError(f"scenario block manifest is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioPackageError(f"cannot read scenario block manifest: {exc}") from exc
    if payload.get("package_version") not in SUPPORTED_PACKAGE_VERSIONS:
        raise ScenarioPackageError("unsupported scenario block package_version")
    if payload.get("validation_status") != "passed":
        raise ScenarioPackageError("scenario block validation_status is not passed")
    if payload.get("package_version") in REPRESENTATIVE_PACKAGE_VERSIONS:
        _validate_representative_block(payload)
    return payload


def _validate_representative_block(payload: dict[str, Any]) -> None:
    if payload.get("horizon") != REPRESENTATIVE_HORIZON:
        raise ScenarioPackageError("invalid horizon for the representative block")
    if payload.get("time_step_hours") != REPRESENTATIVE_TIME_STEP_HOURS:
        raise ScenarioPackageError("invalid time_step_hours for the representative block")
    weights = payload.get("day_weights")
    if (
        not isinstance(weights, list)
        or len(weights) != REPRESENTATIVE_DAY_COUNT
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 for value in weights)
    ):
        raise ScenarioPackageError("representative manifest must list five positive day weights")
    if abs(sum(weights) - 365.0) > 1e-6:
        raise ScenarioPackageError("representative day weights must sum to 365")


def representative_day_weights(root: str | Path) -> tuple[float, ...]:
    """Return the per-day weights of a validated representative package."""
    payload = require_validated_block(root)
    if payload.get("package_version") not in REPRESENTATIVE_PACKAGE_VERSIONS:
        raise ScenarioPackageError("artifact is not a representative-day package")
    return tuple(float(value) for value in payload["day_weights"])
