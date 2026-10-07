"""Run a reproducible scoring/feasibility sensitivity sweep for the CSV game."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
from pathlib import Path
from collections.abc import Mapping

from ercot_game.models import ConnectionPlan, GeneratorPlan, TeamPlan

from .batch_runner import BatchScoringRules, _score_team, load_scoring_rules
from .dcopf import DCOPFInfeasible
from .plan_adapter import evaluate_plans_with_prepared_dcopf


@dataclass(frozen=True)
class Scenario:
    name: str
    plans: tuple[TeamPlan, ...]


def _plan(
    team_id: str,
    sites: tuple[tuple[str, float], ...],
    *,
    horizon: int,
    region_to_bus: Mapping[str, str],
    generator_capacity_mw: float = 0.0,
    generator_cost_per_mwh: float = 100.0,
) -> TeamPlan:
    connections = tuple(
        ConnectionPlan(
            f"{team_id}-{region.lower()}",
            region_to_bus[region],
            (),
            load_mw,
            (1.0,) * horizon,
        )
        for region, load_mw in sites
    )
    generators = ()
    if generator_capacity_mw > 0:
        generators = (
            GeneratorPlan(
                f"{team_id}-generator",
                connections[0].connection_id,
                generator_capacity_mw,
                generator_cost_per_mwh,
            ),
        )
    return TeamPlan(team_id, connections=connections, generators=generators)


def build_scenarios(region_to_bus: Mapping[str, str], horizon: int) -> tuple[Scenario, ...]:
    return (
        Scenario(
            "small-diverse-sites",
            (
                _plan("team-a", (("PANHANDLE", 5.0),), horizon=horizon, region_to_bus=region_to_bus),
                _plan("team-b", (("HOUSTON_GULF", 5.0),), horizon=horizon, region_to_bus=region_to_bus),
            ),
        ),
        Scenario(
            "generator-choice",
            (
                _plan("team-a", (("PANHANDLE", 20.0),), horizon=horizon, region_to_bus=region_to_bus, generator_capacity_mw=10.0),
                _plan("team-b", (("HOUSTON_GULF", 20.0),), horizon=horizon, region_to_bus=region_to_bus),
            ),
        ),
        Scenario(
            "multi-site",
            (
                _plan("team-a", (("PANHANDLE", 10.0), ("EAST", 10.0)), horizon=horizon, region_to_bus=region_to_bus),
                _plan("team-b", (("NORTH", 10.0), ("SOUTH_TEXAS", 10.0)), horizon=horizon, region_to_bus=region_to_bus),
            ),
        ),
        Scenario(
            "stress-infeasible",
            (
                _plan("team-a", (("PANHANDLE", 1000.0),), horizon=horizon, region_to_bus=region_to_bus),
                _plan("team-b", (("HOUSTON_GULF", 1000.0),), horizon=horizon, region_to_bus=region_to_bus),
            ),
        ),
    )


def run_sweep(
    *,
    artifact_dir: str | Path,
    base_rules: BatchScoringRules,
    scenarios: tuple[Scenario, ...],
    horizon: int,
    period_indices: tuple[int, ...],
    it_values: tuple[float, ...] = (100.0, 175.0, 250.0),
    generator_costs: tuple[float, ...] = (50.0, 100.0, 150.0),
    capital_costs: tuple[float, ...] = (0.0, 50_000.0, 100_000.0),
    site_costs: tuple[float, ...] = (0.0, 25_000.0, 50_000.0),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        for generator_cost in generator_costs:
            plans = tuple(
                TeamPlan(
                    plan.team_id,
                    connections=plan.connections,
                    generators=tuple(
                        GeneratorPlan(item.generator_id, item.connection_id, item.capacity_mw, generator_cost)
                        for item in plan.generators
                    ),
                )
                for plan in scenario.plans
            )
            try:
                dispatch = evaluate_plans_with_prepared_dcopf(
                    artifact_dir,
                    plans,
                    period_indices=period_indices,
                )
            except DCOPFInfeasible as exc:
                rows.append({
                    "scenario": scenario.name,
                    "generator_cost_per_mwh": generator_cost,
                    "feasible": False,
                    "failure_reason": str(exc),
                    "it_value_per_mwh": None,
                    "generator_capital_cost_per_mw": None,
                    "site_cost_per_site": None,
                    "scores": {},
                    "ranking": [],
                })
                continue
            for it_value in it_values:
                for capital_cost in capital_costs:
                    for site_cost in site_costs:
                        rules = BatchScoringRules(
                            rules_version=base_rules.rules_version,
                            it_value_per_mwh=(it_value,) * horizon,
                            energy_price_per_mwh=base_rules.energy_price_per_mwh,
                            time_step_hours=base_rules.time_step_hours,
                            generator_capital_cost_per_mw=capital_cost,
                            site_cost_per_site=site_cost,
                            infeasible_score=base_rules.infeasible_score,
                            default_generator_cost_per_mwh=generator_cost,
                        )
                        scores = tuple(_score_team(plan, dispatch, rules) for plan in plans)
                        ordered = sorted(scores, key=lambda score: (-score.score, score.team_id))
                        rows.append({
                            "scenario": scenario.name,
                            "generator_cost_per_mwh": generator_cost,
                            "feasible": True,
                            "failure_reason": None,
                            "it_value_per_mwh": it_value,
                            "generator_capital_cost_per_mw": capital_cost,
                            "site_cost_per_site": site_cost,
                            "scores": {score.team_id: round(score.score, 2) for score in scores},
                            "ranking": [score.team_id for score in ordered],
                        })
    return rows


def render_report(rows: list[dict[str, object]], *, source_rules: str) -> str:
    feasible_rows = [row for row in rows if row["feasible"]]
    infeasible_scenarios = sorted({str(row["scenario"]) for row in rows if not row["feasible"]})
    rankings = {tuple(row["ranking"]) for row in feasible_rows if row["ranking"]}
    scores = [score for row in feasible_rows for score in row["scores"].values()]  # type: ignore[union-attr]
    lines = [
        "# Dispatch-scoring sensitivity report",
        "",
        "**Status:** Instructor calibration draft generated from the prepared Texas dispatch artifact.",
        "",
        f"Rules source: `{source_rules}`.",
        "",
        "## Summary",
        "",
        f"- Sweep rows: **{len(rows)}**.",
        f"- Feasible score configurations: **{len(feasible_rows)}**.",
        f"- Distinct feasible ranking orders: **{len(rankings)}**.",
        f"- Feasible score range observed: **${min(scores):,.2f}–${max(scores):,.2f}**." if scores else "- No feasible score configurations were observed.",
        f"- Stress scenarios detected as infeasible: `{', '.join(infeasible_scenarios) or 'none'}`.",
        "",
        "## Interpretation",
        "",
        "This sweep is a calibration diagnostic, not a claim that the tested plan set is representative of student behavior. A good release configuration should preserve a mixture of feasible and infeasible plans, produce multiple meaningful ranking outcomes, and avoid making capital or site cost overwhelm all energy-value terms.",
        "",
        "## Scenario results",
        "",
        "| Scenario | Generator cost ($/MWh) | Feasible rows | Infeasible rows | Ranking orders | Score range ($) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    scenario_names = sorted({str(row["scenario"]) for row in rows})
    for name in scenario_names:
        subset = [row for row in rows if row["scenario"] == name]
        feasible = [row for row in subset if row["feasible"]]
        scenario_scores = [score for row in feasible for score in row["scores"].values()]  # type: ignore[union-attr]
        generator_costs = sorted({float(row["generator_cost_per_mwh"]) for row in subset})
        ranking_count = len({tuple(row["ranking"]) for row in feasible if row["ranking"]})
        lines.append(
            f"| {name} | {', '.join(f'{value:g}' for value in generator_costs)} | {len(feasible)} | {len(subset) - len(feasible)} | {ranking_count} | "
            + (f"{min(scenario_scores):,.2f}–{max(scenario_scores):,.2f} |" if scenario_scores else "— |")
        )
    lines += [
        "",
        "## Instructor decisions still required",
        "",
        "1. Select a candidate-generator technology and replace the generic variable-cost placeholder.",
        "2. Choose the capital-cost annualization and the fraction assigned to the game horizon.",
        "3. Choose whether site cost is per site, per MW, or a published interconnection-cost proxy.",
        "4. Review the score/ranking spread against actual pilot CSVs before approving release rules.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", default="data/processed/texas_dispatch_source_v1")
    parser.add_argument("--rules", default="data/teaching/dispatch_scoring_rules_v1.json")
    parser.add_argument("--region-map", default="data/teaching/planning_region_source_bus_map_v1.json")
    parser.add_argument("--output", default="docs/ERCOT_DISPATCH_SCORING_SENSITIVITY.md")
    parser.add_argument(
        "--period-indices",
        default="0",
        help="comma-separated zero-based source periods; default 0 for a fast diagnostic, use 0,1,2,3,4,5 for the full teaching horizon",
    )
    args = parser.parse_args()

    region_payload = json.loads(Path(args.region_map).read_text(encoding="utf-8"))
    region_to_bus = {name: item["source_bus_id"] for name, item in region_payload["regions"].items()}
    base_rules = load_scoring_rules(args.rules)
    horizon = len(base_rules.energy_price_per_mwh)
    period_indices = tuple(int(value) for value in args.period_indices.split(",") if value.strip())
    rows = run_sweep(
        artifact_dir=args.artifact_dir,
        base_rules=base_rules,
        scenarios=build_scenarios(region_to_bus, horizon),
        horizon=horizon,
        period_indices=period_indices,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(rows, source_rules=args.rules), encoding="utf-8")
    print(f"wrote {output} ({len(rows)} sweep rows)")


if __name__ == "__main__":
    main()
