"""Two-team example under the uniform rule (max-min level, then fill slack)."""
import json, sys
from tools.activsg2000.dcopf import DCOPFInfeasible, DCOPFUnresolved, solve_prepared_period

PERIOD = int(sys.argv[1]); BLOCK = sys.argv[2]
A, B = "1002", "1010"
TOL = 0.05

def ok(la, lb):
    try:
        solve_prepared_period(BLOCK, period_index=PERIOD, additional_demand_mw_by_bus={A: la, B: lb})
        return True
    except (DCOPFInfeasible, DCOPFUnresolved):
        return False

def bisect(pred, lo, hi):
    if pred(hi): return hi
    while hi - lo > TOL:
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pred(mid) else (lo, mid)
    return lo

def uniform(ra, rb):
    if ok(ra, rb):
        return ra, rb, "feasible"
    t = bisect(lambda t: ok(min(ra, t), min(rb, t)), 0.0, max(ra, rb))
    sa, sb = min(ra, t), min(rb, t)
    # fill slack: raise each team still below its request, others fixed
    if sa < ra:
        sa = bisect(lambda x: ok(x, sb), sa, ra)
    if sb < rb:
        sb = bisect(lambda x: ok(sa, x), sb, rb)
    return sa, sb, f"level t={t:.2f}"

V = 4368 * 6500 + 4416 * (6500 - 18)   # $ per served MW over a week, built in Submission 1
out = {}
for ra in (50, 100):
    for rb in (50, 100):
        sa, sb, how = uniform(ra, rb)
        pa = (V * sa - 25e6 * ra) / 1e6; pb = (V * sb - 25e6 * rb) / 1e6
        out[f"{ra},{rb}"] = {"served": [sa, sb], "how": how, "payoff_musd": [pa, pb]}
        print(ra, rb, how, f"served A={sa:.2f} B={sb:.2f}", f"payoff A={pa:,.0f} B={pb:,.0f}", flush=True)
json.dump({"period": PERIOD, "rule": "uniform (max-min level, then fill slack)", "game": out},
          open(f"outputs/uniform_two_team_p{PERIOD}.json", "w"), indent=1)
