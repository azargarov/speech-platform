---
name: architecture-design
description: Design or review Speech Platform component boundaries, dependency direction,
  or significant architectural changes before implementation.
---

# architecture-design

## Triggers

Use when adding a component, replacing an inference provider, changing dependency direction or comparing meaningful architecture alternatives. A local naming cleanup does not require this workflow.

## Required inputs

Authorized problem, consumers, existing architecture/ADRs, affected contracts, deployment constraints and acceptance goals.

## Workflow

1. Inspect the relevant architecture and read [principles](../../../docs/architecture/principles.md); identify existing decisions and separate facts from assumptions.
2. Assign responsibilities to Gateway, STT, TTS and consumers. Draw or describe dependency direction, data flow and ownership of configuration, model lifecycle and data.
3. Describe failure modes: provider unavailable, overload, deadline, disconnect and cleanup. Include security and resource consequences proportionate to the change.
4. Compare the simplest viable design with meaningful alternatives, including trade-offs and operational cost. Separate application logic from infrastructure adapters; avoid speculative layers.
5. Write or update an ADR for significant decisions with context, decision, alternatives, consequences and status. For a small change, record a short rationale in the task record.
6. Define compatibility impact, testable acceptance criteria and a bounded implementation plan before changing behavior.

## Expected outputs

Design rationale, responsibility/dependency map, relevant data/failure flow, ADR when significant and implementation acceptance criteria.

## Validation checklist

- [ ] Every responsibility has an owner; STT and TTS remain independent.
- [ ] Public contracts hide providers and application logic stays outside the platform.
- [ ] Alternatives and failures were assessed; an ADR is present when warranted.

## Stop and escalation

Escalate unresolved ownership, a breaking contract or new scope before dependent implementation. Record unavailable evidence and continue independent design work; do not invent measurements.

For stage gates and proportional artifacts, consult [methodology](../../../docs/development/methodology.md). Repository rules remain in [AGENTS.md](../../../AGENTS.md).
