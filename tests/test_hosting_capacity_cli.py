from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tomllib

import numpy as np
import pytest

from tools.hosting_capacity import HostingCapacityMatrix


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_hosting_capacity_module_help_works_from_source_checkout():
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, "-m", "ercot_game.hosting_capacity_cli", "--help"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Compute exact one-bus hosting capacity" in completed.stdout


def test_source_checkout_shim_preserves_installed_package_api():
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import ercot_game; "
                "assert ercot_game.__version__ == '0.3.0'; "
                "assert 'ConnectionPlan' in ercot_game.__all__; "
                "assert ercot_game.ConnectionPlan.__module__ == 'ercot_game.models'"
            ),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_pyproject_declares_only_existing_setuptools_packages():
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_dirs = payload["tool"]["setuptools"]["package-dir"]

    assert "tools.zenodo_texas" not in payload["tool"]["setuptools"]["packages"]
    assert "tools.zenodo_texas" not in package_dirs
    for package_dir in package_dirs.values():
        assert (REPO_ROOT / package_dir).is_dir()


def test_hosting_capacity_cli_accepts_prepared_artifact_arguments():
    from ercot_game.hosting_capacity_cli import parse_args

    args = parse_args(
        [
            "--artifact-dir",
            "data/processed/2028/jan_jun",
            "--horizon",
            "4368",
            "--solver-backend",
            "auto",
            "--workers",
            "4",
            "--output-dir",
            "results/hosting_capacity",
        ]
    )

    assert args.horizon == 4368
    assert args.solver_backend == "auto"
    assert args.workers == 4


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--workers", "0", "workers must be at least 1"),
        ("--solver-threads", "0", "solver-threads must be at least 1"),
        ("--horizon", "-1", "horizon must be at least 1"),
        ("--period-count", "0", "period-count must be at least 1"),
    ],
)
def test_hosting_capacity_cli_rejects_invalid_ranges(option, value, message, capsys):
    from ercot_game.hosting_capacity_cli import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--ieee14", option, value, "--output-dir", "out"])

    assert message in capsys.readouterr().err


def test_hosting_capacity_cli_defaults_to_the_released_representative_package():
    from ercot_game.hosting_capacity_cli import parse_args, provider_for_args
    from ercot_game.release_config import canonical_release_artifact_dir

    args = parse_args(["--output-dir", "out"])
    assert args.artifact_dir is None and not args.ieee14

    _provider, horizon = provider_for_args(args)

    assert args.artifact_dir == canonical_release_artifact_dir()
    assert horizon == 120


def test_hosting_capacity_cli_rejects_conflicting_input_modes(capsys):
    from ercot_game.hosting_capacity_cli import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--artifact-dir", "artifact", "--ieee14", "--output-dir", "out"])

    assert "not allowed with argument" in capsys.readouterr().err


def test_hosting_capacity_cli_rejects_nested_parallelism(capsys):
    from ercot_game.hosting_capacity_cli import parse_args

    with pytest.raises(SystemExit):
        parse_args(
            [
                "--ieee14",
                "--workers",
                "2",
                "--solver-threads",
                "2",
                "--output-dir",
                "out",
            ]
        )

    assert "workers > 1 cannot be combined with solver-threads > 1" in capsys.readouterr().err


def test_hosting_capacity_cli_prints_json_summary_and_writes_long_form(tmp_path, monkeypatch, capsys):
    from ercot_game import hosting_capacity_cli

    def fake_compute(provider, **kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        np.save(output_dir / "hosting_capacity_mw.npy", np.array([[4.0, np.nan]]))
        np.save(
            output_dir / "hosting_capacity_status.npy",
            np.array([["optimal", "solver_error"]]),
        )
        return HostingCapacityMatrix(
            period_indices=(0,),
            bus_ids=("b1", "b2"),
            capacity_mw=np.array([[4.0, np.nan]]),
            status=np.array([["optimal", "solver_error"]]),
            objective_value=np.array([[4.0, np.nan]]),
            solve_time_s=np.array([[0.01, 0.02]]),
            metadata={
                "solver_backend": "highs",
                "counts": {
                    "completed_count": 2,
                    "failed_count": 1,
                    "point_count": 2,
                },
                "complete": True,
            },
        )

    monkeypatch.setattr(hosting_capacity_cli, "compute_hosting_capacity_matrix", fake_compute)
    snapshots = iter(((1000, 500), (1400, 2500)))
    monkeypatch.setattr(hosting_capacity_cli, "_resource_usage_snapshot", lambda: next(snapshots))
    output_dir = tmp_path / "output"

    return_code = hosting_capacity_cli.main(
        [
            "--ieee14",
            "--output-dir",
            str(output_dir),
            "--write-long-form",
        ]
    )

    assert return_code == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["output_dir"] == str(output_dir.resolve())
    assert summary["completed_point_count"] == 2
    assert summary["failed_point_count"] == 1
    assert summary["requested_periods"] == [0]
    divisor = 1024 * 1024 if hosting_capacity_cli.sys.platform == "darwin" else 1024
    assert summary["peak_rss_mb"] == round(2500 / divisor, 3)
    assert summary["rss_delta_mb"] == round(2000 / divisor, 3)
    assert (output_dir / "hosting_capacity_long.csv.gz").is_file()


def test_hosting_capacity_cli_returns_interrupted_and_keeps_checkpoint(tmp_path, monkeypatch, capsys):
    from ercot_game import hosting_capacity_cli

    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()

    def interrupted_compute(provider, **kwargs):
        Path(kwargs["checkpoint_dir"]).mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / "period_000000.npz").write_bytes(b"partial checkpoint")
        raise KeyboardInterrupt

    monkeypatch.setattr(hosting_capacity_cli, "compute_hosting_capacity_matrix", interrupted_compute)
    snapshots = iter(((1000, 500), (1400, 2500)))
    monkeypatch.setattr(hosting_capacity_cli, "_resource_usage_snapshot", lambda: next(snapshots))
    output_dir = tmp_path / "output"

    return_code = hosting_capacity_cli.main(
        [
            "--ieee14",
            "--output-dir",
            str(output_dir),
            "--checkpoint-dir",
            str(checkpoint_dir),
        ]
    )

    assert return_code == 130
    summary = json.loads(capsys.readouterr().out)
    assert summary["resume_status"] == "interrupted"
    divisor = 1024 * 1024 if hosting_capacity_cli.sys.platform == "darwin" else 1024
    assert summary["peak_rss_mb"] == round(2500 / divisor, 3)
    assert summary["rss_delta_mb"] == round(2000 / divisor, 3)
    assert (checkpoint_dir / "period_000000.npz").is_file()


def test_cli_resource_metrics_report_mb_and_max_delta(monkeypatch):
    from ercot_game import hosting_capacity_cli

    class FakeResource:
        RUSAGE_SELF = object()
        RUSAGE_CHILDREN = object()

        def __init__(self):
            self.values = iter((1000, 500, 1400, 2500))

        def getrusage(self, _kind):
            return SimpleNamespace(ru_maxrss=next(self.values))

    monkeypatch.setattr(hosting_capacity_cli, "resource", FakeResource())
    before = hosting_capacity_cli._resource_usage_snapshot()
    after = hosting_capacity_cli._resource_usage_snapshot()

    divisor = 1024 * 1024 if hosting_capacity_cli.sys.platform == "darwin" else 1024
    assert hosting_capacity_cli._peak_rss_mb(after) == round(2500 / divisor, 3)
    assert hosting_capacity_cli._rss_delta_mb(before, after) == round(2000 / divisor, 3)


def test_cli_resource_metrics_are_null_when_unavailable(monkeypatch):
    from ercot_game import hosting_capacity_cli

    monkeypatch.setattr(hosting_capacity_cli, "resource", None)
    before = hosting_capacity_cli._resource_usage_snapshot()
    after = hosting_capacity_cli._resource_usage_snapshot()

    assert hosting_capacity_cli._peak_rss_mb(after) is None
    assert hosting_capacity_cli._rss_delta_mb(before, after) is None


def _write_interrupt_checkpoint(path: Path, period_index: int, statuses: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    point_count = len(statuses)
    capacities = np.full(point_count, np.nan)
    objectives = np.full(point_count, np.nan)
    optimal = np.asarray(statuses) == "optimal"
    capacities[optimal] = 1.0
    objectives[optimal] = 1.0
    np.savez_compressed(
        path,
        period_index=np.asarray(period_index, dtype=np.int64),
        identity=np.asarray("{}"),
        capacity_mw=capacities,
        status=np.asarray(statuses, dtype="<U32"),
        objective_value=objectives,
        solve_time_s=np.ones(point_count),
        diagnostic=np.full(point_count, "", dtype="<U512"),
        complete=np.asarray(True),
    )


def test_hosting_capacity_cli_interrupt_recovers_all_bus_checkpoint_counts(
    tmp_path, monkeypatch, capsys
):
    from ercot_game import hosting_capacity_cli

    buses = tuple(SimpleNamespace(bus_id=f"b{index}") for index in range(4))

    def provider(period_index):
        return SimpleNamespace(buses=buses)

    def fake_provider_for_args(args):
        return provider, 2

    monkeypatch.setattr(hosting_capacity_cli, "provider_for_args", fake_provider_for_args)
    checkpoint_dir = tmp_path / "checkpoints"

    def interrupted_compute(_provider, **kwargs):
        _write_interrupt_checkpoint(
            checkpoint_dir / "period_000000.npz",
            0,
            ["optimal", "optimal", "solver_error", "optimal"],
        )
        _write_interrupt_checkpoint(
            checkpoint_dir / "period_000001.npz",
            1,
            ["optimal", "infeasible_base_case", "optimal", "optimal"],
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(hosting_capacity_cli, "compute_hosting_capacity_matrix", interrupted_compute)
    output_dir = tmp_path / "output"

    return_code = hosting_capacity_cli.main(
        [
            "--artifact-dir",
            str(tmp_path / "artifact"),
            "--output-dir",
            str(output_dir),
            "--checkpoint-dir",
            str(checkpoint_dir),
        ]
    )

    assert return_code == 130
    summary = json.loads(capsys.readouterr().out)
    assert summary["bus_count"] == 4
    assert summary["completed_point_count"] == 8
    assert summary["failed_point_count"] == 2
    assert summary["resume_status"] == "interrupted"
    assert (checkpoint_dir / "period_000001.npz").is_file()


def test_hosting_capacity_cli_interrupt_counts_unique_selected_buses(
    tmp_path, monkeypatch, capsys
):
    from ercot_game import hosting_capacity_cli

    buses = tuple(SimpleNamespace(bus_id=f"b{index}") for index in range(4))

    def provider(period_index):
        return SimpleNamespace(buses=buses)

    def fake_provider_for_args(args):
        return provider, 1

    monkeypatch.setattr(hosting_capacity_cli, "provider_for_args", fake_provider_for_args)
    checkpoint_dir = tmp_path / "checkpoints"

    def interrupted_compute(_provider, **kwargs):
        _write_interrupt_checkpoint(
            checkpoint_dir / "period_000000.npz", 0, ["optimal", "solver_error"]
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(hosting_capacity_cli, "compute_hosting_capacity_matrix", interrupted_compute)

    return_code = hosting_capacity_cli.main(
        [
            "--artifact-dir",
            str(tmp_path / "artifact"),
            "--bus-id",
            "b0",
            "--bus-id",
            "b0",
            "--bus-id",
            "b1",
            "--output-dir",
            str(tmp_path / "output"),
            "--checkpoint-dir",
            str(checkpoint_dir),
        ]
    )

    assert return_code == 130
    summary = json.loads(capsys.readouterr().out)
    assert summary["bus_count"] == 2
    assert summary["completed_point_count"] == 2
    assert summary["failed_point_count"] == 1
