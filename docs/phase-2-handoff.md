# Phase 2 Handoff to Phase 3

## Current boundary

Phase 2 is complete as a local, single-team practice interface around the deterministic Phase 1 evaluator. It supports canonical multi-site/multi-generator plans and legacy single-site normalization, but it has no authentication, persistent submissions, official deadlines, rankings, multi-team service, instructor control plane, external execution, or Gymnasium/RL wrapper. The browser and server are seams for future work, not a deployed competition platform.

Everything below is future design and research work, not current capabilities. Phase 3 must preserve the practice-only and non-operational boundary until a separately validated service earns a different operating claim.

## Multi-team ordering and shared-corridor semantics

The current evaluator already provides useful semantic constraints for a future multi-team service: normalize each plan first, sort teams and connection IDs canonically, and never let HTTP arrival order determine a score. Bus requests are aggregated before allocation, but shared corridor capacity is consumed sequentially by `(connection_id, team_id)`. Legacy proportional behavior only where applicable remains a compatibility boundary; it does not describe canonical multi-site corridor allocation. Phase 3 should make this multi-team ordering policy explicit in the round contract and test order invariance with shuffled submissions.

For teams with multiple sites, a shared corridor is one common capacity resource for the period, not one independent copy per team or site. The service must define whether all teams consume a single published corridor budget, whether zones or cohorts create separate resource pools, and how binding/curtailed site diagnostics are exposed. Any shared-corridor allocation or tie-breaking rule must be deterministic, versioned, and replayable; presentation order must remain separate from semantic order.

## Persistent rounds and instructor controls

Future persistent rounds should store users, teams, scenario/evaluator versions, drafts, submissions, evaluation artifacts, round state, exact request payloads, semantic input hashes, and published results. Define draft, submitted, locked, evaluated, and published states; deadlines and timezone rules; idempotency keys; resubmission/correction policy; late or failed-submission behavior; and artifact retention.

An instructor control plane is also future work. It may need to create or clone rounds, select a versioned fixture, set open/close and reveal times, freeze or reopen a round, seed or disable tie-breaking, inspect validation/evaluation failures, publish or retract results, and expose a read-only audit bundle. These controls require authentication, authorization, audit logging, rate limits, transport security, and failure recovery. These controls are not implemented in Phase 2.

## Fairness and visibility

Phase 3 must define fairness before introducing rankings: how ties, late submissions, corrections, invalid plans, evaluator failures, hidden tests, shared-corridor congestion, and randomized tie-breaking are handled. Persist any random seed and publish the policy. Decide whether teams see only their own diagnostics, a public aggregate, delayed aggregate congestion, or a leaderboard, and apply the same visibility rules to all teams. Keep canonical semantic ordering independent of display ordering.

Fairness tests should include permutation-invariant evaluation, equal treatment of equivalent canonical/legacy single-site plans, deterministic multi-site shared-corridor allocation, reproducible reruns, and clear separation between instructional feedback and official grading. These are future acceptance criteria, not claims about the local practice server.

## Gymnasium/RL wrapper implications

A future Gymnasium/RL wrapper must choose whether an action is a complete weekly `TeamPlan`, a sequential site-building action, or a dispatch/recourse action. It must define observation and action spaces for multiple sites and generators, shared multi-agent corridor resources, masks for invalid IDs/references, period progression, terminal conditions, rewards, and the mapping from evaluator diagnostics to reward signals.

The wrapper must preserve evaluator versioning, deterministic seeds where applicable, server/evaluator parity, and a clear distinction between validation failures and environmental penalties. It should decide whether the RL environment calls the evaluator in-process, through a service boundary, or through a batch adapter, and how persistent rounds are represented. No Gymnasium support exists; the RL wrapper is not implemented, and the Phase 2 HTTP API is not an RL environment.

## Deployment and reproducibility

Only after the above policies are defined should the local process move behind authenticated deployment. Separate public scenario/static content from authenticated submissions and instructor operations. Package the fixture, evaluator version, configuration, normalized plans, semantic hashes, seeds, result artifacts, code revision, and environment metadata so a published result can be replayed.

## Research questions

Future work can study how teams trade connection size, corridor congestion, local generation, and flexibility; whether shared-corridor allocation gives stable teaching incentives; how visibility and tie policy affect perceived fairness; which scenario perturbations test robustness without becoming operationally misleading; and how human plans, optimization baselines, and learning agents compare under the same versioned evaluator.

## Migration principles

Keep `evaluate_week` and its JSON contracts as the semantic core. Treat the Phase 2 browser as a replaceable client. Introduce persistence, authentication, instructor controls, multi-team policy, or RL adapters only with explicit versioning, order-invariance tests, replayable artifacts, and a documented fairness policy. Keep the local practice and no-official-ERCOT disclaimer until a separate validated system has earned a different boundary.
