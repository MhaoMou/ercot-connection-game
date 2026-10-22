"""Numerical equilibrium analysis of the one-submission connection game on the
IEEE 14-bus teaching demo.

Every payoff reported here comes from the real evaluator
(``ercot_game.batch_evaluation.evaluate_csv_batch``, the function behind
``ercot-game-batch run``) on the full 120-hour representative horizon (5 days x 24 h standing for
ten years), Week 3 scoring (energy paid at the joint-dispatch LMP).  Each team submits one site: a bus and a
requested connection capacity (no generator, no storage; experiment 4 adds an
optional generator).  A request of 0 MW means "do not enter".

A small LP (DC power flow with PTDFs, all 120 hours, constant team loads) is
used only to locate points of the feasible region H exactly: the max-min-fair
point w, the planner optimum and the region boundary for the figures.  Every
point that is reported is re-evaluated with the evaluator.

Experiments
  1  fixed buses, continuous requests: w, best-response check, BR dynamics,
     planner optimum, price of anarchy
  2  two teams with bus choice: full payoff matrix, pure and mixed equilibria
  3  three and four teams with bus choice: best-response dynamics
  4  experiment 2 with an optional generator G in {0, 0.25 r, 0.5 r}
  5  (after 1) epsilon-equilibrium check of the non-converging LMP dynamics
     in case (c): largest deviation gain at the last states visited
  6  (after 5) global best-response search for a pure equilibrium in case (c)
     with LMP payoffs (bounded to 40 rounds per start)

Usage (from the repository root):
    python docs/student_tutorial/scripts/game_equilibrium_ieee14.py            # everything
    python docs/student_tutorial/scripts/game_equilibrium_ieee14.py --quick    # smoke run
    python docs/student_tutorial/scripts/game_equilibrium_ieee14.py --exp 1 2 --workers 8
    python docs/student_tutorial/scripts/game_equilibrium_ieee14.py --figures-only

Outputs: docs/student_tutorial/data/game_equilibrium/*.json|csv and
docs/student_tutorial/figures/ne_*.pdf.  Evaluator results are cached in
work/game_equilibrium_cache/ (keyed by the full profile) so re-runs are fast.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import multiprocessing as mp
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
for _path in (REPO, REPO / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

ARTIFACT = REPO / "data" / "teaching" / "ieee14_demo_representative"
RULES = REPO / "data" / "teaching" / "dispatch_scoring_rules_ieee14_demo_representative_v1.json"
HORIZON = 120
OUT = REPO / "docs" / "student_tutorial" / "data" / "game_equilibrium"
FIG = REPO / "docs" / "student_tutorial" / "figures"
CACHE_DIR = REPO / "work" / "game_equilibrium_cache"
TEAM_IDS = ("team-a", "team-b", "team-c", "team-d")
CSV_HEADER = (
    "team_id,site_id,bus_id,connection_capacity_mw,"
    "generator_capacity_mw,storage_power_mw,storage_energy_mwh\n"
)
EPS = 1.0  # $ tolerance when comparing payoffs (scores are ~1e6-1e8 $)

_RULE_PAYLOAD = json.loads(RULES.read_text(encoding="utf-8"))
IT_VALUE = float(_RULE_PAYLOAD["it_value_per_mwh"][0])
SITE_COST = float(_RULE_PAYLOAD["site_cost_per_mw"])
WEIGHT_HOURS = float(sum(_RULE_PAYLOAD["period_weight_hours"]))  # ten-year present-value hours
ANNUAL_HOURS = float(sum(_RULE_PAYLOAD["period_day_weights"]))  # served_load_mwh is per represented year
MARGIN_PER_MW = IT_VALUE * WEIGHT_HOURS - SITE_COST  # value minus site cost per served MW, before energy


# ---------------------------------------------------------------------------
# Evaluator oracle
# ---------------------------------------------------------------------------

_WORKER_RULES = None


def _rules():
    global _WORKER_RULES
    if _WORKER_RULES is None:
        from ercot_game.batch_evaluation import load_scoring_rules

        _WORKER_RULES = load_scoring_rules(RULES, artifact_dir=ARTIFACT, horizon=HORIZON)
    return _WORKER_RULES


def canonical(profile) -> tuple:
    """Profile = sequence of (bus, mw[, gen_mw]) for team-a, team-b, ..."""
    out = []
    for site in profile:
        bus, mw = str(site[0]), float(site[1])
        gen = float(site[2]) if len(site) > 2 else 0.0
        if mw <= 0.0:
            bus, mw, gen = "0", 0.0, 0.0
        out.append((bus, round(mw, 4), round(gen, 4)))
    return tuple(out)


def write_plans(profile, directory: Path) -> None:
    for team_id, (bus, mw, gen) in zip(TEAM_IDS, canonical(profile)):
        if mw <= 0.0:
            continue
        with (directory / f"{team_id}.csv").open("w", encoding="utf-8") as handle:
            handle.write(CSV_HEADER)
            handle.write(f"{team_id},site-1,{bus},{mw:.4f},{gen:.4f},0,0\n")


def evaluate_profile(profile, *, min_fraction: float | None = None) -> dict:
    """Run the evaluator on one profile (teams with 0 MW stay out)."""
    from ercot_game import batch_evaluation as be

    profile = canonical(profile)
    n = len(profile)
    result = {
        "profile": [list(site) for site in profile],
        "score": [0.0] * n,
        "served_mw": [0.0] * n,
        "energy_cost": [0.0] * n,
        "site_cost": [0.0] * n,
        "generator_cost": [0.0] * n,
        "fraction": [0.0] * n,
        "scope": "empty",
        "dropped": 0,
        "common_level_mw": None,
    }
    if all(site[1] <= 0.0 for site in profile):
        return result
    saved = be._FAIR_PROJECTION_MIN_ALLOCATION_FRACTION
    if min_fraction is not None:
        be._FAIR_PROJECTION_MIN_ALLOCATION_FRACTION = min_fraction
    directory = Path(tempfile.mkdtemp(prefix="ne14_"))
    try:
        write_plans(profile, directory)
        evaluation = be.evaluate_csv_batch(
            directory,
            artifact_dir=ARTIFACT,
            horizon=HORIZON,
            rules=_rules(),
            submission_number=1,
            energy_cost_enabled=True,
        )
    finally:
        be._FAIR_PROJECTION_MIN_ALLOCATION_FRACTION = saved
        shutil.rmtree(directory, ignore_errors=True)
    by_team = {score.team_id: score for score in evaluation.team_scores}
    for index, team_id in enumerate(TEAM_IDS[:n]):
        score = by_team.get(team_id)
        if score is None:
            continue
        result["score"][index] = float(score.score)
        result["served_mw"][index] = float(score.served_load_mwh) / ANNUAL_HOURS
        result["energy_cost"][index] = float(score.energy_cost)
        result["site_cost"][index] = float(score.site_cost)
        result["generator_cost"][index] = float(
            score.generator_operating_cost + score.generator_capital_cost
        )
        result["fraction"][index] = 1.0 if profile[index][1] > 0 else 0.0
    result["scope"] = str(evaluation.competition_scope)
    diag = evaluation.projection_diagnostics
    if diag is not None:
        for index, team_id in enumerate(TEAM_IDS[:n]):
            if team_id in diag.service_fraction_by_team:
                result["fraction"][index] = float(diag.service_fraction_by_team[team_id])
        result["dropped"] = int(diag.cap_policy.get("dropped_team_count", 0))
        result["common_level_mw"] = float(diag.cap_policy.get("common_level_mw", 0.0))
    return result


def _worker(profile):
    return evaluate_profile(profile)


class Oracle:
    """Evaluator with an on-disk cache and a process pool."""

    def __init__(self, workers: int = 8, cache_name: str = "oracle_cache.jsonl"):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.path = CACHE_DIR / cache_name
        self.cache: dict[tuple, dict] = {}
        if self.path.is_file():
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        item = json.loads(line)
                        self.cache[canonical(item["profile"])] = item
        self.workers = workers
        self.pool = mp.get_context("spawn").Pool(workers) if workers > 1 else None
        self.calls = 0
        self.seconds = 0.0

    def close(self):
        if self.pool is not None:
            self.pool.close()
            self.pool.join()

    def many(self, profiles) -> list[dict]:
        keys = [canonical(profile) for profile in profiles]
        missing = list(dict.fromkeys(key for key in keys if key not in self.cache))
        if missing:
            start = time.time()
            if self.pool is not None and len(missing) > 1:
                results = self.pool.map(_worker, missing, chunksize=1)
            else:
                results = [_worker(key) for key in missing]
            self.seconds += time.time() - start
            self.calls += len(missing)
            with self.path.open("a", encoding="utf-8") as handle:
                for key, result in zip(missing, results):
                    self.cache[key] = result
                    handle.write(json.dumps(result) + "\n")
        return [self.cache[key] for key in keys]

    def one(self, profile) -> dict:
        return self.many([profile])[0]


# ---------------------------------------------------------------------------
# Exact feasible region H (LP over all 120 hours, constant team loads)
# ---------------------------------------------------------------------------


class Region:
    """DC power-flow feasibility of constant extra loads at given buses."""

    def __init__(self):
        def rows(name):
            with (ARTIFACT / name).open(newline="", encoding="utf-8") as handle:
                return list(csv.DictReader(handle))

        buses = [row["bus_id"] for row in rows("bus.csv")]
        self.buses = buses
        index = {bus: i for i, bus in enumerate(buses)}
        reference = next(row["bus_id"] for row in rows("bus.csv") if row["type"] == "3")
        branches = [row for row in rows("branch_limits.csv") if row["status"] == "1"]
        nb, nl = len(buses), len(branches)
        incidence = np.zeros((nl, nb))
        susceptance = np.zeros(nl)
        for k, row in enumerate(branches):
            incidence[k, index[row["from_bus_id"]]] = 1.0
            incidence[k, index[row["to_bus_id"]]] = -1.0
            susceptance[k] = 1.0 / float(row["reactance_pu"])
        bbus = incidence.T @ np.diag(susceptance) @ incidence
        keep = [i for i in range(nb) if buses[i] != reference]
        ptdf = np.zeros((nl, nb))
        ptdf[:, keep] = np.diag(susceptance) @ incidence[:, keep] @ np.linalg.inv(bbus[np.ix_(keep, keep)])
        self.ptdf = ptdf
        self.limit = np.array([float(row["thermal_limit_mva"]) for row in branches])
        self.branch_names = [f"{row['from_bus_id']}-{row['to_bus_id']}" for row in branches]
        gens = [row for row in rows("generator_limits.csv") if row["status"] == "1"]
        self.gen_bus = np.array([index[row["bus_id"]] for row in gens])
        self.gen_max = np.array([float(row["p_max_mw"]) for row in gens])
        self.gen_min = np.array([float(row["p_min_mw"]) for row in gens])
        demand = rows("demand_bus.csv")[:HORIZON]
        self.demand = np.array([[float(row[bus]) for bus in buses] for row in demand])
        self.index = index

    def _solve(self, sites, objective, *, fixed=None, equal_group=None, upper=None):
        """Maximize objective @ r over H.

        sites: bus of each team.  fixed: {team: MW}.  equal_group: teams
        forced to a common level t (t is the last variable).  Returns
        (r, value) or (None, None) when infeasible.
        """
        from scipy.optimize import linprog
        from scipy.sparse import csr_matrix, hstack, kron, identity, vstack

        n = len(sites)
        T, G = self.demand.shape[0], len(self.gen_bus)
        nb = len(self.buses)
        site_matrix = np.zeros((nb, n))
        for i, bus in enumerate(sites):
            site_matrix[self.index[str(bus)], i] = 1.0
        gen_matrix = np.zeros((nb, G))
        for g, b in enumerate(self.gen_bus):
            gen_matrix[b, g] = 1.0
        flow_gen = csr_matrix(self.ptdf @ gen_matrix)
        flow_site = self.ptdf @ site_matrix
        base_flow = self.demand @ self.ptdf.T  # T x nl, flow caused by demand (positive load)
        nvar = n + 1 + T * G
        # flows: ptdf (gen - demand - site r) within +-limit
        a_gen = kron(identity(T), flow_gen)
        a_site = csr_matrix(np.tile(-flow_site, (T, 1)))
        a_t = csr_matrix((a_site.shape[0], 1))
        a_flow = hstack([a_site, a_t, a_gen])
        rhs_hi = (self.limit[None, :] + base_flow).ravel()
        rhs_lo = (self.limit[None, :] - base_flow).ravel()
        a_ub = vstack([a_flow, -a_flow]).tocsr()
        b_ub = np.concatenate([rhs_hi, rhs_lo])
        # balance: sum gen - sum r = total demand
        a_bal = hstack([
            csr_matrix(-np.ones((T, n))),
            csr_matrix((T, 1)),
            kron(identity(T), csr_matrix(np.ones((1, G)))),
        ])
        b_bal = self.demand.sum(axis=1)
        eq_rows, eq_rhs = [a_bal], [b_bal]
        if equal_group:
            for i in equal_group:
                row = np.zeros((1, nvar))
                row[0, i] = 1.0
                row[0, n] = -1.0
                eq_rows.append(csr_matrix(row))
                eq_rhs.append(np.zeros(1))
        a_eq = vstack(eq_rows).tocsr()
        b_eq = np.concatenate(eq_rhs)
        bounds = []
        for i in range(n):
            if fixed and i in fixed:
                bounds.append((fixed[i], fixed[i]))
            else:
                bounds.append((0.0, None if upper is None else upper[i]))
        bounds.append((0.0, None))
        bounds.extend((self.gen_min[g], self.gen_max[g]) for _ in range(T) for g in range(G))
        c = np.zeros(nvar)
        c[: n + 1] = -np.asarray(objective, dtype=float)
        res = linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
        if res.status != 0:
            return None, None
        return res.x[:n].copy(), float(-res.fun)

    def feasible(self, sites, r) -> bool:
        x, _ = self._solve(sites, np.zeros(len(sites) + 1), fixed={i: float(v) for i, v in enumerate(r)})
        return x is not None

    def max_own(self, sites, r, i) -> float | None:
        """Largest r_i with the other requests fixed (None: others infeasible)."""
        fixed = {j: float(v) for j, v in enumerate(r) if j != i}
        objective = np.zeros(len(sites) + 1)
        objective[i] = 1.0
        x, value = self._solve(sites, objective, fixed=fixed)
        return None if x is None else value

    def max_total(self, sites):
        objective = np.ones(len(sites) + 1)
        objective[-1] = 0.0
        return self._solve(sites, objective)

    def maxmin_fair(self, sites, caps=None):
        """Water-filling (max-min fair) point of H for teams at `sites`."""
        n = len(sites)
        fixed: dict[int, float] = {}
        active = set(range(n))
        steps = []
        while active:
            objective = np.zeros(n + 1)
            objective[-1] = 1.0
            upper = None
            if caps is not None:
                upper = [caps[i] for i in range(n)]
            x, level = self._solve(sites, objective, fixed=fixed, equal_group=sorted(active), upper=upper)
            if x is None:
                raise RuntimeError("water-filling LP infeasible")
            r = [fixed.get(i, level) for i in range(n)]
            blocked = set()
            for i in active:
                own = self.max_own(sites, r, i)
                if own is not None and own <= level + 1e-6:
                    blocked.add(i)
                if caps is not None and level >= caps[i] - 1e-9:
                    blocked.add(i)
            steps.append({"level": level, "blocked": sorted(blocked)})
            if not blocked:
                raise RuntimeError("no blocked team in water-filling")
            for i in blocked:
                fixed[i] = level
            active -= blocked
        return [fixed[i] for i in range(n)], steps


def floor_to(value: float, step: float = 0.01) -> float:
    return math.floor(value / step + 1e-9) * step


# ---------------------------------------------------------------------------
# Helpers for best responses
# ---------------------------------------------------------------------------


def replace_site(profile, i, site):
    profile = list(profile)
    profile[i] = site
    return tuple(profile)


# "lmp": the real Submission-2 score.  "no_energy": the same evaluation with
# the energy purchase added back (= the Submission-1 score), a control that
# isolates the allocation rule from LMP effects.
PAYOFF_MODE = "lmp"


def pay(result, i, mode=None):
    mode = PAYOFF_MODE if mode is None else mode
    if mode == "no_energy":
        return result["score"][i] + result["energy_cost"][i]
    return result["score"][i]


def best_response(oracle, profile, i, candidates, keep_current=True):
    """Best site for team i among candidates (evaluator payoffs)."""
    profiles = [replace_site(profile, i, site) for site in candidates]
    results = oracle.many(profiles)
    payoffs = np.array([pay(result, i) for result in results])
    best = float(payoffs.max())
    current_key = canonical(profile)[i]
    if keep_current:
        for site, value in zip(candidates, payoffs):
            if canonical([site])[0] == current_key and value >= best - EPS:
                return site, value, payoffs, results
    k = int(payoffs.argmax())
    return candidates[k], float(payoffs[k]), payoffs, results


# ---------------------------------------------------------------------------
# Experiment 1: fixed buses, continuous requests
# ---------------------------------------------------------------------------

EXP1_CASES = {
    "a_13_14": ("13", "14"),
    "b_1_2": ("1", "2"),
    "c_9_13_14": ("9", "13", "14"),
}


def exp1(oracle, region, quick=False):
    summary = {}
    rows = []
    for name, sites in EXP1_CASES.items():
        if quick and name != "a_13_14":
            continue
        t0 = time.time()
        n = len(sites)
        alone = [region.max_own(sites, [0.0] * n, i) for i in range(n)]
        w_lp, steps = region.maxmin_fair(sites)
        w = [floor_to(v) for v in w_lp]
        # evaluator projection when everyone requests 1000 MW (real rule and
        # with the 50% minimum allocation switched off)
        big = tuple((bus, 1000.0) for bus in sites)
        proj_real = evaluate_profile(big)
        proj_nomin = evaluate_profile(big, min_fraction=0.0)
        moderate = tuple((bus, round(1.5 * wi, 2)) for bus, wi in zip(sites, w_lp))
        proj_moderate = oracle.one(moderate)
        at_w = oracle.one(tuple(zip(sites, w)))
        modes = {}
        for payoff_mode in ("lmp", "no_energy"):
            modes[payoff_mode] = _exp1_mode(oracle, region, sites, w, alone, name, rows, payoff_mode, quick)
        br_check = modes["lmp"]["best_response_check"]
        # planner optimum
        opt_lp, opt_total = region.max_total(sites)
        opt = [floor_to(v) for v in opt_lp]
        at_opt = oracle.one(tuple(zip(sites, opt)))
        boundary = []
        if n == 2:
            for x in np.linspace(0.0, alone[0], 81):
                boundary.append([float(x), region.max_own(sites, [float(x), 0.0], 1)])
        summary[name] = {
            "sites": sites,
            "alone_hosting_capacity_mw": alone,
            "w_lp_mw": w_lp,
            "w_mw": w,
            "water_filling_steps": steps,
            "evaluator_all_request_1000mw_real_rule": {k: proj_real[k] for k in ("served_mw", "score", "scope", "dropped", "fraction")},
            "evaluator_all_request_1000mw_no_minimum": {k: proj_nomin[k] for k in ("served_mw", "score", "scope", "dropped", "fraction", "common_level_mw")},
            "evaluator_all_request_1p5w_real_rule": {k: proj_moderate[k] for k in ("profile", "served_mw", "score", "scope", "dropped", "fraction")},
            "at_w": {k: at_w[k] for k in ("served_mw", "score", "energy_cost", "site_cost", "scope")},
            "at_w_avg_lmp_paid": [e / (s * WEIGHT_HOURS) if s else None for e, s in zip(at_w["energy_cost"], at_w["served_mw"])],
            "best_response_check": br_check,
            "modes": modes,
            "planner_lp_mw": list(opt_lp),
            "planner_total_mw_lp": opt_total,
            "planner_mw": opt,
            "at_planner": {k: at_opt[k] for k in ("served_mw", "score", "energy_cost", "scope")},
            "poa_served": sum(at_opt["served_mw"]) / sum(at_w["served_mw"]),
            "poa_welfare": sum(at_opt["score"]) / sum(at_w["score"]),
            "dynamics": modes["lmp"]["dynamics"],
            "boundary": boundary,
            "seconds": time.time() - t0,
        }
        print(f"[exp1 {name}] w={w} opt={opt} poa={summary[name]['poa_served']:.4f} "
              + " ".join(f"{m}: maxgain={[round(c['max_deviation_gain'], 1) for c in v['best_response_check']]} "
                         f"near_w={v['runs_ending_within_0.11mw_of_w']}/{len(v['dynamics'])} "
                         f"limits={v['distinct_limit_points']}" for m, v in modes.items())
              + f" {time.time() - t0:.0f}s", flush=True)
    write_json(OUT / "exp1_fixed_buses.json", summary)
    write_csv(OUT / "exp1_deviation_scan.csv", rows)
    return summary


def fine_check(oracle, region, sites, r, i, step, upper, mode):
    """Team i's payoff over a fine grid of own requests, others fixed at r."""
    grid = sorted(set(round(x, 4) for x in np.arange(0.0, upper + 1e-9, step))
                  | {round(r[i], 4)} | lp_candidates(region, sites, r, i))
    profile = tuple(zip(sites, r))
    results = oracle.many([replace_site(profile, i, (sites[i], x)) for x in grid])
    payoffs = np.array([pay(res, i, mode) for res in results])
    base = pay(oracle.one(profile), i, mode)
    k = int(payoffs.argmax())
    return grid, results, payoffs, {
        "team": TEAM_IDS[i], "bus": sites[i], "r_mw": r[i], "payoff_at_r": base,
        "best_grid_mw": grid[k], "best_grid_payoff": float(payoffs[k]),
        "max_deviation_gain": float(payoffs[k] - base),
        "relative_gain": float((payoffs[k] - base) / abs(base)) if base else None,
        "lp_residual_given_others": region.max_own(sites, r, i),
        "lp_secure_level": secure_level(region, sites, r, i),
        "grid_points": len(grid),
    }


def _exp1_mode(oracle, region, sites, w, alone, name, rows, payoff_mode, quick):
    global PAYOFF_MODE
    PAYOFF_MODE = payoff_mode
    n = len(sites)
    step = 0.5 if max(alone) < 200 else 1.0
    br_check = []
    for i in range(n):
        upper = max(1.3 * alone[i], w[i] + 20.0)
        grid, results, payoffs, check = fine_check(oracle, region, sites, w, i, step, upper, payoff_mode)
        check["w_mw"] = w[i]
        check["payoff_at_w"] = check["payoff_at_r"]
        br_check.append(check)
        if payoff_mode == "lmp":
            for r, res in zip(grid, results):
                rows.append({
                    "case": name, "team": TEAM_IDS[i], "bus": sites[i], "r_mw": r,
                    "score": res["score"][i], "score_no_energy": res["score"][i] + res["energy_cost"][i],
                    "served_mw": res["served_mw"][i], "energy_cost": res["energy_cost"][i],
                    "scope": res["scope"], "dropped": res["dropped"],
                })
    rng = random.Random(1000 + len(name))
    step_dyn = 1.0 if max(alone) < 200 else 10.0
    cand_sets = [sorted(set(round(x, 4) for x in np.arange(0.0, 1.3 * alone[i] + 1e-9, step_dyn))) for i in range(n)]
    starts = [[0.0] * n] + [[round(rng.uniform(0, 1.3 * alone[i]), 2) for i in range(n)] for _ in range(2 if quick else 5)]
    runs = []
    for mode in ("sequential", "simultaneous"):
        for s_index, start in enumerate(starts):
            run = br_dynamics_continuous(oracle, region, sites, start, cand_sets, mode, rng)
            run["start_index"] = s_index
            run["start"] = start
            runs.append(run)
    # fine-grid NE check at every distinct rest point of the dynamics
    limits = {}
    for run in runs:
        if run["converged"]:
            key = tuple(round(v, 4) for v in run["final"])
            if key not in limits:
                checks = [fine_check(oracle, region, sites, list(key), i, step,
                                     max(1.3 * alone[i], key[i] + 20.0), payoff_mode)[3] for i in range(n)]
                res = oracle.one(tuple(zip(sites, key)))
                limits[key] = {"r_mw": list(key), "checks": checks,
                               "max_gain": max(c["max_deviation_gain"] for c in checks),
                               "served_mw": res["served_mw"], "score": res["score"],
                               "energy_cost": res["energy_cost"], "scope": res["scope"],
                               "distance_to_w_mw": max(abs(a - b) for a, b in zip(key, w))}
    PAYOFF_MODE = "lmp"
    return {
        "best_response_check": br_check,
        "dynamics": runs,
        "limit_points": list(limits.values()),
        "distinct_limit_points": len(limits),
        "runs_converged": sum(1 for run in runs if run["converged"]),
        "runs_ending_within_0.11mw_of_w": sum(
            1 for run in runs if all(abs(a - b) <= 0.11 for a, b in zip(run["final"], w))),
    }


def br_dynamics_continuous(oracle, region, sites, start, cand_sets, mode, rng, max_rounds=30):
    n = len(sites)
    r = list(start)
    path = [list(r)]
    seen = {tuple(round(v, 4) for v in r): 0}
    converged = False
    cycle = None
    for round_index in range(1, max_rounds + 1):
        if mode == "sequential":
            order = list(range(n))
            rng.shuffle(order)
            changed = False
            for i in order:
                new = _br_continuous(oracle, region, sites, r, i, cand_sets[i])
                if abs(new - r[i]) > 1e-9:
                    r[i] = new
                    changed = True
                path.append(list(r))
        else:
            new = [_br_continuous(oracle, region, sites, r, i, cand_sets[i]) for i in range(n)]
            changed = any(abs(a - b) > 1e-9 for a, b in zip(new, r))
            r = new
            path.append(list(r))
        if not changed:
            converged = True
            break
        key = tuple(round(v, 4) for v in r)
        if key in seen:
            cycle = {"first_seen_round": seen[key], "repeat_round": round_index}
            break
        seen[key] = round_index
    final = oracle.one(tuple(zip(sites, r)))
    return {
        "mode": mode, "converged": converged, "rounds": round_index, "cycle": cycle,
        "final": r, "final_served": final["served_mw"], "final_scope": final["scope"],
        "path": path,
    }


def secure_level(region, sites, r, i):
    """MW team i is allocated by the uniform rule (no minimum) if it asks for
    an unlimited amount while the others keep their requests r_{-i}."""
    caps = [float(v) for v in r]
    caps[i] = 1e6
    allocation, _steps = region.maxmin_fair(sites, caps=caps)
    return allocation[i]


def lp_candidates(region, sites, r, i):
    """Candidate requests near the residual capacity and the secure level."""
    out = set()
    own = region.max_own(sites, r, i)
    if own is not None:
        base = floor_to(own)
        out.update(base + d for d in (-1.0, -0.5, -0.2, -0.1, -0.05, 0.0, 0.05, 0.5, 1.0))
    base = floor_to(secure_level(region, sites, r, i))
    out.update(base + d for d in (-0.5, -0.2, -0.15, -0.1, -0.05, -0.01, 0.0, 0.05, 0.5))
    return {round(v, 4) for v in out if v >= 0}


def _br_continuous(oracle, region, sites, r, i, grid):
    candidates = set(grid)
    candidates.update(lp_candidates(region, sites, r, i))
    candidates.add(round(r[i], 4))
    candidates = sorted(candidates)
    site, _value, _payoffs, _results = best_response(
        oracle, tuple(zip(sites, r)), i, [(sites[i], c) for c in candidates]
    )
    return float(site[1])


def exp1_epsilon(oracle, region, case="c_9_13_14", tail=6):
    """For runs that did not converge under LMP payoffs, the largest
    deviation gain (fine grid, every team) at the last states visited."""
    data = json.loads((OUT / "exp1_fixed_buses.json").read_text(encoding="utf-8"))[case]
    sites = tuple(data["sites"])
    alone = data["alone_hosting_capacity_mw"]
    n = len(sites)
    states = {}
    for run in data["modes"]["lmp"]["dynamics"]:
        if run["converged"]:
            continue
        for r in run["path"][-tail:]:
            states.setdefault(tuple(round(v, 4) for v in r), None)
    states[tuple(data["w_mw"])] = None
    out = []
    for key in states:
        checks = [fine_check(oracle, region, sites, list(key), i, 0.5,
                             max(1.3 * alone[i], key[i] + 20.0), "lmp")[3] for i in range(n)]
        res = oracle.one(tuple(zip(sites, key)))
        out.append({"r_mw": list(key), "max_gain": max(c["max_deviation_gain"] for c in checks),
                    "max_relative_gain": max(c["max_deviation_gain"] / abs(c["payoff_at_r"]) for c in checks if c["payoff_at_r"]),
                    "gains": [c["max_deviation_gain"] for c in checks],
                    "best_moves": [c["best_grid_mw"] for c in checks],
                    "score": res["score"], "energy_cost": res["energy_cost"], "served_mw": res["served_mw"],
                    "avg_lmp_paid": [e / (m * WEIGHT_HOURS) if m else None for e, m in zip(res["energy_cost"], res["served_mw"])],
                    "scope": res["scope"]})
        print(f"[exp1eps] {key} max gain {out[-1]['max_gain']:.0f} moves {out[-1]['best_moves']}", flush=True)
    out.sort(key=lambda item: item["max_gain"])
    write_json(OUT / "exp1_case_c_lmp_epsilon.json", {"case": case, "states": out})
    return out


def uniform_rule_gap(oracle, region, sites, r):
    """Largest |evaluator served MW - exact uniform-rule MW| (no minimum
    allocation) at profile r; flags the projection's early stop."""
    res = oracle.one(tuple(zip(sites, r)))
    exact, _steps = region.maxmin_fair(sites, caps=[float(v) for v in r])
    return max(abs(a - b) for a, b in zip(res["served_mw"], exact)), exact


def exp1_global(oracle, region, case="c_9_13_14", n_starts=4, max_rounds=40):
    """Global best-response search in case (c) with LMP payoffs: each team
    scans its whole request grid (0.5 MW at bus 9, 0.25 MW at 13/14, plus LP
    candidates) in randomized sequential order, from the lowest-epsilon
    states of exp 5 and from w.  A round with no change is an exact pure
    equilibrium on that grid."""
    global PAYOFF_MODE
    PAYOFF_MODE = "lmp"
    data = json.loads((OUT / "exp1_fixed_buses.json").read_text(encoding="utf-8"))[case]
    eps = json.loads((OUT / "exp1_case_c_lmp_epsilon.json").read_text(encoding="utf-8"))["states"]
    sites = tuple(data["sites"])
    alone = data["alone_hosting_capacity_mw"]
    w = data["w_mw"]
    n = len(sites)
    steps = [0.5 if a > 80 else 0.25 for a in alone]
    grids = [sorted(set(round(x, 4) for x in np.arange(0.0, 1.3 * a + 1e-9, st))) for a, st in zip(alone, steps)]
    starts = [list(w)] + [s["r_mw"] for s in eps if s["r_mw"] != list(w)][:n_starts]
    rng = random.Random(606)
    runs = []
    for start in starts:
        r = [float(v) for v in start]
        path = [list(r)]
        seen = {tuple(round(v, 4) for v in r): 0}
        converged, cycle = False, None
        for round_index in range(1, max_rounds + 1):
            order = list(range(n))
            rng.shuffle(order)
            changed = False
            for i in order:
                cands = sorted(set(grids[i]) | lp_candidates(region, sites, r, i) | {round(r[i], 4)})
                site, _value, _p, _res = best_response(oracle, tuple(zip(sites, r)), i, [(sites[i], c) for c in cands])
                if abs(site[1] - r[i]) > 1e-9:
                    r[i] = float(site[1])
                    changed = True
                    path.append(list(r))
            if not changed:
                converged = True
                break
            key = tuple(round(v, 4) for v in r)
            if key in seen:
                cycle = {"first_seen_round": seen[key], "repeat_round": round_index}
                break
            seen[key] = round_index
        res = oracle.one(tuple(zip(sites, r)))
        gap, exact = uniform_rule_gap(oracle, region, sites, r)
        # gains of each team at the final state over its global grid
        gains = []
        for i in range(n):
            cands = sorted(set(grids[i]) | lp_candidates(region, sites, r, i) | {round(r[i], 4)})
            _site, value, _p, _res = best_response(oracle, tuple(zip(sites, r)), i, [(sites[i], c) for c in cands])
            gains.append(value - res["score"][i])
        run = {"start": start, "final": r, "converged": converged, "cycle": cycle, "rounds": round_index,
               "moves": len(path) - 1, "path": path, "final_gains": gains,
               "final_max_relative_gain": max(g / abs(sc) for g, sc in zip(gains, res["score"]) if sc),
               "final_score": res["score"], "final_served_mw": res["served_mw"], "final_scope": res["scope"],
               "final_avg_lmp_paid": [e / (m * WEIGHT_HOURS) if m else None for e, m in zip(res["energy_cost"], res["served_mw"])],
               "final_uniform_rule_mw": exact, "final_evaluator_vs_uniform_rule_gap_mw": gap}
        runs.append(run)
        print(f"[exp6] start {start} -> {r} converged={converged} cycle={cycle} rounds={round_index} "
              f"gains={[round(g) for g in gains]} scope={res['scope']} gap={gap:.3f}", flush=True)
    write_json(OUT / "exp1_case_c_lmp_global.json", {"case": case, "grid_steps_mw": steps, "runs": runs})
    return runs


# ---------------------------------------------------------------------------
# Strategy grid with bus choice
# ---------------------------------------------------------------------------

GAME_BUSES = ("1", "2", "4", "9", "13", "14")


def strategy_grid(region, step=10.0, top=300.0, factor=1.3, buses=GAME_BUSES):
    hc = {bus: region.max_own((bus,), [0.0], 0) for bus in buses}
    strategies = [("0", 0.0)]
    for bus in buses:
        for mw in np.arange(step, top + 1e-9, step):
            if mw <= factor * hc[bus] + 1e-9:
                strategies.append((bus, float(mw)))
    return strategies, hc


def label(site):
    return "out" if site[1] <= 0 else f"{site[0]}:{site[1]:g}" + (f"+G{site[2]:g}" if len(site) > 2 and site[2] > 0 else "")


# ---------------------------------------------------------------------------
# Experiment 2: two teams with bus choice
# ---------------------------------------------------------------------------


def exp2(oracle, region, quick=False):
    t0 = time.time()
    step = 30.0 if quick else 10.0
    strategies, hc = strategy_grid(region, step=step)
    m = len(strategies)
    print(f"[exp2] {m} strategies, hosting capacities {hc}", flush=True)
    pairs = [(i, j) for i in range(m) for j in range(i, m)]
    results = oracle.many([(strategies[i], strategies[j]) for i, j in pairs])
    A = np.zeros((m, m))
    B = np.zeros((m, m))
    info = {}
    swapped_needed = []
    for (i, j), res in zip(pairs, results):
        A[i, j], B[i, j] = res["score"]
        info[(i, j)] = res
        if i != j:
            if res["dropped"] and strategies[i][1] == strategies[j][1]:
                swapped_needed.append((j, i))
            else:
                A[j, i], B[j, i] = res["score"][1], res["score"][0]
                info[(j, i)] = {**res, "score": res["score"][::-1], "served_mw": res["served_mw"][::-1],
                                "fraction": res["fraction"][::-1], "energy_cost": res["energy_cost"][::-1],
                                "profile": res["profile"][::-1]}
    for (i, j), res in zip(swapped_needed, oracle.many([(strategies[i], strategies[j]) for i, j in swapped_needed])):
        A[i, j], B[i, j] = res["score"]
        info[(i, j)] = res
    asym = float(np.abs(A - B.T).max())
    print(f"[exp2] matrix done ({len(pairs) + len(swapped_needed)} evaluations, "
          f"max |A - B^T| = {asym:.1f}) {time.time() - t0:.0f}s", flush=True)
    pure = pure_equilibria(A, B)
    pure_list = []
    for i, j in pure:
        res = info[(i, j)]
        pure_list.append({
            "team_a": label(strategies[i]), "team_b": label(strategies[j]),
            "score": [A[i, j], B[i, j]], "served_mw": res["served_mw"], "scope": res["scope"],
            "dropped": res["dropped"], "fraction": res["fraction"],
            "energy_cost": res["energy_cost"], "welfare": A[i, j] + B[i, j],
        })
    W = A + B
    k = np.unravel_index(int(W.argmax()), W.shape)
    planner_grid = {
        "team_a": label(strategies[k[0]]), "team_b": label(strategies[k[1]]),
        "welfare": float(W[k]), "served_mw": info[k]["served_mw"], "scope": info[k]["scope"],
    }
    planner_cont = planner_continuous(oracle, region, 2)
    np.savez_compressed(OUT / "exp2_payoff_matrix.npz", A=A, B=B, strategies=np.array([label(s) for s in strategies]))
    mixed = mixed_equilibria(A, B, strategies, quick=quick)
    # fairness at pure NE
    for item in pure_list:
        s = item["served_mw"]
        item["jain_served"] = (sum(s) ** 2) / (len(s) * sum(x * x for x in s)) if sum(s) > 0 else None
    summary = {
        "strategies": [label(s) for s in strategies],
        "n_strategies": m,
        "hosting_capacity_alone_mw": hc,
        "grid_step_mw": step,
        "max_abs_A_minus_Bt": asym,
        "pure_equilibria": pure_list,
        "planner_on_grid": planner_grid,
        "planner_continuous": planner_cont,
        "poa_welfare_grid": [planner_grid["welfare"] / item["welfare"] for item in pure_list],
        "mixed": mixed,
        "seconds": time.time() - t0,
    }
    np.savez_compressed(OUT / "exp2_payoff_matrix.npz", A=A, B=B, strategies=np.array([label(s) for s in strategies]))
    rows = []
    for (i, j), res in sorted(info.items()):
        rows.append({
            "team_a": label(strategies[i]), "team_b": label(strategies[j]),
            "score_a": res["score"][0], "score_b": res["score"][1],
            "served_a": res["served_mw"][0], "served_b": res["served_mw"][1],
            "scope": res["scope"], "dropped": res["dropped"],
        })
    write_csv(OUT / "exp2_payoff_matrix.csv", rows)
    write_json(OUT / "exp2_two_team.json", summary)
    print(f"[exp2] pure NE: {[(p['team_a'], p['team_b'], [round(x) for x in p['score']]) for p in pure_list]}", flush=True)
    print(f"[exp2] planner grid: {planner_grid}", flush=True)
    return summary, strategies, A, B


def pure_equilibria(A, B):
    col_best = A.max(axis=0)
    row_best = B.max(axis=1)
    out = []
    for i in range(A.shape[0]):
        for j in range(A.shape[1]):
            if A[i, j] >= col_best[j] - EPS and B[i, j] >= row_best[i] - EPS:
                out.append((i, j))
    return out


LH_TIMEOUT_SECONDS = 600.0


def _lemke_howson(a, b, lab):
    import nashpy as nash

    try:
        with np.errstate(all="ignore"):
            return tuple(np.asarray(x) for x in nash.Game(a, b).lemke_howson(initial_dropped_label=lab))
    except Exception:
        return None


def mixed_equilibria(A, B, strategies, quick=False):
    import nashpy as nash

    scale = 1e6
    a = A / scale
    b = B / scale
    game = nash.Game(a, b)
    m, n = a.shape
    found = []
    failures = 0
    labels = list(range(m + n)) if not quick else list(range(0, m + n, max(1, (m + n) // 10)))
    # Lemke-Howson can cycle on degenerate games (nashpy has no iteration
    # cap), so each label runs in a worker with a time limit.
    timeouts = 0
    ctx = mp.get_context("fork" if sys.platform.startswith("linux") else "spawn")
    pool = ctx.Pool(min(len(labels), max(1, (mp.cpu_count() or 2) // 4)))
    pending = {lab: pool.apply_async(_lemke_howson, (a, b, lab)) for lab in labels}
    deadline = time.time() + LH_TIMEOUT_SECONDS
    outcomes = {}
    for lab, job in pending.items():
        try:
            outcomes[lab] = job.get(timeout=max(0.1, deadline - time.time()))
        except mp.TimeoutError:
            outcomes[lab] = "timeout"
    pool.terminate()
    for lab in labels:
        outcome = outcomes[lab]
        if outcome == "timeout":
            timeouts += 1
            failures += 1
            continue
        if outcome is None:
            failures += 1
            continue
        sigma_r, sigma_c = outcome
        if sigma_r is None or not np.all(np.isfinite(sigma_r)) or not np.all(np.isfinite(sigma_c)) \
                or abs(sigma_r.sum() - 1) > 1e-6 or abs(sigma_c.sum() - 1) > 1e-6 \
                or sigma_r.min() < -1e-9 or sigma_c.min() < -1e-9:
            failures += 1
            continue
        # verify equilibrium
        ur = a @ sigma_c
        uc = sigma_r @ b
        regret = max(float(ur.max() - sigma_r @ ur), float(uc.max() - uc @ sigma_c)) * scale
        sig = (tuple(np.round(sigma_r, 6)), tuple(np.round(sigma_c, 6)))
        if regret > 10.0 * EPS:
            failures += 1
            continue
        if sig not in [item["key"] for item in found]:
            found.append({"key": sig, "label": lab, "regret": regret})
    mixed = []
    for item in found:
        sr, sc = (np.array(x) for x in item["key"])
        support_r = [(label(strategies[k]), float(sr[k])) for k in np.nonzero(sr > 1e-9)[0]]
        support_c = [(label(strategies[k]), float(sc[k])) for k in np.nonzero(sc > 1e-9)[0]]
        mixed.append({
            "team_a": support_r, "team_b": support_c,
            "pure": len(support_r) == 1 and len(support_c) == 1,
            "expected_score": [float(sr @ A @ sc), float(sr @ B @ sc)],
            "regret": item["regret"], "first_label": item["label"],
        })
    # asymmetric replicator dynamics and fictitious play
    rng = np.random.default_rng(7)
    replicator = []
    timepoints = np.linspace(0, 400, 2001)
    shift_a = a - a.min() + 1e-3
    shift_b = b - b.min() + 1e-3
    for trial in range(2 if quick else 6):
        x0 = rng.dirichlet(np.ones(m))
        y0 = rng.dirichlet(np.ones(n))
        try:
            xs, ys = nash.Game(shift_a, shift_b).asymmetric_replicator_dynamics(x0=x0, y0=y0, timepoints=timepoints)
            x, y = xs[-1], ys[-1]
            replicator.append({
                "trial": trial,
                "team_a_top": [(label(strategies[k]), float(x[k])) for k in np.argsort(-x)[:3]],
                "team_b_top": [(label(strategies[k]), float(y[k])) for k in np.argsort(-y)[:3]],
            })
        except Exception as exc:  # pragma: no cover - diagnostic only
            replicator.append({"trial": trial, "error": str(exc)})
    fp = []
    for trial in range(2 if quick else 4):
        np.random.seed(trial)
        counts = None
        for counts in game.fictitious_play(iterations=3000 if not quick else 300):
            pass
        cr, cc = counts
        pr, pc = cr / cr.sum(), cc / cc.sum()
        ur = a @ pc
        uc = pr @ b
        fp.append({
            "trial": trial,
            "team_a_top": [(label(strategies[k]), float(pr[k])) for k in np.argsort(-pr)[:3]],
            "team_b_top": [(label(strategies[k]), float(pc[k])) for k in np.argsort(-pc)[:3]],
            "empirical_regret": max(float(ur.max() - pr @ ur), float(uc.max() - uc @ pc)) * scale,
        })
    return {
        "lemke_howson_labels_tried": len(list(labels)),
        "lemke_howson_failures": failures,
        "lemke_howson_timeouts": timeouts,
        "lemke_howson_time_limit_seconds_total": LH_TIMEOUT_SECONDS,
        "distinct_equilibria": mixed,
        "replicator": replicator,
        "fictitious_play": fp,
    }


def planner_continuous(oracle, region, n, buses=GAME_BUSES):
    best = None
    for combo in itertools.combinations_with_replacement(buses, n):
        r, total = region.max_total(combo)
        if r is None:
            continue
        if best is None or total > best[1] + 1e-6:
            best = (combo, total, list(r))
    combo, total, r = best
    floored = [floor_to(v) for v in r]
    # keep only teams with load
    res = oracle.one(tuple(zip(combo, floored)))
    return {"buses": list(combo), "lp_mw": r, "lp_total_mw": total, "mw": floored,
            "served_mw": res["served_mw"], "score": res["score"], "welfare": sum(res["score"]),
            "scope": res["scope"]}


# ---------------------------------------------------------------------------
# Experiment 3: three and four teams, best-response dynamics on the grid
# ---------------------------------------------------------------------------


def exp3(oracle, region, quick=False, team_counts=(3, 4)):
    t0 = time.time()
    step = 30.0 if quick else 10.0
    strategies, hc = strategy_grid(region, step=step)
    summary = {"n_strategies": len(strategies), "grid_step_mw": step}
    for n in team_counts:
        rng = random.Random(100 + n)
        runs = []
        n_starts = 2 if quick else 6
        for s in range(n_starts):
            start = tuple(rng.choice(strategies) for _ in range(n)) if s > 0 else tuple(strategies[0] for _ in range(n))
            runs.append(br_dynamics_grid(oracle, strategies, start, rng))
            print(f"[exp3 n={n} start {s}] converged={runs[-1]['converged']} rounds={runs[-1]['rounds']} "
                  f"final={[label(x) for x in runs[-1]['final']]} welfare={runs[-1]['final_welfare']:.0f} "
                  f"{time.time() - t0:.0f}s", flush=True)
        planner = planner_continuous(oracle, region, n)
        for run in runs:
            run["poa_vs_continuous_planner"] = planner["welfare"] / run["final_welfare"] if run["final_welfare"] > 0 else None
        distinct = {}
        for run in runs:
            if run["converged"] and run["is_exact_ne"]:
                key = tuple(sorted(label(x) for x in run["final"]))
                distinct.setdefault(key, run["final_welfare"])
        summary[f"n{n}"] = {
            "runs": runs, "planner_continuous": planner,
            "distinct_equilibria_up_to_relabeling": [{"sites": list(k), "welfare": v} for k, v in distinct.items()],
        }
    summary["seconds"] = time.time() - t0
    write_json(OUT / "exp3_multi_team.json", summary)
    return summary


def br_dynamics_grid(oracle, strategies, start, rng, max_rounds=25):
    n = len(start)
    profile = tuple(start)
    path = [{"profile": [label(s) for s in profile], **_profile_stats(oracle.one(profile))}]
    seen = {canonical(profile): 0}
    converged = False
    cycle = None
    drops_in_scans = 0
    scans = 0
    for round_index in range(1, max_rounds + 1):
        order = list(range(n))
        rng.shuffle(order)
        changed = False
        for i in order:
            site, value, payoffs, results = best_response(oracle, profile, i, strategies)
            scans += 1
            drops_in_scans += sum(1 for res in results if res["dropped"])
            if canonical([site])[0] != canonical(profile)[i]:
                profile = replace_site(profile, i, site)
                changed = True
                path.append({"mover": TEAM_IDS[i], "profile": [label(s) for s in profile],
                             **_profile_stats(oracle.one(profile))})
        if not changed:
            converged = True
            break
        key = canonical(profile)
        if key in seen:
            cycle = {"first_seen_round": seen[key], "repeat_round": round_index}
            break
        seen[key] = round_index
    final = oracle.one(profile)
    # exact NE check: each team's full scan
    gains = []
    for i in range(n):
        _site, value, _p, _r = best_response(oracle, profile, i, strategies)
        gains.append(value - final["score"][i])
    return {
        "start": [label(s) for s in start], "final": [list(s) for s in profile],
        "final_labels": [label(s) for s in profile],
        "converged": converged, "cycle": cycle, "rounds": round_index,
        "is_exact_ne": max(gains) <= EPS, "max_deviation_gain": max(gains),
        "final_score": final["score"], "final_served_mw": final["served_mw"],
        "final_welfare": sum(final["score"]), "final_scope": final["scope"], "final_dropped": final["dropped"],
        "path": path, "drop_events_in_path": sum(1 for p in path if p["dropped"]),
        "scan_evaluations": scans * len(strategies), "scan_evaluations_with_drop": drops_in_scans,
    }


def _profile_stats(res):
    return {"score": res["score"], "served_mw": res["served_mw"], "welfare": sum(res["score"]),
            "scope": res["scope"], "dropped": res["dropped"]}


# ---------------------------------------------------------------------------
# Experiment 4: generator option in the two-team game
# ---------------------------------------------------------------------------


def exp4(oracle, region, exp2_summary, strategies, quick=False):
    t0 = time.time()
    # A generator of G = 0.5 r lifts the limit to HC + G, so a site can reach
    # 2 HC: widen the size grid (exp 2 stops at 300 MW and 1.3 HC).
    wide, _hc = strategy_grid(region, step=30.0 if quick else 10.0, top=1000.0, factor=2.6)
    strategies = sorted(set(strategies) | set(wide), key=lambda s: (s[0], s[1]))
    extended = [(s[0], s[1], 0.0) for s in strategies]
    for s in strategies:
        if s[1] > 0:
            extended.extend([(s[0], s[1], 0.25 * s[1]), (s[0], s[1], 0.5 * s[1])])
    checks = []
    for item in exp2_summary["pure_equilibria"]:
        prof = tuple(_parse_label(item[key]) for key in ("team_a", "team_b"))
        base = oracle.one(prof)
        gains = []
        best_sites = []
        for i in range(2):
            site, value, _p, _r = best_response(oracle, prof, i, extended)
            gains.append(value - base["score"][i])
            best_sites.append(label(site))
        checks.append({"profile": [item["team_a"], item["team_b"]], "max_gain_with_generator": gains,
                       "best_response": best_sites, "still_ne": max(gains) <= EPS})
        print(f"[exp4] NE {item['team_a']},{item['team_b']}: gains {gains} BR {best_sites}", flush=True)
    rng = random.Random(44)
    runs = []
    for s in range(2 if quick else 4):
        start = tuple(rng.choice(extended) for _ in range(2)) if s > 0 else (extended[0], extended[0])
        runs.append(br_dynamics_grid(oracle, extended, start, rng))
        print(f"[exp4 start {s}] converged={runs[-1]['converged']} final={runs[-1]['final_labels']} "
              f"welfare={runs[-1]['final_welfare']:.0f}", flush=True)
    summary = {"n_strategies": len(extended), "ne_checks": checks, "runs": runs, "seconds": time.time() - t0}
    write_json(OUT / "exp4_generator.json", summary)
    return summary


def _parse_label(text):
    if text == "out":
        return ("0", 0.0, 0.0)
    gen = 0.0
    if "+G" in text:
        text, g = text.split("+G")
        gen = float(g)
    bus, mw = text.split(":")
    return (bus, float(mw), gen)


# ---------------------------------------------------------------------------
# CLI validation against ercot-game-batch run
# ---------------------------------------------------------------------------


def validate_cli(oracle, profile):
    from ercot_game import batch_cli

    directory = Path(tempfile.mkdtemp(prefix="ne14_cli_"))
    plans = directory / "plans"
    plans.mkdir()
    write_plans(profile, plans)
    code = batch_cli.main([
        "run", "--submissions-dir", str(plans), "--artifact-dir", str(ARTIFACT),
        "--rules", str(RULES), "--output-dir", str(directory / "out"),
        "--week", "3", "--submission-number", "1",
    ])
    evaluation = json.loads((directory / "out" / "evaluation.json").read_text(encoding="utf-8"))
    cli = {s["team_id"]: s["score"] for s in evaluation["team_scores"]}
    mine = oracle.one(profile)
    diff = max(abs(cli[t] - mine["score"][k]) for k, t in enumerate(TEAM_IDS[: len(profile)]) if t in cli)
    shutil.rmtree(directory, ignore_errors=True)
    return {"profile": [list(p) for p in canonical(profile)], "cli_exit": code, "cli_scores": cli,
            "oracle_scores": mine["score"], "max_abs_diff": diff, "cli_scope": evaluation.get("competition_scope")}


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=1) + "\n", encoding="utf-8")


def write_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="coarse grids and few starts (smoke test)")
    parser.add_argument("--exp", type=int, nargs="*", default=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--figures-only", action="store_true")
    parser.add_argument("--cache-name", default="oracle_cache.jsonl",
                        help="cache file under work/game_equilibrium_cache (one per concurrent run)")
    args = parser.parse_args(argv)
    global OUT
    if args.quick:
        OUT = OUT / "quick"
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.figures_only:
        start = time.time()
        oracle = Oracle(workers=args.workers, cache_name=args.cache_name)
        region = Region()
        meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "quick": args.quick, "workers": args.workers,
                "margin_per_served_mw_before_energy": MARGIN_PER_MW, "it_value_per_mwh": IT_VALUE,
                "site_cost_per_mw": SITE_COST}
        meta["cli_validation"] = [
            validate_cli(oracle, (("13", 20.0), ("14", 20.0))),
            validate_cli(oracle, (("13", 40.0), ("14", 30.0))),
        ]
        print("[cli]", meta["cli_validation"], flush=True)
        results = {}
        if 1 in args.exp:
            results[1] = exp1(oracle, region, quick=args.quick)
        exp2_out = None
        if 2 in args.exp or 4 in args.exp:
            exp2_out = exp2(oracle, region, quick=args.quick)
        if 3 in args.exp:
            exp3(oracle, region, quick=args.quick)
        if 5 in args.exp:
            exp1_epsilon(oracle, region)
        if 6 in args.exp:
            exp1_global(oracle, region)
        if 4 in args.exp and exp2_out is not None:
            exp4(oracle, region, exp2_out[0], exp2_out[1], quick=args.quick)
        meta["seconds"] = time.time() - start
        meta["oracle_new_evaluations"] = oracle.calls
        meta["oracle_seconds"] = oracle.seconds
        old = {}
        meta_path = OUT / "run_meta.json"
        if meta_path.is_file():
            old = json.loads(meta_path.read_text(encoding="utf-8"))
        old[f"run_exp_{'_'.join(map(str, args.exp))}"] = meta
        write_json(meta_path, old)
        oracle.close()
    import importlib.util

    spec = importlib.util.spec_from_file_location("ne_figs", Path(__file__).with_name("game_equilibrium_figures.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.make_all(OUT, FIG if not args.quick else OUT)


if __name__ == "__main__":
    main()
