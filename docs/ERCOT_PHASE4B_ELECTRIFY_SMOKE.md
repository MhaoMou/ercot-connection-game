# Phase 4B Electrify Smoke Job

Status: **PASS — isolated smoke execution complete**

Date: 2026-10-01

## Scope

One non-classroom Teaching Scenario V2 evaluation package was staged in an
isolated Electrify directory and executed with the Gate 4A local worker. No
student-facing route, classroom round, or production database was connected to
the remote run.

## Remote environment

- Host: `electrify.ecn.purdue.edu`
- Isolated directory: `/home/minghao/ercot_gate4b_smoke_20261001`
- Runtime: system Python 3.10.12
- GPU: NVIDIA RTX 6000 Ada; not used by this evaluator
- Electrify job queue: not used for this short foreground smoke run
- Interactive SSH: used only to launch and inspect this one isolated test

The project targets Python 3.11+, while the available system runtime is
Python 3.10.12. `typing_extensions` was already installed, so a temporary
smoke-only `sitecustomize.py` compatibility shim supplied `StrEnum` and
`typing.NotRequired`. Production source was not modified for this runtime
difference. The evaluator modules compiled and imported successfully.

## Package and result

```text
job_id: smoke-1
scenario: ercot-planning-teaching-v2
evaluator: 0.3.0
status: complete
batch_input_hash: 1610d1b90670f10d2379ba220adcb6d6d7be5cd9914af63b8d493cb8a391efcd
output_hash: 9ce63f71b938e3449058f4ef48d11edc5ee03ef766f05063d7e001b368618619
replayed_output_hash: 9ce63f71b938e3449058f4ef48d11edc5ee03f766f05063d7e001b368618619
```

The local and remote output hashes matched. The serialized artifact files also
matched byte-for-byte:

```text
artifact_sha256: 83f2a0e83b7c83c876c8894f3902d70fc44eff03c8505c7a14d38c9df6a31941
```

## Verification performed

- Remote Python compilation of evaluator, orchestration, and job modules.
- Remote package execution.
- Remote artifact replay.
- Local execution of the identical package.
- Local artifact replay.
- Local/remote artifact SHA-256 comparison.
- Existing Gate 4A focused tests: 3 passed.
- Full project regression suite: 595 passed before the smoke-only remote staging.

## Interpretation

Gate 4B proves that the current self-contained job package can execute on
Electrify’s available Python runtime and produce a byte-identical artifact to
the local worker for this smoke case.

It does not yet prove:

- scheduler submission or queue behavior;
- artifact transfer through a production job mechanism;
- retry/cancellation behavior;
- multi-team classroom batch scale;
- remote execution through the Phase 3 instructor service;
- that the Python 3.10 compatibility shim is suitable for production.

The isolated multi-team shadow execution is documented in
[ERCOT_PHASE4C_SHADOW_EXECUTION.md](ERCOT_PHASE4C_SHADOW_EXECUTION.md). The
remaining work is deployment-specific scheduler/service integration; it is
not required to change the evaluator or make the remote worker authoritative.
