# Reference plan for the absolute grading points

The absolute game points are `5 * min(1, max(0, S / (2B)))`, where `S` is a
team's final score (sum of its four graded submissions) and `B` is the score
of this reference plan: one team alone runs 500 MW off the grid, a single
500 MW site with a 500 MW generator (G = C) and no battery, built in
Submission 1 of Weeks 2 and 3. It adds nothing in Submission 2.

An off-grid site never draws from the grid, so its score does not depend on
the bus, on the other teams or on the week's energy price. `B` is computed
analytically from `dispatch_scoring_rules_representative_v1.json`, with the
generator at full output in every hour (the 120 period weights sum to
61,526.57 hours):

| Term | Per graded submission |
| --- | --- |
| IT value: 500 MW x 61,526.57 h x $1,000/MWh | $30.7633B |
| Fuel: 500 MW x 61,526.57 h x $157.5/MWh (25% at $80, 50% at $150, 25% at $250) | -$4.8452B |
| Site cost: 500 MW x $25M/MW | -$12.5000B |
| Generator capital: 500 MW x $2.0M/MW | -$1.0000B |
| Score | $12.4181B |

| Graded submission | Score |
| --- | --- |
| Week 2, Submission 1 (W2S1) | $12.418B |
| Week 2, Submission 2 (W2S2) | $0 (no new sites) |
| Week 3, Submission 1 (W3S1) | $12.418B |
| Week 3, Submission 2 (W3S2) | $0 (no new sites) |
| **Final score, B** | **$24.836B** |

`B` is the reference team's final score, the sum of its four graded
submissions, so it is compared directly with a team's final score `S`; full
absolute points need `S >= 2B = $49.67B`.

The batch evaluator is not used for `B`: the grid operator minimizes total
cost, so it would serve part of this site from the grid whenever grid energy is
cheaper than the generator's fuel, and the site would no longer run off the
grid. `team-reference.csv` is the plan itself, for reference.
