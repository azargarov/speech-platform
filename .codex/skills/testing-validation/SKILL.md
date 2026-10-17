---
name: testing-validation
description: Plan and execute risk-based verification for Speech Platform changes
  and record reproducible evidence, including failures and unavailable checks.
---

# testing-validation

## Triggers

Use when behavior changes, acceptance criteria are defined, or verification evidence is requested. For pure documentation changes use structural, link and consistency checks rather than inference tests.

## Required inputs

Diff or intended change, acceptance criteria, failure risks, existing tests, available tools and permitted environments.

## Workflow

1. Map risks and acceptance criteria to checks. Choose unit tests for isolated logic, integration tests for real boundaries and contract tests for API behavior where appropriate.
2. Include negative/boundary cases and regression coverage for fixed defects. Avoid tests that merely repeat implementation or inspect wording instead of behavior.
3. Define reproducible commands and prerequisites. Keep GPU-independent verification in CI; GPU/runtime tests need an available authorized environment and separate evidence.
4. Execute focused checks and the relevant repository verification target. For application changes use `make verify PYTHON=.venv/bin/python`; for governance use `make governance-check PYTHON=.venv/bin/python` and the installed skill validator when available.
5. When a check fails, preserve the failure, diagnose and fix in scope, then rerun affected checks. Do not remove checks to claim success. Record blocked/unrun checks and continue independent work.
6. Record command, environment, exit status and useful output. Label OBSERVED execution, INTERPRETATION and NOT ESTABLISHED using the methodology. Inspection alone never establishes a passing test.

## Expected outputs

Risk-to-check rationale, meaningful tests if needed, reproducible commands and an evidence record with failures and remaining gaps.

## Validation checklist

- [ ] Relevant success, error and boundary paths covered.
- [ ] Commands actually ran and results match captured output.
- [ ] Local, CI, GPU and user validation claims remain distinct.

## Stop and escalation

Escalate when acceptance needs an unavailable environment or out-of-scope fixes. Do not run destructive integration checks or mutate running services without authorization.

For stage gates and proportional artifacts, consult [methodology](../../../docs/development/methodology.md). Repository rules remain in [AGENTS.md](../../../AGENTS.md).
