# Student Tutorial

This directory contains the student tutorial for the ACTIVSg2000 data-center
connection game (`main.tex`; the built PDF is committed as `tutorial.pdf`), its
figures, and seven
small companion notebooks.

The game plans the next ten years on five representative days of 24 one-hour
periods (120 periods in all) with the `daily_exact_cycle` storage boundary.
Each representative day is weighted by the number of calendar days it stands
for, so the 120 hours make up one year, and the yearly result is discounted
over ten years. The student CSV is a site-level plan; it does not contain one
row per period. The numbers in the tutorial come from
`data/teaching/dispatch_scoring_rules_representative_v1.json` and the
scenario package in `data/processed/activsg2000_representative_v1/`.

## What is here

- `tutorial.pdf`: the built tutorial; start here.
- `main.tex` and `references.bib`: the LaTeX source. It compiles with
  `pdflatex` and `bibtex` from this directory.
- `figures/`: the TikZ and PDF figures used by `main.tex`.
- `notebooks/`: seven small companion notebooks.
- `ai_walkthrough/`: a recorded session with an AI coding agent, used as an
  example in the tutorial.

## Using the notebooks

The notebooks use tiny made-up fixtures to show individual mechanics. Open
them locally or upload them to Google Colab. When using Colab, clone or
otherwise provide the repository before running cells so paths resolve
consistently. The local tutorial dependencies can be installed with:

```bash
python3 -m pip install -e '.[tutorial]'
```

Then start Jupyter from the repository root and open
`docs/student_tutorial/notebooks/`.

## Verification and privacy

Treat every AI response as a starting point. Verify file names, columns, units,
bus IDs, solver status, numerical outputs, and provenance using the repository
files or executable examples. The student preview is conservative and
non-authoritative; it is not an official score.

Do not upload private team plans, credentials, rankings, instructor-only
diagnostics, or other confidential information to shared AI tools. Use public
data, synthetic examples, or instructor-approved fixtures only.
