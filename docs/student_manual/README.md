# Student Manual

This directory contains the LaTeX source for the competitive data-center
connection-planning assignment manual.

```text
main.tex       # document source
references.bib # cited sources
../scripts/check_submission.py  # student-facing CSV format checker
```

The manual uses Times-compatible text/math fonts and GitHub-style `listings`
blocks for CSV examples and technical identifiers. The instructor should
update the round-specific hourly price/value vectors and storage-cost
coefficients before distributing a final release.

Students can check a submission before uploading it with:

```bash
PYTHONPATH=src python scripts/check_submission.py \
  --file team-blue.csv \
  --artifact-dir data/processed/texas_dispatch_source_v1 \
  --horizon 4368
```

Use `--horizon 4416` for the July--December half-year. The checker validates
the canonical `bus_id` schema against the released Zenodo bus and generator
catalogs; the instructor-side evaluator remains authoritative.
