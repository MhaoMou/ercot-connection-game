from __future__ import annotations

import csv
import json
from pathlib import Path
import zipfile

import pytest

from tools.zenodo_texas.extract import extract_archive


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixture_archive(tmp_path: Path, *, invalid_reference: bool = False) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _write_csv(
        source / "bus.csv",
        [
            {"bus_id": "100", "interconnect": "Eastern", "Pd": "1"},
            {"bus_id": "200", "interconnect": "Texas", "Pd": "2"},
        ],
    )
    _write_csv(
        source / "branch.csv",
        [
            {
                "branch_id": "b1",
                "from_bus_id": "200",
                "to_bus_id": "999" if invalid_reference else "200",
                "interconnect": "Texas",
            }
        ],
    )
    _write_csv(
        source / "sub.csv",
        [{"sub_id": "s1", "interconnect": "Texas"}],
    )
    _write_csv(
        source / "bus2sub.csv",
        [{"bus_id": "200", "sub_id": "s1", "interconnect": "Texas"}],
    )
    _write_csv(
        source / "plant.csv",
        [{"plant_id": "p1", "bus_id": "200", "interconnect": "Texas"}],
    )
    _write_csv(
        source / "gencost.csv",
        [{"plant_id": "p1", "c1": "5", "interconnect": "Texas"}],
    )
    _write_csv(
        source / "dcline.csv",
        [{
            "dcline_id": "d1",
            "from_bus_id": "200",
            "to_bus_id": "300",
            "from_interconnect": "Texas",
            "to_interconnect": "Western",
        }],
    )
    _write_csv(
        source / "zone.csv",
        [{"zone_id": "301", "state": "Texas", "interconnect": "Texas"}],
    )
    _write_csv(
        source / "demand.csv",
        [
            {"UTC Time": "2020-01-01T00:00:00", "301": "2", "100": "1"},
        ],
    )
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in source.iterdir():
            handle.write(path, f"base_grid/{path.name}")
    return archive


def test_extracts_texas_rows_and_preserves_headers(tmp_path: Path):
    output = tmp_path / "output"

    report = extract_archive(_fixture_archive(tmp_path), output)

    assert report["selection_rule"] == "interconnect == Texas"
    assert report["row_counts"]["bus"] == 1
    assert report["row_counts"]["branch"] == 1
    with (output / "bus.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{"bus_id": "200", "interconnect": "Texas", "Pd": "2"}]


def test_reports_unresolved_references_and_cross_interconnect_dc_line(tmp_path: Path):
    report = extract_archive(_fixture_archive(tmp_path, invalid_reference=True), tmp_path / "output")

    assert any("branch endpoint" in message for message in report["errors"])
    assert report["dc_lines"]["cross_interconnect_count"] == 1
    assert report["valid"] is False


def test_reports_profile_coverage_without_fabricating_semantics(tmp_path: Path):
    report = extract_archive(_fixture_archive(tmp_path), tmp_path / "output")

    demand = report["profiles"]["demand.csv"]
    assert demand["timestamp_column"] == "UTC Time"
    assert demand["column_count"] == 2
    assert demand["matching_selected_zone_columns"] == 1
    assert demand["matching_selected_bus_columns"] == 0
    assert demand["unresolved_column_count"] == 1
    assert demand["unresolved_columns"] == ["100"]
    assert demand["status"] == "partial_zone_id_coverage"
    with (tmp_path / "output" / "demand.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{"UTC Time": "2020-01-01T00:00:00", "301": "2"}]


def test_manifest_hashes_are_deterministic_and_complete(tmp_path: Path):
    output = tmp_path / "output"
    extract_archive(_fixture_archive(tmp_path), output)

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == sorted(manifest["files"])
    assert set(manifest["sha256"]) == set(manifest["files"])
    assert all(len(value) == 64 for value in manifest["sha256"].values())


def test_rejects_archive_without_required_file(tmp_path: Path):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass

    with pytest.raises(ValueError, match="missing required source file"):
        extract_archive(archive, tmp_path / "output")
