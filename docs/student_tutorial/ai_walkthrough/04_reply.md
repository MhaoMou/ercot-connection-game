The plan is saved as `runs/demo/plan.csv` and the checker accepts it. The broken copy, with a generator larger than its connection, is rejected.

```
mkdir -p runs/demo runs/demo_bad
cat > runs/demo/plan.csv <<'EOF' ... EOF
sed 's/^team-demo,site-bus2,2,220,0,/team-demo,site-bus2,2,220,250,/' runs/demo/plan.csv > runs/demo_bad/plan_bad.csv
.venv/bin/ercot-game-check-csv --file runs/demo/plan.csv --artifact-dir data/teaching/ieee14_demo_1h
.venv/bin/ercot-game-check-csv --file runs/demo_bad/plan_bad.csv --artifact-dir data/teaching/ieee14_demo_1h
```

**`runs/demo/plan.csv`** has about half of each bus's minimum hosting capacity (bus 1: 484.7 → 240 MW, bus 2: 440.6 → 220 MW). There are no generators or batteries.
```
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
team-demo,site-bus1,1,240,0,0,0
team-demo,site-bus2,2,220,0,0,0
```
Checker output:
```
VALID: runs/demo/plan.csv
team=team-demo sites=2 rows=2 buses=2 generators=0 storage=0 horizon=None
exit=0
```

**Broken copy `runs/demo_bad/plan_bad.csv`:** the bus-2 site now has a 250 MW generator on a 220 MW connection.
```
team-demo,site-bus2,2,220,250,0,0
```
Checker output:
```
INVALID: runs/demo_bad/plan_bad.csv
- row 3: generator capacity cannot exceed connection capacity
Expected header: team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
Example row: team-a,site-north,1001,40,20,10,40
exit=1
```
Row 3 means the second data row, because the header counts as row 1. In the real game, a file like this would score 0.

I put the broken copy in its own folder on purpose. The preview tool runs every CSV in a folder together, so keeping it out of `runs/demo/` stops it from being mixed in.

**Caveat:** "valid" only means the file is well-formed. It says nothing about whether the grid can serve the load. Buses 1 and 2 share network capacity, so their hosting capacities don't add up. Also, 460 MW of new load plus the 288 MW peak is about 748 MW, against only 772.4 MW of total generation. Running `ercot-game-preview` on `runs/demo` with `--preview-stride 1` would show how much of this plan is actually served.
