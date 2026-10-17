---
name: clean-code
description: Implement or refactor Speech Platform code into cohesive, testable modules
  while preserving explicit dependencies and existing behavior.
---

# clean-code

## Triggers

Use for application code implementation, code review or refactoring. Documentation-only work does not activate code refactoring.

## Required inputs

Authorized behavior, relevant code/configuration, contracts, existing tests and a proportional design/plan.

## Workflow

1. Identify the smallest affected modules and their responsibility; inspect callers and compatibility requirements before editing.
2. Keep cohesion high and coupling low. Pass dependencies explicitly; inject clocks, providers or transports when actual substitution/testing requires it. Do not mandate interfaces for every concrete type.
3. Keep mutable state owned by an instance with a clear lifecycle; remove hidden state and unnecessary globals. Validate deployment assumptions through configuration at startup.
4. Handle errors with useful context, explicit propagation and cleanup. Carry context/cancellation across I/O; do not log sensitive inputs as error detail.
5. Prefer a direct deterministic implementation over speculative extensibility. Justify new dependencies or abstractions with a present need.
6. Add focused behavioral/regression coverage, run relevant checks and update affected documentation. Review the resulting diff for unrelated changes.

## Expected outputs

Focused implementation or review findings, meaningful tests when behavior changes, verification evidence and updated documentation.

## Validation checklist

- [ ] Modules are small enough to test with explicit dependencies.
- [ ] No hidden mutable state or hardcoded deployment assumptions were added.
- [ ] Errors and cleanup are explicit; abstractions solve current needs.

## Stop and escalation

Stop dependent edits when intended behavior or compatibility cannot be determined. Escalate required breaking changes or scope expansion; do not redesign unrelated modules.

For stage gates and proportional artifacts, consult [methodology](../../../docs/development/methodology.md). Repository rules remain in [AGENTS.md](../../../AGENTS.md).
