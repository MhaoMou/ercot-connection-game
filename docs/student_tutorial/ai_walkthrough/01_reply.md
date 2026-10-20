I read `README.md` and Part I of `docs/student_tutorial/main.tex`, then ran the checker once on an example file. I didn't change anything.

**What you submit:** one CSV per team per submission. There are two submissions a week for three weeks, so six files, and no report. Each file has exactly this header, with one row per site:
`team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh`
Generator capacity can't exceed connection capacity, and storage energy must be either 0 or 4× storage power. In Submission 2, keep every Submission 1 row unchanged and only add new sites.

**How it's scored:** score = IT value ($6,500/MWh served) − energy cost (at the local price, Submission 2 only) − generator running cost − one-time capital: $25M/MW per site, $1.5M/MW per generator, $400k/MW + $250k/MWh per battery. All teams' plans run on the grid together. If they don't fit, everyone gets the same MW level, and a team that would get less than half of its request gets nothing. Week 1 is practice. Your final score is the sum of the four Week 2–3 submissions. An invalid file scores 0.

**Commands** (in `.venv/`):
```
ercot-game-check-csv --file plan.csv --artifact-dir data/processed/activsg2000_scenarios_v2_6h/<year>/<jan_jun|jul_dec>
ercot-game-preview --submissions-dir runs/a --artifact-dir ... --rules data/teaching/dispatch_scoring_rules_<half>_6h_v1.json --horizon <724|728|736> --output runs/a.json
```
Test run: `ercot-game-check-csv --file examples/eight_team_round/submissions/team-01.csv` printed `VALID ... sites=2` (exit 0).
