In the Week 3 preview, all of your load is served and the plan scores about **+$15.6 billion**. The term that dominates is IT value ($27.6B), and the biggest cost is site cost ($11.2B). So yes, the plan is well above break-even.

The preview needs a folder of submissions, and `runs/demo/` also holds `plan_bad.csv`. So I copied the valid plan into its own folder. I also used the demo's scoring rules, as the package README does.

```bash
mkdir -p runs/demo/submissions && cp runs/demo/plan.csv runs/demo/submissions/
ercot-game-preview --submissions-dir runs/demo/submissions \
  --artifact-dir data/teaching/ieee14_demo_representative \
  --rules data/teaching/dispatch_scoring_rules_ieee14_demo_representative_v1.json \
  --week 3 --output runs/demo/preview_week3.json
# wrote preview: runs/demo/preview_week3.json
# WARNING: this is a conservative preview, not the official score.
```

Key output for team-demo (valid and feasible, all 120 periods checked, energy cost on):

| Term | $ |
|---|---|
| IT value | +27.63 B |
| Energy cost (LMP) | −0.83 B |
| Generator and storage costs | 0 |
| Site cost (449 MW × $25M) | −11.23 B |
| **Score** | **+15.57 B** |

- **Share of load served: 100%.** The preview reports 3,933,240 MWh served. That equals 449 MW × 8,760 h, the full request for a year. The IT value matches 449 MW × 61,527 MWh-equivalents × $1,000.
- **Break-even:** each fully served MW earns about $61.5M of IT value over ten years. It costs $25M of site cost plus roughly $1.8M of energy (the $0.83B spread over 449 MW). That puts break-even at about 44% service, and the plan is far above it.

**Caveats:**
- This is only your team on the demo grid. In the real evaluation, other teams building at the same buses could push your service down, and a team served less than half of its request gets nothing.
- The preview does not run batteries (it says so in its warning). That doesn't matter for this plan, which has none.
- The demo's numbers say nothing about the real ACTIVSg2000 game.

The run created `runs/demo/submissions/plan.csv` and `runs/demo/preview_week3.json`.
