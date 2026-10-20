# Lecture data

The lecture figures use one-hour resolution, which is easier to explain than
the game's six-hour periods. All numbers in the slides come from the files in
`raw/`, produced on Electrify on 2026-10-17 from the hourly ACTIVSg2000
scenario package (`activsg2000_scenarios_v1`, 2028 July--December unless
noted), and are turned into plot tables and `numbers.tex` by
`scripts/make_lecture_data.py` (run from `docs/guest_lecture`); `scripts/make_figures.py` then
draws the slide figures with matplotlib into `figures/*.pdf`. The one exception
is the site picture on "Your role in one picture", which is TikZ
(`figures/site_icons.tex`, icons from `fontawesome5`). The two AI-agent slides
summarize the session recorded in `docs/student_tutorial/ai_walkthrough/`.

The hourly package is kept locally and is not published in this repository.
Its manifests report `unverified_dependency`; for these runs the copy on
Electrify was marked `passed` so the solver would accept it. The hosting
capacity at bus 1002 in hour 1837 (123 MW) matches the value computed earlier
on the same package.

| Raw file | Command |
| --- | --- |
| `raw/hc1h_allbuses_peakday/` | `ercot-game-hosting-capacity --artifact-dir .../activsg2000_scenarios_v1/2028/jul_dec --horizon 4416 --start-period 1824 --period-count 24 --solver-backend gurobi --workers 16 --write-long-form` (all 2,000 buses, the 24 hours of the peak-load day) |
| `raw/hc1h_selected_allhours/` | same, `--start-period 0 --period-count 4416` for buses 1001 1002 1007 1010 7419 7087 7077 7127 5253 5370 |
| `raw/pair_region_p1837.json` | `scripts/pair_region.py 1837 .../activsg2000_scenarios_v1/2028/jul_dec`: two-bus region for buses 1002/1010 at the peak hour and the two-team example (HiGHS via `solve_prepared_period`) |
| `raw/uniform_two_team_p1837.json` | `scripts/uniform_two_team.py 1837 .../activsg2000_scenarios_v1/2028/jul_dec` (Electrify, 2026-10-18): the two-team payoffs under the evaluator's uniform rule (common MW level, then water-filling); used for the two-team slide in place of the payoffs in `pair_region_p1837.json` |
| `raw/eight_team_1h_summary.json` | the hourly eight-team run of 2026-10-14 (`ercot-game-batch run`, 2028 January--June, 4,368 hours) |

The grid map (`figures/grid_map.svg`) is that hourly run drawn with
`ercot-game-grid-map --layout data/teaching/activsg2000_geo_layout_v1.json
--time-step-hours 1`; bus locations come from
`tools/activsg2000/build_geo_layout.py` and are approximate.

The peak-load day is day 76 (hours 1824--1847); hour 1837 has the highest
system load. The storage example uses hourly steps, B = 4P, a daily cycle
that starts and ends at B/2, and discharge that only serves the site's own
load.
