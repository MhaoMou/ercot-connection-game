I ran `cat README.md` and `sed -n 111,366p docs/student_tutorial/main.tex` (Part I). I didn't change any files.

**What you submit:** one CSV per submission, two a week for three weeks (six files in all). It has exactly the header `team_id,site_id,bus_id,connection_capacity_mw,generator_capacity_mw,storage_power_mw,storage_energy_mwh` and one row per site. The rules are G ≤ 0.5C and storage either zero or B = 4P. Submission 2 lists only new sites. You also give a final presentation and a report.

**Scoring:** score = IT value ($1,000/MWh served, over 10 years) − energy cost (charged at the LMP, Week 3 only) − generator operating cost − capital costs (site $25M/MW, generator $1.5M/MW, storage $400k/MW + $250k/MWh). All plans are dispatched together. An invalid file scores 0. Your final score is the sum of the four Week 2 and 3 submissions. It is worth 10 of the assignment's 40 points; the other 30 come from the presentation, report and your work.

**Commands:**
```bash
python -m pip install -e .
ercot-game-check-csv --file team.csv --artifact-dir <package>
ercot-game-preview   # approximate score for your plan alone
```

Note: the README describes an older six-hour setup ($6,500/MWh). Follow Part I.
