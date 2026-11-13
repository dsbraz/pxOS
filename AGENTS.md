# AGENTS.md

## Rule 1 — Think Before Coding
No silent assumptions. State what you're assuming. Surface tradeoffs. Ask before guessing. Push back when a simpler approach exists.

## Rule 2 — Simplicity First
Minimum code that solves the problem. No speculative features. No abstractions for single-use code. If a senior engineer would call it overcomplicated — simplify.

## Rule 3 — Surgical Changes
Touch only what you must. Don't "improve" adjacent code, comments, or formatting. Don't refactor what isn't broken. Match existing style.

## Rule 4 — Goal-Driven Execution
Define success criteria. Loop until verified. Don't tell the Agent what steps to follow, tell it what success looks like and let it iterate.

## Integration policy
While the team consists only of the maintainer and the agent, integrate directly into main. Require pull requests only when other people join the team, not when the product reaches production. Run relevant checks before integration.

## Commit messages
Do not mention agent or AI participation in commit subjects, bodies, or trailers. Do not add agent credits, generated-by notices, or Co-authored-by trailers identifying agents. Describe only the change and its rationale.

## Spikes
Spikes are temporary experiments and do not need CI. Keep their dependencies, tooling, validation instructions, and results inside their own directories under spikes/. Do not add spike-specific jobs or dependency-update automation to repository-wide configuration. Validate experiments locally as needed to answer their hypotheses; do not treat experimental technology as approved product infrastructure.
