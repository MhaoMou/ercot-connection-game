I only read files and changed nothing. `.venv/` doesn't have pandas, so I used Python's built-in `csv` module.

```bash
cd data/teaching/ieee14_demo_representative
ls; for f in *.csv; do echo "$f $(($(wc -l <$f)-1)) rows"; head -3 $f; done; head -60 manifest.json
.venv/bin/python -c "import csv ..."   # sorts branch_limits.csv by thermal_limit_mva; sums bus_load_base.csv, demand_bus.csv and generator_limits.csv
```

**Summary of `data/teaching/ieee14_demo_representative`:**
- **Buses:** 14.
- **Lines:** 20, all in service. There are no DC lines (`dcline.csv` is empty).
- **Generators:** 5, with 772.4 MW total capacity:

  | Generator | Bus | Capacity (MW) | Cost ($/MWh) |
  |---|---|---|---|
  | g1 | 1 | 332.4 | 14 |
  | g2 | 2 | 140 | 18 |
  | g3 | 3 | 100 | 24 |
  | g6 | 6 | 100 | 27 |
  | g8 | 8 | 100 | 30 |

- **Load:** the base load is 259.0 MW. Across the periods it ranges from 224.5 to 301.7 MW, with an average of 264.5 MW.
- **Operating periods:** 120. That is 5 representative days of 24 one-hour periods. The day weights add up to 365, and the peak day has a weight of 1.
- **Five smallest thermal limits:**

  | Line | Buses | Limit (MVA) |
  |---|---|---|
  | br19 | 12–13 | 20 |
  | br18 | 10–11 | 25 |
  | br20 | 13–14 | 25 |
  | br11 | 6–11 | 30 |
  | br12 | 6–12 | 30 |

  br16 (9–10) is also at 30 MVA, so the 4th and 5th places are a three-way tie at that limit.

These weak lines are all in the low-voltage area around buses 9–14, so a large site there will hit congestion first. The manifest says this demo is not the game network, so use it for practice only.
