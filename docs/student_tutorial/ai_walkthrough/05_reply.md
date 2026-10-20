The plan is above break-even. The preview serves all of its load and gives a score of about +$62.5M, but its margin over break-even is thin.

```
.venv/bin/ercot-game-preview --submissions-dir runs/demo \
  --artifact-dir data/teaching/ieee14_demo_1h \
  --rules data/teaching/dispatch_scoring_rules_ieee14_demo_1h_v1.json \
  --horizon 168 --preview-stride 1 --submission-number 2 \
  --output work/demo_preview.json
# wrote preview: .../work/demo_preview.json
# WARNING: this is a conservative preview, not the official score.
.venv/bin/python -I -c "...print the fields of work/demo_preview.json..."
```
The preview checked all 168 periods and found the plan feasible. The only file written was `work/demo_preview.json`.

**Load served: 100%.** Served energy was 77,280 MWh, which is exactly the full request (460 MW × 168 h). So the plan fit the grid in every hour, even though buses 1 and 2 share network capacity.

| Term | $ |
|---|---|
| IT value | +502,320,000 |
| Site cost (460 MW × ~$0.95M/MW) | −437,500,002 |
| Energy cost (Submission 2) | −2,318,400 |
| Generator and storage costs | 0 |
| **Score** | **+62,501,598** |

**Dominant term:** the score is mostly IT value minus site cost. Site cost is by far the largest cost and takes 87% of the IT value. Energy cost is under 0.5% of IT value. It works out to $30/MWh on average, above the $14 uncongested price, so some lines bind.

**Break-even:** this plan needs about 87.6% of its load served to reach zero, which is (437.5M + 2.3M) / 502.3M. It got 100%, a margin of about 12 percentage points. If other teams also crowd buses 1 and 2 and the fair-share rule cuts this team below about 88%, the score turns negative. Below 50% it gets nothing but still pays the full site cost.

This is a preview of this one team alone, and batteries are not dispatched. Only the instructor's joint evaluation produces an official score.
