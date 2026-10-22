I computed the hosting capacity of all 14 buses over the 120 hours (1,680 solves, all optimal). Output went to a temporary folder outside the project, so no project files changed.

```bash
ercot-game-hosting-capacity \
  --artifact-dir data/teaching/ieee14_demo_representative \
  --horizon 120 --period-count 120 --output-dir <tmp>/hc14
# backend highs, bus_count 14, completed_point_count 1680, failed_point_count 0, wall_time 1.6 s
```

Then I took each bus's minimum from `hosting_capacity_mw.npy`, which has one value per hour and bus. The columns are in the order of `bus_ids` in the metadata file (`1,10,11,...`), not numeric order, so I matched them up by that list.

| Bus | Min hosting capacity (MW) |
|---|---|
| 1 | 470.7 |
| 2 | 428.8 |
| 5 | 310.8 |
| 4 | 240.9 |
| 3 | 180.3 |
| 7 | 177.7 |
| 8 | 177.7 |
| 6 | 168.8 |
| 9 | 103.0 |
| 13 | 50.8 |
| 11 | 45.4 |
| 10 | 44.5 |
| 12 | 42.9 |
| 14 | 37.6 |

**What it means:** a bus's minimum hosting capacity is the most new load you could add at that bus alone, with every other bus at its normal load, that the grid can still serve in every one of the 120 hours without overloading a line or running out of generation. For every bus the lowest value falls in hour 109, which is on the peak day.

**Shortlist: buses 1 and 2.**
- They have by far the most room: 471 and 429 MW, even in the peak hour.
- They sit next to the two cheapest and largest generators: g1 (332 MW at $14/MWh) and g2 (140 MW at $18/MWh).
- They are far from the weak 20–30 MVA lines around buses 9–14, where hosting capacity drops to 38–103 MW.

**One caution:** these numbers are for one bus at a time, and they don't add up. Every team will see the same table, so buses 1 and 2 may get crowded. Bus 5 (311 MW) is a good fallback.
