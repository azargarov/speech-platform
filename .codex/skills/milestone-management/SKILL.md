---
name: milestone-management
description: Plan, track, validate or close Speech Platform milestones using bounded
  scope, explicit acceptance evidence and user decision gates.
---

# milestone-management

## Triggers

Use for milestone creation, status changes, verification records, user validation or closeout. A small authorized fix can use a task record without creating a milestone.

## Required inputs

User objective/authorization, PLANS.md, current milestone artifacts, prior work and available verification evidence.

## Workflow

1. Inspect current state and prior approvals. Identify the authorized milestone, inclusions, exclusions and dependencies; preserve existing work if sequencing changes.
2. Create/update `docs/milestones/<ID>/plan.md` with bounded scope, acceptance criteria, risks and commands. Update PLANS.md without advancing automatically.
3. Maintain implementation.md as an actual change record, including deviations and preserved work. Link significant design decisions rather than duplicating ADRs.
4. Maintain verification.md with executed commands, environment, results and evidence provenance. Distinguish OBSERVED, INTERPRETATION and NOT ESTABLISHED per the methodology; historic/user-reported evidence is explicitly attributed.
5. Prepare user-validation.md with exact commands, expected outcomes and pending reviewer/date/feedback. Record actual feedback only when received.
6. Write result.md against acceptance criteria and unresolved items. Leave completion pending until user validation and explicit closeout approval; do not begin the next milestone or commit without corresponding user approval.

## Expected outputs

PLANS.md plus plan, implementation, verification, user-validation and result records; explicit current status and next user decision.

## Validation checklist

- [ ] Scope and acceptance bounded; all five artifacts agree with PLANS.md.
- [ ] Evidence has provenance; pending validation/approval is visible.
- [ ] No automatic milestone progression, fabricated acceptance or unauthorized commit.

## Stop and escalation

Escalate scope expansion, incompatible acceptance criteria or missing required validation. A user status question is not approval to advance; record blockers without erasing completed work.

For stage gates and proportional artifacts, consult [methodology](../../../docs/development/methodology.md). Repository rules remain in [AGENTS.md](../../../AGENTS.md).
