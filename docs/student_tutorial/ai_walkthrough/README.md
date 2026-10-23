# AI-agent walkthrough on the IEEE-14 demo

Six prompts a student gave a coding agent, and the agent's replies, from one
session on 2026-10-19. The tutorial section "Walk through the workflow with an
AI agent" shows shortened versions of these; the files here are complete.

**Recorded under an earlier draft.** The replies are kept exactly as the agent
gave them. Since the session, the README was updated (it then still described
the retired six-hour setup, which the agent noticed), and the generator rules
changed to $2.0M/MW with at most two hours of full output per day (the agent
quotes $1.5M/MW). The commands are shortened in places; for example
`ercot-game-preview` needs `--submissions-dir` and `--output` (see the tutorial).

- **Agent:** a Claude coding agent (Opus 5.5), running in a fresh clone of this
  repository with the package installed in a virtual environment. It had not
  seen this repository before the first prompt. The copy left out this folder
  and the tutorial section that quotes it, so the agent could not reuse
  earlier answers.
- **Data:** `data/teaching/ieee14_demo_representative` (five representative days, 120 hourly periods) with
  `data/teaching/dispatch_scoring_rules_ieee14_demo_representative_v1.json`.
- **Prompts** (`NN_prompt.md`) are exactly what the agent received.
- **Replies** (`NN_reply.md`) are verbatim. The agent was asked to call its
  virtual environment `.venv/`.

The agent created only `runs/` and `work/` in its copy; those outputs are not
kept here. To reproduce, clone the repository, install it (`pip install -e .`
plus `highspy`), start a coding agent in the repository folder, and paste the
prompts in order. Replies will differ in wording, and the numbers should match.
