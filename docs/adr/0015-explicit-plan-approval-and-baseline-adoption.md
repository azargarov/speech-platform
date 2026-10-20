# ADR 0015: Explicit plan approval and baseline adoption

- Status: accepted for M01F-A architecture; implementation separately gated
- Date: 2026-10-20

## Context

An update approval must remain bound to the exact reviewed target and observed
before-state. The existing healthy M01E deployment has no managed generation
record, so treating an absent pointer as permission to adopt it implicitly
would make provenance and rollback eligibility ambiguous.

## Decision

- Require a plan ID supplied in a separate invocation to approve an update.
  Bind it to immutable target, selected services, per-service current vector,
  runtime/config/secret identity, artifacts, compatibility, resource
  observations and policy/schema versions. Any stale guard requires a new
  plan and approval.
- Define explicit `adopt-baseline` as a separately approved, read-only
  registration of a complete healthy M01E deployment. It verifies exact image,
  model, configuration and runtime identities plus health evidence; refuses
  ambiguity, unhealthy, drifted, partial or already managed state; and issues
  no Docker lifecycle command. Adoption persists generation and operation
  records only after explicit approval and while holding the shared per-project
  deployment lock; it never creates, starts, stops, restarts, pulls, removes or
  otherwise changes Docker state.
- Keep `recover/status` read-only for Docker and durable installed state.
  Reconciliation that writes generation, pointer or operation records is a
  distinct planned and explicitly approved operation, protected by that same
  shared project lock, and invokes no Docker lifecycle command.
- Persist adoption provenance and observed health evidence as the initial
  immutable generation. It is rollback eligible only while every exact
  restoration input is retained and reverified.
- Never adopt automatically when state is absent or during update planning.

## Alternatives considered

- Implicit adoption on first update: rejected because an update could silently
  bless drift or partial state as known-good history.
- Approval through an interactive prompt only: rejected because the approval
  must be explicitly tied to a stable reviewable identity across invocations.
- Treating the operational STT baseline file alone as an installed
  generation: rejected because it does not prove a complete M01E platform
  vector or retained restoration inputs.

## Consequences

Approval is auditable and expires on changed inputs. Adoption adds a deliberate
operator step and can fail when prior provenance or immutable inputs are
missing. Adoption and approved durable reconciliation can write host-local
records but remain read-only with respect to Docker lifecycle.
