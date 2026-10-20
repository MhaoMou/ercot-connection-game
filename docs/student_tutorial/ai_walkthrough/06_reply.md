With the rival copying our plan, each team gets a service fraction of 0.527 and each scores about −$174M. Our plan only works if nobody else builds near buses 1 and 2.

```
mkdir -p runs/demo_joint
cp runs/demo/plan.csv runs/demo_joint/team-demo.csv
sed 's/^team-demo,/team-rival,/' runs/demo/plan.csv > runs/demo_joint/team-rival.csv
.venv/bin/ercot-game-check-csv --file runs/demo_joint/team-rival.csv --artifact-dir data/teaching/ieee14_demo_1h   # VALID
.venv/bin/ercot-game-batch run --submissions-dir runs/demo_joint \
  --artifact-dir data/teaching/ieee14_demo_1h \
  --rules data/teaching/dispatch_scoring_rules_ieee14_demo_1h_v1.json \
  --output-dir work/demo_joint_batch --horizon 168 --time-step-hours 1 --submission-number 2
# summary: 2 teams scored, 0 rejected, scope=joint_projection
.venv/bin/python -I -c "...read work/demo_joint_batch/evaluation.json and leaderboard.csv..."
```
New files are `runs/demo_joint/` (two CSVs) and `work/demo_joint_batch/`.

**Result.** The combined 920 MW was infeasible, so the evaluator applied the fair-share rule. Both teams were cut back to the same level of 242.35 MW each.

| Team | Requested | Served | Service fraction | Score |
|---|---|---|---|---|
| team-demo | 460 MW | 242.35 MW | **0.527** | **−$174.07M** |
| team-rival | 460 MW | 242.35 MW | **0.527** | **−$174.07M** |

For each team, IT value falls to $264.7M and energy cost to $1.2M, but site cost stays at $437.5M because it is charged on the full 460 MW requested.

**What it means for our plan:**
- **Swing:** with one copycat, our score drops from +$62.5M (alone) to −$174M.
- **Below break-even:** 52.7% served is far below the ~88% this plan needs.
- **Near the cutoff:** 52.7% is just above the 50% cutoff, so one more copycat or a slightly bigger request would drop us to zero service. We would still pay the $437.5M site cost.
- **Smaller requests are safer:** the two teams together got 484.7 MW, which equals the hosting capacity of bus 1 alone. A smaller request would be served in full under the same rule.
- **The table isn't a budget per team:** a hosting-capacity number is shared by everyone who reads it.

**Assumptions from this session you should check yourself:**
1. **Course rules:** Part I leaves dates, file naming, grading, tie-breaks, the late policy and team-coordination rules as instructor placeholders. My summary doesn't cover them.
2. **Package choice:** I used `data/teaching/ieee14_demo_1h` as you asked. It is a teaching demo, not the ACTIVSg2000 game grid. Its capital costs are scaled down to one week (168/4416), so none of these numbers transfer.
3. **Hosting capacity:** I computed each bus on its own with `--artifact-dir` (not the bundled `--ieee14` case), over periods 0–167. I treated the per-bus minimum as "safe" capacity, but these values don't add across buses.
4. **The shortlist:** I picked buses 1 and 2 for headroom and cheap nearby generators. I didn't consider what other teams would do, which this run shows matters most.
5. **Sizing:** "about half" became 240 and 220 MW (rounded). The site IDs are names I made up.
6. **The broken file:** I put it in `runs/demo_bad/` so it can't be mixed into a preview or batch run.
7. **Preview:** it skips battery dispatch and is not the official score. I assumed `--preview-stride 1` and `--submission-number 2` match how the demo would be graded.
8. **Joint run:** I passed the package README's flags (`--time-step-hours 1`, `--horizon 168`) and let the evaluator infer `--source-period-offset` and use its default `--projection-iterations` (the README run uses 10). I ran a single Submission 2 with no Submission 1 history, so all capital is charged here.
9. **The rival:** it is an exact copy. Real rivals would choose different buses and sizes, and there would be more than two teams.
10. **Break-even:** the ~88% figure is my own arithmetic from the preview's site cost and energy cost.
11. **Extra files:** I created `runs/demo/`, `runs/demo_bad/`, `runs/demo_joint/` and the `work/` outputs. Check that your course repository ignores these before you commit anything. The repository files themselves are unchanged.
