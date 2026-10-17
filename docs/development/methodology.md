# Engineering methodology

Canonical workflow: Inspect → Design → Plan → Implement → Verify → User Validate → Closeout.

[AGENTS.md](../../AGENTS.md) supplies mandatory repository rules. Skills under `.codex/skills/` supply task-specific workflows; load only relevant instructions. Current work authorization and milestone state live in [PLANS.md](../../PLANS.md). Older milestone records remain historical evidence, never implied permission to resume work.

## Stages and gates

| Stage | Entry criteria | Required artifacts and work | Exit criteria / decision gate |
| --- | --- | --- | --- |
| Inspect | Authorized task and repository available | Inspect working state, instructions, relevant code/contracts, tools, prior evidence; record constraints and existing work | Scope and unknowns identified; no unrelated changes |
| Design | Problem and consumers understood | Responsibilities, dependency direction, data flow, failure modes, privacy/operations impact and compatibility; alternatives with trade-offs; ADR for significant decisions | Design supports acceptance criteria; unresolved consequential decisions go to user |
| Plan | Design sufficient for bounded work | Milestone plan with inclusions, exclusions, acceptance checks, risks and validation commands | Authorization covers implementation scope; milestone advancement requires explicit approval |
| Implement | Current stage authorized and plan actionable | Focused changes, tests and documentation; implementation record describing actual work and deviations | Reviewable changes satisfy planned scope; no silent scope expansion |
| Verify | Changes ready and prerequisites known | Run relevant formatting, static analysis, config/schema checks, tests and build checks; record commands, versions, exit codes and relevant output | Required checks pass or blockers are explicitly recorded; failures prevent a passing claim |
| User Validate | Verification record and concrete validation steps available | user-validation.md contains expected behavior, exact commands, reviewer feedback and environment | Actual user validation recorded; unresolved findings return to design/implementation |
| Closeout | Acceptance criteria met and user validation recorded | result.md compares criteria with evidence, limitations and explicit user closeout decision | User approves completion; no automatic next milestone or commit |

Milestones require `docs/milestones/<ID>/{plan,implementation,verification,user-validation,result}.md` and a current PLANS.md entry. Verification records include observed execution and distinguish local checks from CI or target-host validation. User validation and closeout can occur in one explicit user decision when the evidence and acceptance are clear. A commit requires explicit approval independently of milestone completion.

## Proportional work

For a small fix, documentation edit or local refactor, use a short design/plan in the task record or response, focused verification, and a clear final report. Do not create a milestone or ADR for every edit. Behavioral changes still require meaningful tests; pure documentation changes need link, consistency and format checks. A new externally visible contract, trust boundary, deployment strategy or component dependency normally warrants an ADR. Record significant decisions as proposed until accepted; preserve older decisions and supersede them explicitly.

## Failures and uncertainty

When a check fails, retain the failure evidence, diagnose it, fix only authorized causes and rerun affected checks. Broaden verification when changed behavior or unresolved risk justifies it. Do not disable a failing check to obtain a pass. An unrelated/environmental failure is recorded as blocked or not run; it cannot become a success by inspection. Continue independent safe work while a dependency is unavailable.

Use these evidence labels in milestone records:

- OBSERVED: directly inspected state, executed commands and outputs, or explicitly attributed user-reported measurements. State provenance, date and environment.
- INTERPRETATION: conclusions drawn from observations, including assumptions and their practical limits.
- NOT ESTABLISHED: unexecuted checks, unknown behavior, inaccessible environments, unvalidated performance or pending approval.

Never present another environment's historic results as a current run. Missing tools require a documented fallback or an explicit limitation. Ask only for information or authorization necessary to resolve a consequential blocked decision; routine implementation choices stay within existing scope.

## Scope and documentation changes

Compare discoveries against acceptance criteria. For necessary in-scope adjustments, update design/plan and explain the change. For new functionality, breaking compatibility or a new milestone, prepare a bounded proposal and obtain approval before dependent work. Preserve existing work instead of deleting it to fit a new sequence. Record reordering or pausing in PLANS.md without rewriting historical evidence.

Maintain contracts with API changes, configuration examples with validation changes, runbooks with deployment changes, and ADRs with significant design decisions. Update documentation in the same reviewable change. No secret values or private recordings belong in evidence. Never deploy, advance milestones or commit merely because verification passed.
