# Reference plan for the absolute grading points

The absolute game points are `5 * min(1, max(0, S / (2B)))`, where `S` is a
team's final score (sum of its four graded submissions) and `B` is the score
of this reference plan: one 300 MW site at bus 6147, with no generator or
battery, built in Submission 1 of Weeks 2 and 3 and evaluated alone. It adds
nothing in Submission 2.

Bus 6147 ranks about 110th of 2,000 buses by minimum hosting capacity over the
120 representative hours (2,264 MW), so the site is well inside its limit.

| Submission | IT value | Site cost | Energy cost | Score |
| --- | --- | --- | --- | --- |
| Week 2, Submission 1 | $18.458B | $7.500B | $0 | $10.958B |
| Week 3, Submission 1 | $18.458B | $7.500B | $0.329B | $10.629B |
| Week 2 and 3, Submission 2 | — | — | — | $0 |

`B = $21.587B`; full absolute points need `S >= $43.17B`.

Reproduce with the released defaults (representative package and rules):

```bash
ercot-game-batch run --submissions-dir data/teaching/reference_plan \
  --output-dir results/reference_week2 --week 2 --submission-number 1
ercot-game-batch run --submissions-dir data/teaching/reference_plan \
  --output-dir results/reference_week3 --week 3 --submission-number 1
```
