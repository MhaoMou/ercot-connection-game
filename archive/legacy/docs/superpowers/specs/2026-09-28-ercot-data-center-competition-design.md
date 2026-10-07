# ERCOT Data-Center Interconnection Competition Design

## 1. Purpose and scope

This project designs a competitive power-systems course game in which student teams operate data-center companies seeking to connect load to an ERCOT-based network. Each week, teams submit a structured connection and generation plan. An authoritative evaluator checks the plan against network and operating constraints, applies flexible-connection curtailment when permitted, computes revenue and penalties, and updates each team's persistent state.

The first deployment prioritizes educational value while preserving a clean path to a Gymnasium-compatible reinforcement-learning environment and a research paper. The game should support more than 30 teams and run for at least one month, potentially for a full semester.

## 2. Core design principles

1. The student decision should be simple enough to understand in one class period, while the evaluator can grow in physical and economic fidelity.
2. Official evaluation must be deterministic and reproducible from a versioned scenario, configuration, submission, and evaluator version.
3. Feasibility should be graded continuously through transparent recourse costs rather than by assigning every infeasible plan zero revenue.
4. Flexible connection should be an explicit strategic choice, not a hidden repair mechanism.
5. Student-facing software, official evaluation, and research environment interfaces should be separate components.
6. The official process should be batch-based: freeze a weekly scenario and all submissions before scoring.
7. Official weekly submissions are simultaneous; shared congestion must not be resolved by accidental web-submission order.

## 3. Game timeline

The course may last a semester, and the game season may last at least one month. The game is not a fixed four-week exercise. The repeated weekly cycle is:

1. Publish the next ERCOT scenario, available network information, prices, and rules.
2. Teams inspect the state and submit or revise their persistent portfolio.
3. Freeze submissions at the deadline.
4. Evaluate all teams against the same frozen scenario and evaluator version.
5. Publish scores, rankings, diagnostics, and remaining resources.
6. Carry the resulting state into the next week.

Persistent state includes connected load, generator investments, cumulative revenue, remaining capital, remaining intervention budget, previous curtailment, reliability history, and accepted connection commitments.

The instructor can increase difficulty over time without changing the interface. Early weeks may use deterministic scenarios and detailed feedback. Later weeks may include multiple operating scenarios, outages, changing prices, limited information, and expansion decisions.

## 4. Student action and submission format

Each weekly submission is structured data rather than executable code. The first version should contain:

- connection bus or zone;
- requested data-center capacity in MW;
- normalized load profile or selected profile class;
- optional generator type, location, capacity, and marginal cost;
- flexible-connection intervention budget `K`;
- maximum curtailment depth `mu`;
- optional maximum curtailment or service-quality commitment.

The web interface should validate syntax and obvious bounds before accepting a submission. Students should be able to use a practice evaluator, but the official evaluation should occur only after the weekly deadline.

The first version should not allow student-uploaded executable code. A later research mode may support containerized strategy submissions with strict CPU, memory, time, and network limits.

## 5. Flexible-connection recourse

The infeasibility mechanism adapts the flexible-connection formulation in Gu, Chen, and Qin, “The Role of Flexible Connection in Accelerating Load Interconnection in Distribution Networks” (arXiv:2510.11476). The paper models a load profile as a capacity multiplied by a normalized time-varying profile, limits the number of intervention slots, and bounds curtailment depth. Its key insight is that rare, bounded interventions can unlock substantial hosting capacity.

For team `i`, let `K_i` be the maximum number of curtailment interventions and `mu_i` the maximum fraction of connected capacity that can be curtailed in any intervention. Let `u_i(t)` be the load modification, where negative values represent curtailment:

```text
u_i(t) <= 0
number of nonzero u_i(t) <= K_i
|u_i(t)| <= mu_i * C_i
```

The official evaluator should:

1. Test the submitted plan with no curtailment.
2. If feasible, operate it normally.
3. If infeasible, find a feasible curtailment vector satisfying the team's `K_i` and `mu_i` limits.
4. Among feasible repairs, minimize curtailed energy or the economic value lost from curtailment.
5. Compute revenue from served load and subtract a flexibility fee and curtailment cost.
6. If no feasible repair exists within the contract, apply a residual unserved-energy penalty to the remaining violation.

For simplified networks, the evaluator may use the paper's dynamic-hosting-capacity idea: identify the critical time slots with the lowest residual hosting capacity and curtail the minimum amount needed to lift them to the next supported capacity level. For the full ERCOT model, this becomes a network-constrained optimization problem with generator dispatch, line constraints, voltage or security constraints as appropriate, and scenario-specific recourse.

`K` should be a persistent budget over the competitive season, not reset automatically each week. The game may impose a fee for flexibility so that choosing maximum curtailment is not always optimal.

The paper's distribution-feeder assumptions should not be presented as a literal ERCOT model. The game uses its flexible-connection principle and intervention-budget formulation as an adaptation to an ERCOT-based network.

## 6. Shared-bus allocation

When multiple teams request capacity at the same bus or create a shared network bottleneck, the evaluator should process all weekly submissions jointly. It should not use first-come-first-served by default, because that rewards submission timing rather than power-system strategy and can produce arbitrary outcomes from small timing differences.

The allocation layer runs before individual team recourse:

1. Freeze all team submissions at the deadline.
2. Identify buses and shared network constraints whose aggregate requests are infeasible.
3. Allocate available hosting capacity using a published fairness rule.
4. Apply each team's flexible-connection curtailment and generator recourse to the allocated plan.
5. Compute revenue and penalties from the resulting served and curtailed energy.

The first implementation should use proportional rationing at a directly overloaded bus. If the bus can accommodate only a fraction `rho` of the aggregate requested capacity, each affected team initially receives:

```text
served_capacity_i = rho * requested_capacity_i
```

For example, if three teams each request 100 MW and only 180 MW is available, each receives 60 MW before individual flexibility and recourse are applied. This rule is simple, transparent, and independent of submission order.

The more general implementation should use a joint optimization that maximizes total declared team value subject to network constraints, with a weighted max-min fairness tie-breaker. This allows allocations to differ when teams have different load profiles, generators, or flexibility commitments while preventing arbitrary winner-takes-all outcomes.

First-come-first-served may be introduced only as an explicit reservation or auction mechanism in which priority is part of the published game rules. It should not arise accidentally from the order in which students submit web forms.

## 7. Revenue and ranking

For each team and week, compute:

```text
score = IT value of served energy
        - normal energy cost
        - generator operating cost
        - congestion or network-use cost
        - flexibility fee
        - curtailment cost
        - residual unserved-energy penalty
```

The exact coefficients should be published before the season begins. The penalty ordering should satisfy:

```text
unserved-energy penalty >> curtailment cost > emergency energy cost > normal energy cost
```

The scoring function must prevent a team from earning more by submitting an infeasible plan than by submitting its feasible repaired version. Feasibility diagnostics should be decomposed into connection, thermal, voltage, generation-adequacy, service, and budget components.

The final grade should be based primarily on cumulative revenue ranking. Secondary metrics should be reported for learning and analysis: served energy, curtailed energy, intervention count, maximum violation, reliability, capital efficiency, and score improvement.

## 8. System architecture

The system has five components:

### Student web interface

Displays the current network snapshot, candidate locations, prices, available resources, rules, previous scores, and remaining team state. It provides a structured form and practice-evaluation feedback.

### Game API and database

Authenticates teams, enforces deadlines, stores immutable submissions, tracks persistent state, exposes results, and records evaluator versions. PostgreSQL is suitable for the first implementation.

### Evaluation service

A Python service validates submissions, runs network and economic calculations, solves flexible-curtailment recourse, computes scores, and emits diagnostics. Official evaluations should run as isolated jobs so one slow or malformed submission cannot disrupt the class.

### Electrify execution layer

Electrify may host heavier simulations or batch workers. The preferred interface is:

```text
web API -> job queue -> evaluator worker -> Electrify batch job -> result artifact -> database
```

The pilot may run the evaluator on one controlled server if that is more reliable. An interactive SSH session should not be a dependency of the student-facing web server.

### Instructor dashboard

Provides controls to open and close weeks, freeze scenarios, publish results, inspect failed jobs, rerun a submission, override a corrupted result, export grades, and view aggregate learning metrics.

The official score is reproducible from:

```text
versioned scenario + game configuration + team action + evaluator version
```

## 9. Weekly operating modes

The platform should distinguish practice mode from official mode.

Practice mode allows hypothetical submissions and approximate feedback. It may run against a public or perturbed scenario.

Official mode uses the frozen weekly scenario, closes submissions at the deadline, evaluates every team under the same conditions, and stores an auditable result.

Student results should reveal enough information to support learning without exposing other teams' detailed strategies.

## 10. Gymnasium/RL extension

The evaluator should be separated from a Gymnasium wrapper. A weekly decision is one environment step:

```python
obs, info = env.reset(seed=...)
obs, reward, terminated, truncated, info = env.step(action)
```

The observation may include network headroom by candidate bus, prices or congestion indicators, remaining capital, remaining intervention budget, portfolio state, previous curtailment, and information available under the scenario rules.

The initial action space can be structured as discrete-continuous decisions: bus or zone, load capacity, generator type, generator capacity, integer `K`, and continuous `mu`.

The environment should accept broad actions, apply network feasibility and flexible-curtailment recourse, and return interpretable diagnostics rather than requiring the policy to satisfy all constraints directly. The `info` object should include feasibility status, binding constraints, curtailed energy, intervention timestamps, generator dispatch, unserved energy, cost decomposition, evaluator version, and scenario ID.

The environment should support both a short fixed horizon and a longer semester-style horizon. `K`, capital, and portfolio state must be persistent across steps.

Potential research baselines include maximum-feasible-load, cheapest-energy, reliability-first, perfect-information optimization, myopic RL, and recurrent or belief-state policies under uncertainty. Human-only, agent-only, and mixed human-agent competition can all use the same evaluator.

## 11. Recommended implementation phases

### Phase 1: Offline evaluator

Build a deterministic evaluator with versioned input/output files, a small ERCOT-derived model, structured plans, basic network checks, and the flexible-curtailment repair mechanism.

### Phase 2: Local practice interface

Add a lightweight web or notebook interface so a team can submit a plan, see diagnostics, and understand the score decomposition.

### Phase 3: Official multi-team service

Add authentication, persistent database state, deadline enforcement, batch evaluation, instructor controls, ranking, audit logs, and exports.

### Phase 4: Electrify integration

Move heavy or parallel batch jobs to Electrify only after the local evaluator and failure recovery are stable.

### Phase 5: Research wrapper

Freeze the evaluator API, add Gymnasium wrappers, scenario seeds, benchmark policies, and experiment logging.

## 12. Design risks and safeguards

- Solver failures: retain a deterministic fallback evaluator and mark incomplete results rather than silently assigning scores.
- Unequal information: publish the information available to all teams and freeze the official scenario before evaluation.
- Exploitative plans: cap capacity, capital, flexibility, and emergency recourse; test for profitable pathological behavior.
- Shared congestion: evaluate all teams jointly and use a published order-independent allocation rule; never rely on accidental submission timing.
- Excessive complexity: begin with representative operating periods and a small scenario set, then expand.
- Reproducibility: version network data, scenario generation, game parameters, solver settings, and evaluator code.
- Privacy and competition: publish aggregate or anonymized information about other teams, not their full actions.

## 13. Research questions enabled by the platform

The design supports questions such as:

1. How much hosting capacity is unlocked by limited-frequency, bounded-depth flexible connection?
2. How do competitive agents trade off connection size, location, reliability, and flexibility?
3. Does a persistent intervention budget produce more realistic long-horizon planning behavior?
4. How do human strategies compare with optimization and RL policies?
5. How does uncertainty change the value of firm versus flexible interconnection?
