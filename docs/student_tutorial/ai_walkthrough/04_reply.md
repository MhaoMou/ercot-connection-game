The plan is saved as `runs/demo/plan.csv` and passes the checker. The copy with a generator larger than its connection fails, and the checker names the row and the limit.

I sized each site at about half of its bus's minimum hosting capacity: 235 MW at bus 1 (half of 470.7) and 214 MW at bus 2 (half of 428.8), with no generator or battery.

```bash
mkdir -p runs/demo
cat > runs/demo/plan.csv <<'EOF'
team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh
team-demo,site-bus1,1,235,0,0,0
team-demo,site-bus2,2,214,0,0,0
EOF
ercot-game-check-csv --file runs/demo/plan.csv --artifact-dir data/teaching/ieee14_demo_representative
```
```
VALID: runs/demo/plan.csv
team=team-demo sites=2 rows=2 buses=2 generators=0 storage=0 horizon=None
```
The exit code was 0.

**Copy with the mistake:** in `runs/demo/plan_bad.csv`, site-bus1 gets a 300 MW generator on its 235 MW connection.
```bash
sed 's/site-bus1,1,235,0/site-bus1,1,235,300/' runs/demo/plan.csv > runs/demo/plan_bad.csv
ercot-game-check-csv --file runs/demo/plan_bad.csv --artifact-dir data/teaching/ieee14_demo_representative
```
```
INVALID: runs/demo/plan_bad.csv
- row 2: generator capacity cannot exceed 0.5 x connection capacity (300 MW > 117.5 MW)
```
The exit code was 1.

The checker's limit is stricter than "no bigger than the connection": a generator can be at most half the connection capacity, which is 117.5 MW for this site. That is the G ≤ 0.5C rule from Part I. A file like this one would score 0, so check every file you upload with `--artifact-dir`.

These are the only files I created, both in `runs/demo/`.
