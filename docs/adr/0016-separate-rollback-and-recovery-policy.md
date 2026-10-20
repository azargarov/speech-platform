# ADR 0016: Separate rollback operations and conservative recovery

- Status: accepted for M01F-A architecture; implementation separately gated
- Date: 2026-10-20

## Context

An update may partially activate services, and interruptions can occur between
runtime activation, readiness, installed-pointer promotion and journal
terminal persistence. Automatically resuming or rolling back would issue new
mutations from uncertain evidence. Update and rollback failures also need
separate provenance.

## Decision

- Successful operations and their generations are terminal and immutable.
  Every transition is correlated to its operation ID.
- Rollback is a new separately planned and approved operation linked to its
  source operation and exact target generation. It is not a transition that
  mutates a successful or failed update operation.
- Keep update outcomes (`REJECTED`, `FAILED`, `PARTIAL`, `UNKNOWN`,
  `SUCCEEDED`) separate from rollback eligibility assessments. `ROLLBACK_READY`
  may be attached to or linked from an update result, but never replaces or
  obscures that result, proves current eligibility, authorizes mutation or
  promises restoration inputs remain available. Eligibility is rechecked in a
  separate rollback plan.
- Represent update outcomes (`REJECTED`, `FAILED`, `PARTIAL`, `UNKNOWN`,
  `SUCCEEDED`) separately from rollback outcomes (`REJECTED`,
  `ROLLBACK_FAILED`, `PARTIAL`, `UNKNOWN`, `ROLLED_BACK`). Preserve original
  failure and rollback failure independently.
- After interruption, `recover/status` inspects runtime and durable records
  read-only and never changes Docker, generations, installed pointers or
  operation records. If
  reconciliation requires writing a generation, pointer or operation record,
  first produce a distinct plan and obtain explicit approval; perform the
  approved record-only reconciliation under the shared per-project lock. Never
  auto-resume, auto-rollback, blindly replay a command, or perform automatic
  GPU reset/retry.
- Promote installed state only after selected and untouched service identities,
  compatibility, health and applicable bounded smoke are verified, immutable
  generation and pointer are durable, and terminal success is persisted.

## Alternatives considered

- Automatic rollback on update failure: rejected because a second mutation
  requires independent operator judgment and may be unsafe after uncertain GPU
  cleanup or incomplete prior inputs.
- Resume the interrupted command sequence: rejected because command result
  absence does not establish whether Docker applied it.
- Reuse update operation states for rollback: rejected because it overwrites
  causal history and makes original and restoration errors hard to distinguish.

## Consequences

Recovery is conservative and may require operator diagnosis even where runtime
appears recoverable. Operation history remains attributable, and every further
write or lifecycle mutation has fresh planning and approval. The state store
and runtime cannot be committed atomically, so read-only inspection plus
explicitly approved record reconciliation is required; reconciliation itself
does not invoke Docker lifecycle operations.
