Here is the summary of `data/teaching/ieee14_demo_1h`. I took the numbers straight from the package's CSV files and checked them against its `README.md` and `manifest.json`. They all agree, and I didn't change any files.

Commands I ran (from the project folder):
```
ls -la data/teaching/ieee14_demo_1h
cat data/teaching/ieee14_demo_1h/README.md data/teaching/ieee14_demo_1h/*.csv   # plus head/wc on demand_bus.csv
.venv/bin/python -I - data/teaching/ieee14_demo_1h <<'EOF' ... EOF   # short csv/json script to count, sum and sort
```
Key output:
```
buses 14 branches 20 in service 20 generators 5 gen Pmax 772.4
base load MW 259.0
periods 168 load min/mean/max 242.9 264.6 287.7 peak period 157
br19 12-13 20.0 | br18 10-11 25.0 | br20 13-14 25.0 | br11 6-11 30.0 | br12 6-12 30.0 | br16 9-10 30.0 | br17 9-14 30.0
manifest: horizon 168, time_step_hours 1, validation_status passed
```

- **Buses:** 14, with IDs "1" to "14". Bus 1 is the reference bus.
- **Lines:** 20, all in service. There are no DC lines.
- **Generators:** 5, totalling 772.4 MW.
  - g1 at bus 1: 332.4 MW, $14/MWh
  - g2 at bus 2: 140 MW, $18/MWh
  - g3 at bus 3: 100 MW, $24/MWh
  - g6 at bus 6: 100 MW, $27/MWh
  - g8 at bus 8: 100 MW, $30/MWh
- **Total load:** 259.0 MW base. Over the week it ranges from 242.9 to 287.7 MW, with a mean of 264.6 MW. The peak is period 157 (day 7, 13:00–14:00).
- **Operating periods:** 168 one-hour periods, which is one week, 1–7 July 2028. This is not the six-hour format of the real game.
- **Five smallest thermal limits:**

| Line | Limit (MVA) |
|---|---|
| 12-13 | 20 |
| 10-11 | 25 |
| 13-14 | 25 |
| 6-11 | 30 |
| 6-12 | 30 |

  Two more lines, 9-10 and 9-14, are also at 30 MVA, so "the five smallest" is really a four-way tie at 30.

The package's README says lines 6-13, 9-14 and 13-14 together limit buses 13 and 14. It reports that 30 MW at both buses doesn't fit in the peak hour, while 20 MW at both does. If you run this package, use `--horizon 168` and `--preview-stride 1`. The README warns that the default stride skips the peak hour.

This also answers your earlier question about what you submit, how it's scored and which commands you'll use. That answer stands as I gave it.
