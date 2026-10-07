import inspect
import json
import re
from pathlib import Path

from ercot_game import practice_server
from ercot_game import validate
from ercot_game import allocation
from ercot_game.evaluator import evaluate_week
from ercot_game.io import plan_from_dict, scenario_from_dict
from ercot_game.practice_serialization import evaluation_response


PROJECT_ROOT = Path(__file__).parents[1]
DOCUMENTATION = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "docs/phase-1-evaluator.md",
    PROJECT_ROOT / "docs/phase-2-practice-interface.md",
    PROJECT_ROOT / "docs/phase-2-handoff.md",
)
BATCH_DOCUMENTATION = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "docs/ERCOT_INSTRUCTOR_BATCH_EVALUATION.md",
    PROJECT_ROOT / "examples/instructor_batch/README.md",
    PROJECT_ROOT / "work/pilot_submissions/README.md",
)
RESULTS_DOCUMENTATION = (
    PROJECT_ROOT / "docs/ERCOT_INSTRUCTOR_RELEASE_NOTE.md",
    PROJECT_ROOT / "docs/ERCOT_MAP_PERFORMANCE.md",
)
PRACTICE_DOCS = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "docs/phase-2-practice-interface.md",
)
APP_JS = PROJECT_ROOT / "web/app.js"


def _text(paths: tuple[Path, ...]) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_active_batch_documentation_uses_current_half_year_contract():
    docs = _text(BATCH_DOCUMENTATION)
    assert "4368" in docs
    assert "4416" in docs
    assert "source-period-offset" in docs
    assert "source rows" in docs
    assert "fair continuous projection" in docs.lower()
    assert "team-owned" in docs.lower()
    assert "storage capital" in docs.lower()
    assert "storage operating" in docs.lower()
    assert "public-data" in docs.lower() or "zenodo" in docs.lower()
    assert "horizon=6" not in docs
    assert "/private/tmp/ercot-game-dcopf-venv" not in docs


def test_active_batch_examples_use_bus_ids_and_real_catalog_ids():
    docs = _text(BATCH_DOCUMENTATION)
    assert "placeholder-generator" not in docs
    assert "storage is reserved" not in docs.lower()
    examples = (PROJECT_ROOT / "examples/instructor_batch").glob("*.csv")
    for path in examples:
        header = path.read_text(encoding="utf-8").splitlines()[0]
        assert "bus_id" in header
        assert "site_id" not in header
    for path in (PROJECT_ROOT / "work/pilot_submissions").glob("*.csv"):
        if path.name == "team-malformed.csv":
            continue
        header = path.read_text(encoding="utf-8").splitlines()[0]
        assert "bus_id" in header
        assert "site_id" not in header


def test_pyproject_declares_source_and_tools_runtime_packages():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'tools = "tools"' in pyproject
    assert '"tools.zenodo_texas" = "tools/zenodo_texas"' in pyproject


def test_documented_local_markdown_links_resolve():
    for document in DOCUMENTATION:
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", text):
            if "://" in target or target.startswith("mailto:"):
                continue
            assert (document.parent / target).exists(), (document, target)


def test_documented_fixture_and_example_paths_exist():
    documented_paths = (
        "data/fixtures/ercot_small.json",
        "examples/week_01_submissions.json",
        "web/index.html",
        "web/styles.css",
        "web/app.js",
    )
    docs = _text(PRACTICE_DOCS + (PROJECT_ROOT / "docs/phase-1-evaluator.md",))
    for relative_path in documented_paths:
        assert (PROJECT_ROOT / relative_path).is_file(), relative_path
        assert relative_path in docs, relative_path


def test_practice_docs_match_current_server_methods_routes_and_statuses():
    readme, guide = (path.read_text(encoding="utf-8") for path in PRACTICE_DOCS)
    docs = readme + "\n" + guide
    handler_source = inspect.getsource(practice_server.PracticeRequestHandler)
    get_source = inspect.getsource(practice_server.PracticeRequestHandler.do_GET)
    post_source = inspect.getsource(practice_server.PracticeRequestHandler.do_POST)

    documented_routes = {
        "GET": ("/api/health", "/api/scenario", *practice_server._STATIC_ASSETS),
        "POST": ("/api/evaluate",),
    }
    for method, routes in documented_routes.items():
        for route in routes:
            if route in practice_server._STATIC_ASSETS:
                assert f"| {method} | {route} |" in guide, (method, route)
            else:
                assert f"{method} {route}" in docs, (method, route)

    assert 'path == "/api/health"' in get_source
    assert 'path == "/api/scenario"' in get_source
    assert 'urlsplit(self.path).path != "/api/evaluate"' in post_source
    for route in practice_server._STATIC_ASSETS:
        assert route in docs

    status_contract = {
        "200": ("HTTPStatus.OK",),
        "400": ("HTTPStatus.BAD_REQUEST", "malformed_json", "missing_plan"),
        "413": ("HTTPStatus.REQUEST_ENTITY_TOO_LARGE", "request_too_large"),
        "422": ("HTTPStatus.UNPROCESSABLE_ENTITY", "invalid_plan", "evaluation_input"),
        "404": ("HTTPStatus.NOT_FOUND", "not_found"),
        "500": ("HTTPStatus.INTERNAL_SERVER_ERROR", "internal_error"),
    }
    for status, source_tokens in status_contract.items():
        assert f"| {status} |" in guide or status in readme, status
        for token in source_tokens:
            assert token in handler_source, token


def test_phase3_server_contract_is_present_and_safe():
    source = inspect.getsource(practice_server.PracticeRequestHandler)
    module_source = inspect.getsource(practice_server)
    for route in (
        "/api/session",
        "/api/session/revoke",
        "/api/rounds/",
        "/draft",
        "/submit",
        "submission",
        "leaderboard",
        "/api/instructor/rounds/",
        "/transition",
        "/evaluate",
        "/audit",
    ):
        assert route in source
    for code in (
        "unauthorized",
        "forbidden",
        "round_not_open",
        "deadline_passed",
        "duplicate_submission",
        "invalid_transition",
        "validation_failed",
        "evaluation_failed",
        "request_id",
    ):
        assert code in source
    assert "Bearer " in source
    assert "build_batch_input" in source
    assert "evaluate_locked_round" in source
    assert "RoundStore" in module_source
    assert "SessionManager" in module_source
    assert "X-Bootstrap-Credential" in module_source
    assert "trusted local bootstrap" in module_source
    assert "Repeating a successful" in module_source
    assert "_phase3_method_guard" in module_source
    assert "allowed_methods" in module_source
    assert "send_error" in module_source
    assert "NOT_IMPLEMENTED" in module_source


def test_practice_docs_match_current_server_asset_content_types_and_limits():
    guide = (PROJECT_ROOT / "docs/phase-2-practice-interface.md").read_text(
        encoding="utf-8"
    )
    source = inspect.getsource(practice_server)
    for route, (filename, content_type) in practice_server._STATIC_ASSETS.items():
        assert route in guide
        assert filename in guide
        assert content_type in guide
    assert str(practice_server.MAX_REQUEST_BODY_BYTES // 1024 // 1024) + " MiB" in guide
    assert "MAX_REQUEST_BODY_BYTES" in source


def test_practice_documentation_matches_server_parser_flags():
    docs = _text(PRACTICE_DOCS)
    parser = practice_server._build_parser()
    help_text = parser.format_help()
    for flag in ("--scenario", "--host", "--port"):
        assert flag in help_text
        assert flag in docs

    defaults = parser.parse_args([])
    assert defaults.host == "localhost"
    assert defaults.port == 8000
    assert defaults.scenario == practice_server._default_scenario_path()
    assert "host localhost" in docs
    assert "port 8000" in docs


def test_documentation_states_client_and_generator_semantics():
    readme, guide = (path.read_text(encoding="utf-8") for path in PRACTICE_DOCS)
    assert "does not reimplement scoring, optimization, or feasibility logic" in readme
    for phrase in (
        "validates and serializes the form",
        "manages selection/loading/pending/result/error state",
        "server remains authoritative",
    ):
        assert phrase in readme
    for field in ("generator_id", "capacity_mw", "marginal_cost_per_mwh"):
        assert field in guide
    assert "finite and non-negative" in guide
    assert "current evaluator/API rejects negative values" in guide
    assert "browser uses the same non-negative range" in guide
    assert "current validator does not require it to be non-negative" not in guide
    assert "zero generator dispatch" in guide


def test_generator_documentation_matches_app_validation_landmarks():
    guide = (PROJECT_ROOT / "docs/phase-2-practice-interface.md").read_text(
        encoding="utf-8"
    )
    app = APP_JS.read_text(encoding="utf-8")
    for landmark in (
        "function readNumericField",
        'readNumericField(capacityField, "Generator capacity", { min: 0 })',
        'readNumericField(costField, "Generator marginal cost", { min: 0 })',
        "const generators = []",
        "generators.push({ generator_id: generatorId",
        "Number.isFinite(value)",
    ):
        assert landmark in app, landmark
    for phrase in (
        "checks form completeness",
        "finite, non-negative capacity and marginal cost",
        "current evaluator/API rejects negative values",
        "browser uses the same non-negative range",
        "server remains authoritative",
    ):
        assert phrase in guide


def test_documentation_contains_exact_verification_commands():
    docs = _text(DOCUMENTATION)
    commands = (
        "pytest -q",
        "pytest tests/test_practice_serialization.py tests/test_practice_server.py tests/test_web_assets.py -q",
        "PYTHONPATH=src python -m ercot_game.practice_server --help",
        "PYTHONPATH=src python -m ercot_game.practice_server --scenario data/fixtures/ercot_small.json --host 127.0.0.1 --port 8765",
    )
    for command in commands:
        assert command in docs, command


def test_results_release_documentation_describes_sanitized_package_contract():
    docs = _text(RESULTS_DOCUMENTATION)
    for phrase in (
        "build_results_package.py",
        "--network",
        "--evaluation",
        "--team",
        "--output-dir",
        "results.v1",
        "selected-team-only",
        "aggregate suppression",
        "three verified contributing teams",
        "/results",
    ):
        assert phrase in docs, phrase


def test_results_release_documentation_separates_evaluator_from_browser_viewer():
    docs = _text(RESULTS_DOCUMENTATION).lower()
    for phrase in (
        "evaluator-authoritative",
        "browser visualization only",
        "browser-facing",
        "does not recompute",
        "sanitized",
    ):
        assert phrase in docs, phrase


def test_results_release_documentation_states_privacy_boundary_and_schema_artifacts():
    docs = _text(RESULTS_DOCUMENTATION)
    for artifact in (
        "round_metadata.json",
        "public_network.json",
        "team_report.json",
        "aggregate_grid_summary.json",
    ):
        assert artifact in docs, artifact
    for phrase in (
        "raw submissions",
        "cross-team",
        "other teams",
        "privacy boundary",
    ):
        assert phrase.lower() in docs.lower(), phrase


def test_documentation_describes_canonical_team_plan_schema_and_legacy_normalization():
    docs = _text(DOCUMENTATION)
    canonical_fields = (
        "connections[]",
        "connection_id",
        "bus_id",
        "path_corridors",
        "capacity_mw",
        "profile",
        "generators[]",
        "generator_id",
        "connection_id",
        "marginal_cost_per_mwh",
        "intervention_budget_k",
        "curtailment_depth_mu",
        "flexibility_fee_per_mwh",
    )
    for field in canonical_fields:
        assert field in docs, field
    assert "one connection" in docs
    assert "connection-legacy" in docs
    assert "generator-legacy" in docs
    assert "server remains authoritative" in docs
    assert "server is the source of truth" in docs


def test_documentation_describes_nested_generator_constraints_and_diagnostics():
    docs = _text(DOCUMENTATION)
    for phrase in (
        "generators[].connection_id",
        "must reference an existing connection_id",
        "generator capacity",
        "marginal cost",
        "connection_results",
        "generator_dispatch",
        "site_diagnostics",
        "team_totals",
        "aggregate_diagnostics",
        "binding",
        "curtailed",
    ):
        assert phrase in docs, phrase


def test_documentation_describes_teaching_map_counts_interactions_and_disclaimer():
    docs = _text(PRACTICE_DOCS)
    for phrase in (
        "32 schematic buses",
        "48 representative corridors",
        "8 teaching zones",
        "period selector",
        "hover",
        "keyboard-focus",
        "click/tap",
        "persistent",
        "detail drawer",
        "connection editor",
        "generator editor",
        "tutorial",
        "K",
        "μ",
        "schematic",
        "not operational",
    ):
        assert phrase in docs, phrase


def test_documentation_describes_exact_api_query_examples_and_status_contract():
    docs = _text(DOCUMENTATION)
    for route in (
        "GET /api/health",
        "GET /api/scenario",
        "GET /api/scenario?period=N",
        "POST /api/evaluate",
        "GET /",
        "GET /styles.css",
        "GET /app.js",
    ):
        assert route in docs, route
    for status in ("200", "400", "413", "422", "404", "500"):
        assert status in docs, status
    for example in (
        '"connections": [',
        '"generators": [',
        '"bus_id": "bus-central"',
        '"generator": null',
        "?period=2",
        "input_hash",
        "evaluator_version",
    ):
        assert example in docs, example
    for command in (
        "PYTHONPATH=src python -m ercot_game.cli validate",
        "PYTHONPATH=src python -m ercot_game.cli evaluate",
        "pytest tests/test_documentation.py -q",
    ):
        assert command in docs, command


def test_documentation_binds_map_counts_to_fixture_and_initial_period_request():
    fixture_path = PROJECT_ROOT / "data/fixtures/ercot_small.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    docs = _text(PRACTICE_DOCS)
    app = APP_JS.read_text(encoding="utf-8")

    bus_count = len(fixture["buses"])
    corridor_count = len(fixture["corridors"])
    zone_count = len(fixture["presentation"]["zone_labels"])
    assert (bus_count, corridor_count, zone_count) == (32, 48, 8)
    assert f"{bus_count} schematic buses" in docs
    assert f"{corridor_count} representative corridors" in docs
    assert f"{zone_count} teaching zones" in docs

    assert 'fetch("/api/scenario?period=0",' in app
    assert "initial client request is `/api/scenario?period=0`" in docs


def test_documentation_describes_strict_period_query_syntax():
    guide = (PROJECT_ROOT / "docs/phase-2-practice-interface.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "GET /api/scenario?period=N",
        "period=0",
        "zero-based",
        "exactly one recognized `period` key",
        "strict period query syntax",
        "repeated",
        "unknown",
        "blank",
        "non-integer",
        "out-of-range",
        "invalid_period",
    ):
        assert phrase in guide, phrase


def test_documentation_matches_negative_generator_cost_validation():
    docs = _text(DOCUMENTATION)
    source = inspect.getsource(validate.validate_plan)
    assert "marginal_cost_per_mwh must be non-negative" in source
    for phrase in (
        "marginal_cost_per_mwh",
        "finite and non-negative",
        "current evaluator/API rejects negative values",
        "browser uses the same non-negative range",
    ):
        assert phrase in docs, phrase
    assert "borderline resources" not in docs
    assert "varied/overlapping resource profiles" in docs


def _fixture_scenario_and_documentation_plan():
    fixture = json.loads(
        (PROJECT_ROOT / "data/fixtures/ercot_small.json").read_text(encoding="utf-8")
    )
    scenario = scenario_from_dict(fixture)
    plan = plan_from_dict(
        {
            "team_id": "documentation-schema",
            "connections": [
                {
                    "connection_id": "documentation-site",
                    "bus_id": scenario.buses[0].bus_id,
                    "path_corridors": [scenario.corridors[0].corridor_id],
                    "capacity_mw": 1.0,
                    "profile": [0.0] * len(scenario.energy_price_per_mwh),
                }
            ],
            "generators": [],
            "intervention_budget_k": 0,
            "curtailment_depth_mu": 0.0,
            "flexibility_fee_per_mwh": 0.0,
        }
    )
    return scenario, plan


def test_documentation_response_schema_matches_fixture_evaluation():
    scenario, plan = _fixture_scenario_and_documentation_plan()
    response = evaluation_response(evaluate_week(scenario, None, (plan,)))
    docs = _text(DOCUMENTATION)

    assert {
        "evaluator_version",
        "scenario_id",
        "input_hash",
        "team_results",
        "connection_results",
        "generator_dispatch",
        "site_diagnostics",
        "team_totals",
        "aggregate_diagnostics",
    } <= response.keys()
    team = response["team_results"][0]
    assert {
        "allocation",
        "recourse",
        "connection_results",
        "generator_dispatch_results",
        "score_breakdown",
        "diagnostics",
    } <= team.keys()
    assert {
        "team_id",
        "connection_id",
        "bus_id",
        "path_corridors",
        "allocation",
        "recourse",
        "score_breakdown",
        "diagnostics",
    } <= response["connection_results"][0].keys()
    assert {"team_id", "connection_id", "bus_id", "diagnostics"} == set(
        response["site_diagnostics"][0]
    )
    assert {"team_id", "feasible", "score_breakdown", "total"} == set(
        response["team_totals"][0]
    )
    for phrase in (
        "site_diagnostics is the identity/basic site-info view",
        "connection_results carries allocation, recourse, score_breakdown, and diagnostics",
        "team results carry aggregate allocation, recourse, scores, and diagnostics",
        "aggregate_diagnostics carries resource, binding/curtailment, and unserved summaries",
    ):
        assert phrase in docs, phrase


def test_documentation_balance_equation_matches_fixture_result_fields():
    scenario, plan = _fixture_scenario_and_documentation_plan()
    response = evaluation_response(evaluate_week(scenario, None, (plan,)))
    docs = _text(DOCUMENTATION)
    docs_lower = docs.lower()
    team = response["team_results"][0]

    assert "requested = served + curtailed + residual_unserved" in docs
    assert "requested = served + generator_supply + curtailed + residual_unserved" not in docs
    assert "generator supply is included in served" in docs_lower
    assert "grid supply is recorded separately" in docs_lower
    assert {"served_mw", "curtailed_mw", "residual_unserved_mw"} <= team["recourse"].keys()
    assert "grid_supply_mw" in team["diagnostics"]
    assert "generator_supply" not in team["recourse"]


def test_documentation_corridor_semantics_match_allocator_and_legacy_boundary():
    docs = _text(DOCUMENTATION)
    docs_lower = docs.lower()
    allocator = inspect.getsource(allocation._multi_site_allocation)
    allocator_lower = allocator.lower()

    assert "bus requests are aggregated" in docs_lower
    assert "shared corridor capacity is consumed sequentially" in docs_lower
    assert "(connection_id, team_id)" in docs
    assert "legacy proportional behavior only where applicable" in docs_lower
    assert "bus sharing retains the phase 1 proportional rule" in allocator_lower
    assert "sequentially in canonical ``(connection_id, team_id)`` order" in allocator


def test_documentation_does_not_retain_pre_migration_network_claims():
    docs = _text(DOCUMENTATION).lower()
    for stale_claim in (
        "three-bus",
        "three bus",
        "two-corridor",
        "two corridor",
    ):
        assert stale_claim not in docs, stale_claim


def test_phase_three_handoff_marks_future_multi_team_and_rl_work_explicitly():
    handoff = (PROJECT_ROOT / "docs/phase-2-handoff.md").read_text(
        encoding="utf-8"
    )
    assert "future design and research work, not current capabilities" in handoff
    for phrase in (
        "multi-team ordering",
        "persistent rounds",
        "instructor controls",
        "fairness",
        "shared corridor",
        "Gymnasium",
        "RL wrapper",
        "not implemented",
    ):
        assert phrase in handoff, phrase


def test_phase_three_handoff_documents_canonical_corridor_ordering():
    handoff = (PROJECT_ROOT / "docs/phase-2-handoff.md").read_text(
        encoding="utf-8"
    )
    handoff_lower = handoff.lower()
    assert "bus requests are aggregated" in handoff_lower
    assert "shared corridor capacity is consumed sequentially by" in handoff_lower
    assert "(connection_id, team_id)" in handoff
    assert "legacy proportional behavior only where applicable" in handoff_lower
    assert "aggregate shared bus/corridor requests before allocation" not in handoff_lower
