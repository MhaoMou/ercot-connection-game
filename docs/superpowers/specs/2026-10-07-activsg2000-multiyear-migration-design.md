# ACTIVSg2000 Multi-Year Dataset Migration Design

**Date:** 2026-10-07  
**Status:** Approved for implementation after user approval of aggressive cleanup

## Goal

Replace the current Zenodo-based prototype data path and its 2017/2018
zonal-load extensions with a validated, versioned three-year
ACTIVSg2000-compatible scenario package suitable for six half-year student
submissions.

## Design

The final game data path will use a fixed ACTIVSg2000-compatible network
topology plus generated or source-backed hourly operating scenarios. Every
hourly state must pass the repository DCOPF before it is admitted to the
student-game artifact.

The scenario package will contain:

- fixed bus, branch, and generator catalogs;
- bus-level hourly load;
- generator-specific wind and solar availability;
- generator availability/capacity data;
- fixed generator costs;
- fixed or scenario-specific branch limits;
- half-year calendar metadata;
- a validation manifest with hashes, counts, and hourly DCOPF results.

The evaluator will accept only a scenario directory whose manifest declares
that all requested hours passed validation. Invalid or incomplete scenario
packages will fail closed.

## Scenario construction

The repository will first look for a complete ACTIVSg2000-compatible source
package. If no complete three-year package is available, the generator will
create a controlled scenario package from the fixed topology:

1. derive or load three complete calendar years of bus-level load;
2. map generator-specific wind/solar profiles to catalog generators;
3. assign generator availability and preserve catalog capacity limits;
4. preserve fixed generator marginal costs from the selected source artifact;
5. preserve fixed branch limits unless a scenario explicitly declares a
   versioned alternative;
6. generate deterministic scenario metadata and SHA-256 hashes;
7. run hourly DCOPF validation before publishing the package.

The controlled package is a teaching scenario, not a claim that it reproduces
historical ERCOT operations.

## Active time model

Each student submission covers one half-year with one-hour periods:

- January--June: 4,368 hours in leap years and 4,344 otherwise;
- July--December: 4,416 hours.

The package will expose six half-year blocks across three years. No six-period
legacy convention remains in production code or student-facing documentation.

## Validation contract

For every included hour:

- all bus demands are finite and nonnegative;
- generator availability is finite and within catalog capacity;
- branch limits are finite and nonnegative;
- all referenced IDs exist in the fixed catalog;
- DCOPF reaches a feasible status;
- the manifest records the validated period and solver result.

The validator will fail on the first invalid input class and report all
failed periods in its summary. The evaluator will refuse an artifact with
missing validation metadata or a failed hour.

## Cleanup boundary

The aggressive cleanup removes from active source control:

- data/processed/texas_dispatch_source_v1/;
- data/processed/texas_dispatch_source_v1_years/;
- data/processed/ercot_loads/;
- the old Zenodo-specific extraction, preparation, and multi-year extension
  implementation;
- tests whose only purpose is the retired Zenodo/prototype data path;
- outdated teaching rules and documentation that describe the retired data
  source or six-period convention;
- obsolete toy-network and previous webpage artifacts when they are not
  needed by the current results viewer.

The raw Zenodo archive is not used by the final evaluator. It will be removed
from the repository as part of aggressive cleanup after the new package has
been created and validated. Source provenance for the new package will be
recorded in its manifest and documentation.

No deletion will be performed through broad recursive commands. Each target
will be listed and checked for references before removal.

## Compatibility

The CSV schema and scoring model remain conceptually unchanged unless a
scenario-specific field is required to represent generator availability. The
evaluator continues to calculate:

- IT-service value;
- grid energy cost;
- generator operating and capital cost;
- site cost;
- storage capital and operating cost.

The current Zenodo-based implementation is not retained as a supported runtime
fallback.

## Testing

The migration must add or update tests for:

- scenario manifest structure and hashes;
- complete three-year/half-year indexing;
- profile dimensionality and ID coverage;
- generator and branch-limit bounds;
- hourly DCOPF validation;
- evaluator refusal of unvalidated or incomplete artifacts;
- CSV validation against the new catalogs;
- representative feasible and infeasible batch submissions.

The full existing suite must pass after obsolete Zenodo-only tests are removed
or replaced.

