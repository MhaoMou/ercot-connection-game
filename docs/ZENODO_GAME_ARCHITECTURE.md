# Zenodo Game Architecture

The current game has one supported execution path:

1. Students submit one complete long-form CSV per team.
2. The validator checks source-bus IDs, generator IDs, storage declarations,
   and complete half-year coverage against the prepared Zenodo artifact.
3. The batch evaluator combines valid teams and solves one DCOPF per hour.
4. If the joint plan is infeasible, fair continuous projection seeks the
   largest common service fraction before deterministic fallback isolation.
5. Scores and rankings are written to instructor-private output artifacts.

The prepared artifact is the Texas subset of the Zenodo U.S. Test System,
containing approximately 2,000 buses and the associated branches, demand,
generator limits, and generator cost catalog.

The canonical plan model contains only:

- connection site: source `bus_id`, requested capacity in MW, and hourly load
  profile;
- generator: catalog `generator_id`, owned capacity in MW, and catalog-derived
  marginal cost;
- storage: owned power capacity in MW and energy capacity in MWh.

There is no browser planning model, abstract region/interface layer, or
student-supplied flexibility/curtailment parameter in the current production
workflow. Dispatch uses fixed submitted load and continuous storage scheduling.
