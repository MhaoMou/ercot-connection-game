I ran the hosting-capacity tool on all 14 buses for all 168 hours. All 2,352 solves finished with no failures, in about 2.5 s. I'd shortlist **buses 1 and 2**, but treat their numbers as a ceiling, not a guarantee, because other teams can crowd them.

Commands (run from the project folder):
```
.venv/bin/ercot-game-hosting-capacity --help
.venv/bin/ercot-game-hosting-capacity --artifact-dir data/teaching/ieee14_demo_1h \
  --horizon 168 --start-period 0 --period-count 168 \
  --output-dir work/demo_hc_all --write-long-form
# -> "bus_count": 14, "complete": true, "completed_point_count": 2352, "failed_point_count": 0
.venv/bin/python -I -c "...read work/demo_hc_all/hosting_capacity_long.csv.gz, take the minimum per bus..."
```
The run wrote its results to a new folder, `work/demo_hc_all/`. No other files were changed. (`pandas` isn't installed in `.venv/`, so I read the results with the standard `csv`/`gzip` modules.)

**Minimum hosting capacity per bus over the week.** Every bus hits its minimum in hour 157, which is the peak-load hour.

| Bus | Min HC (MW) | Bus | Min HC (MW) |
|---|---|---|---|
| 1 | 484.7 | 6 | 171.7 |
| 2 | 440.6 | 9 | 105.7 |
| 5 | 317.9 | 13 | 52.5 |
| 4 | 248.1 | 11 | 46.1 |
| 3 | 185.4 | 10 | 45.0 |
| 7 | 180.0 | 12 | 43.2 |
| 8 | 180.0 | 14 | 38.5 |

These values match the hour-157 table in the package's `README.md`.

**What the number means:** it is the largest extra load you could add at that one bus, with no other new load anywhere, that the grid could still serve in every hour of the week without overloading a line or running out of generation.

**Why buses 1 and 2:**
- **Most room:** at about 485 MW and 441 MW, they have far more space than any other bus.
- **Cheapest energy:** they sit next to the cheapest generators (g1 at $14/MWh and g2 at $18/MWh). Energy costs little here unless lines get congested.
- **Little swing:** their hosting capacity changes only about 10% over the week.

**Caveats:**
- **Not additive:** each value is for one bus on its own. Buses 1 and 2 are directly connected and share the same network capacity, so you can't build 485 MW at one and 441 MW at the other.
- **Shared with other teams:** every team sees this same table, so these buses may get crowded. The fair-share rule then cuts everyone back, and a team served less than 50% of its request gets nothing.
- **Avoid buses 13 and 14:** they share a bottleneck (lines 6-13, 9-14 and 13-14). The README reports that 30 MW at each doesn't fit together, even though each fits alone.
