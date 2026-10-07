# Phase 4C Electrify Shadow Execution

Status: **PASS — Teaching Scenario V2 shadow execution complete**

Date: 2026-10-01

## Scope

The identical immutable Phase 4A job package was executed locally and on
Electrify using a three-team locked batch built from the production Teaching
Scenario V2 and Planning Model V1. Local execution remained authoritative;
the remote run was a shadow comparison only. No production service, Classroom
database, scheduler, or student-facing route was connected.

## Batch

```text
scenario_id: ercot-planning-teaching-v2
planning_model_version: 1.0.0
evaluator_version: 0.3.0
policy_version: phase3-canonical-v1
teams: team-v2-alpha, team-v2-bravo, team-v2-gulf
batch_input_hash: 5cf94e84b16eb4c75ca445d5c3b9babc90cee6ff6c925e240a15c41ea82b19be
```

The batch exercises variable connection profiles, a generator-backed team,
two teams sharing the `HIGH_PLAINS__PERMIAN` Planning Interface, and a
feasible team on `SOUTH_TEXAS`.

## Remote environment

- Host: `electrify.ecn.purdue.edu`
- Isolated directory: `/home/minghao/ercot_gate4c_shadow_20261001`
- Runtime: system Python 3.10.12
- GPU: NVIDIA RTX 6000 Ada; not used
- Queue/scheduler: not used for this foreground shadow run
- Compatibility: the same temporary smoke-only `sitecustomize.py` shim used by Gate 4B supplied `StrEnum` and `typing.NotRequired`; production source remains Python 3.11+

## Result comparison

Local and remote comparisons had no mismatches for status, scenario/model
identity, canonical input hash, complete ranked results, team scores,
feasibility, binding-resource diagnostics, or replayed output hash.

```text
status: complete
job_id: shadow-v2c
output_hash: 9459ad9388dd0c82e0e02c1a4118045f80bc0f8fdce25d9ec3516a92f23b0bc9
replayed_output_hash: 9459ad9388dd0c82e0e02c1a4118045f80bc0f8fdce25d9ec3516a92f23b0bc9
artifact_sha256: 26ecc5e816951648b1985168d6b34c4bdeb127e70557cbbad880faad6a0ca7a2
local_remote_artifact_bytes_match: true
```

Ranked results were identical:

| Rank | Team | Revenue | Feasible | Binding resource |
| ---: | --- | ---: | :---: | --- |
| 1 | `team-v2-gulf` | `6318.0` | yes | none |
| 2 | `team-v2-alpha` | `-32133.210000000006` | no | `corridor:HIGH_PLAINS__PERMIAN` |
| 3 | `team-v2-bravo` | `-46988.0` | no | `corridor:HIGH_PLAINS__PERMIAN` |

## Validator correction discovered during shadow preparation

The V2 batch intentionally used variable profiles. This exposed an existing
multiteam audit-validation bug: it compared network availability against
`capacity × ratio`, which is only correct for an all-ones profile. The correct
invariant is `requested_load × ratio`, where
`requested_load = capacity × profile`.

The correction is limited to audit validation and does not change allocation,
recourse, scoring, or evaluator mathematics. A focused regression test now
ensures a locked V2 round with a variable profile remains valid.

## Verification

- Remote evaluator/job module compilation: passed.
- Remote package execution and audit replay: passed.
- Local package execution and audit replay: passed.
- Complete ranked-result and diagnostic comparison: passed with no mismatches.
- Local/remote artifact SHA-256 comparison: passed.
- Focused multiteam, job, and Planning Model tests: `39 passed`.
- Full project regression suite: `596 passed`.

## Not yet proven

Gate 4C did not prove scheduler submission or production queue behavior. The
opt-in instructor-service boundary, retry/cancel contract, and verified
artifact ingestion are documented in
[ERCOT_PHASE4D_REMOTE_JOB_INTEGRATION.md](ERCOT_PHASE4D_REMOTE_JOB_INTEGRATION.md).
A scheduler-specific transport adapter remains deployment work, and local
execution remains authoritative until that adapter is selected and tested.
