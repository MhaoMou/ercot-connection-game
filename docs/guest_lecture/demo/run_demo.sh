#!/usr/bin/env bash
# Live demo for the guest lecture. Run from the repository root with the
# project installed (python -m pip install -e .). Each step takes seconds.
set -euo pipefail
BLOCK=data/processed/activsg2000_representative_v1
OUT=${OUT:-work/lecture_demo}
BACKEND=${BACKEND:-auto}   # auto picks Gurobi when available, else HiGHS
PY=${PYTHON:-python3}
export PYTHONPATH="src:.${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$OUT"

# Representative day 4 (periods 96-119) is the peak day, 2028-09-15; period
# 109 (13:00) is the peak hour (hour 1837 of the hourly July-December block).
echo "== 1. Hosting capacity of buses 1002, 1010, 7419 around the peak hour (periods 106-111)"
"$PY" -m ercot_game.hosting_capacity_cli \
  --artifact-dir "$BLOCK" \
  --start-period 106 --period-count 6 \
  --bus-id 1002 --bus-id 1010 --bus-id 7419 \
  --solver-backend "$BACKEND" \
  --output-dir "$OUT/hc" --write-long-form
"$PY" - "$OUT/hc/hosting_capacity_long.csv.gz" <<'PY'
import csv, gzip, sys
rows = list(csv.DictReader(gzip.open(sys.argv[1], "rt")))
periods = sorted({int(r["period_index"]) for r in rows})
print("bus   " + "".join(f"{p:>10}" for p in periods) + "    min")
for bus in sorted({r["bus_id"] for r in rows}):
    hc = {int(r["period_index"]): float(r["hosting_capacity_mw"]) for r in rows if r["bus_id"] == bus}
    print(f"{bus:<6}" + "".join(f"{hc[p]:>10.1f}" for p in periods) + f"{min(hc.values()):>7.1f}")
PY

echo "== 2. A two-site plan, checked against the package"
cat > "$OUT/team-demo.csv" <<'CSV'
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
team-demo,site-a,7419,250,0,50,200
team-demo,site-b,1002,100,0,0,0
CSV
"$PY" -m ercot_game.csv_validator --file "$OUT/team-demo.csv" --artifact-dir "$BLOCK"

echo "== 3. Grid map of the eight-team example: open in a browser"
echo "docs/guest_lecture/figures/grid_map.svg"
