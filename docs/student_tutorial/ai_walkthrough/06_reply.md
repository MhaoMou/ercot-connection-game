With an identical rival, each team gets **52.4% service** and the score falls from $15.6B to **$2.8B per team**. That is just above the 50% line below which a team gets nothing.

I made the rival's file by copying our plan and changing only `team_id`, then ran the official joint evaluator on both files for Week 3 with the demo rules.

```bash
mkdir -p runs/demo/joint
cp runs/demo/plan.csv runs/demo/joint/team-demo.csv
sed 's/team-demo/team-rival/' runs/demo/plan.csv > runs/demo/joint/team-rival.csv
ercot-game-batch run --submissions-dir runs/demo/joint \
  --artifact-dir data/teaching/ieee14_demo_representative \
  --rules data/teaching/dispatch_scoring_rules_ieee14_demo_representative_v1.json \
  --week 3 --output-dir runs/demo/joint_week3
# summary: 2 teams scored, 0 rejected, scope=joint_projection
```

`evaluation.json` reports `DCOPF physically infeasible`. Together the two teams ask for 898 MW, and the grid cannot carry that, so the fair projection was used:

| | team-demo | team-rival |
|---|---|---|
| Requested | 449 MW | 449 MW |
| Served (common level) | 235.3 MW | 235.3 MW |
| **Service fraction** | **52.4%** | **52.4%** |
| IT value | $14.48B | $14.48B |
| Energy cost | $0.43B | $0.43B |
| Site cost | $11.23B | $11.23B |
| **Score** | **$2.82B** | **$2.82B** |

The two teams have identical scores. The leaderboard's ranks 1 and 2 are just tie order.

**What it means for our plan:**
- Site cost is charged on the 449 MW we request, served or not. So the score drops from about $15.6B alone to $2.8B, even though about half the load is still served.
- We are only 2.4 points above the 50% cutoff. A third team copying the same table would likely push both of us under it: zero IT value, but the full $11.2B site cost, for a score of about −$11B.
- Half of hosting capacity is safe only if nobody else builds there. Smaller sites, or a spread to buses 4 and 5, are much more robust to copying.

**Assumptions to check yourself:**
1. **Rules:** I trusted Part I of the tutorial over the README, whose numbers ($6,500/MWh, six-hour package) look out of date. Check the course's current rules.
2. **Rules file:** I used the demo scoring rules (`dispatch_scoring_rules_ieee14_demo_representative_v1.json`). I didn't check that they match the real game's rules, and nothing here applies to the ACTIVSg2000 network.
3. **Bus columns:** I mapped the columns of `hosting_capacity_mw.npy` to buses using the string-sorted `bus_ids` list in its metadata file. A wrong mapping would change the whole table and the shortlist.
4. **Hosting-capacity scope:** the numbers are for one bus at a time with no other new load, and they don't add up. I shortlisted on the minimum over all hours.
5. **Sizes:** "about half" became 235 and 214 MW, rounded by me.
6. **Served share:** in the preview, I read 100% service from served_load_mwh = 449 × 8,760. The preview doesn't run batteries and is not official.
7. **Week 3 setting:** I assumed `--week 3` turns on LMP energy cost in both tools. The outputs show energy cost on, but the README's batch example uses other flags.
8. **Submission number:** both runs used the default submission number. I didn't model Submission 1 to Submission 2 carry-over.
9. **Rival:** an exact copy is an extreme case. Real rivals will differ, and there will be more of them.
10. **Break-even:** the "about 44%" figure is my own back-of-envelope arithmetic, not evaluator output.

New files: `runs/demo/joint/` (team-demo.csv, team-rival.csv) and `runs/demo/joint_week3/` (evaluation.json, leaderboard.csv, diagnostics/).
