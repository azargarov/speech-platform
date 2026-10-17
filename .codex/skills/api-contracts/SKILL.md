---
name: api-contracts
description: Design or change Speech Platform public or internal HTTP contracts with
  OpenAPI validation, explicit compatibility and provider-independent behavior.
---

# api-contracts

## Triggers

Use when adding/changing API operations, schemas, errors, capabilities or cancellation semantics, including worker contracts. Internal function signatures alone do not trigger this skill.

## Required inputs

Consumer use cases, existing OpenAPI documents, supported capabilities, compatibility requirements and configurable limits/deadlines.

## Workflow

1. Inspect current public and internal specifications and consumers. Describe the consumer outcome without exposing provider engine details.
2. Edit the contract before implementing handlers. Specify versioned paths, request/response schemas, media types, authentication and consistent error schemas.
3. Define input limits, language behavior, timestamps/streaming capabilities, deadlines, cancellation and unavailable-feature behavior. Identify configured defaults versus protocol invariants.
4. Assess compatibility: preserve existing fields and semantics; use additive changes only when consumers tolerate them. Obtain approval for breaking changes and document migration/versioning.
5. Validate affected OpenAPI documents with the repository validator/dependencies using `make test PYTHON=.venv/bin/python`, or a focused installed OpenAPI validator. If unavailable, inspect structure and report semantic validation as NOT ESTABLISHED.
6. Plan/run contract tests for implemented behavior, including errors and boundaries. Keep reserved future operations distinct from installed routes and update consumer guidance.

## Expected outputs

Validated versioned contracts, compatibility assessment, capability/cancellation semantics and relevant contract-test evidence.

## Validation checklist

- [ ] Public and private contracts are separate; stable public IDs conceal engines.
- [ ] Schemas, errors, limits, auth and cancellation are explicit.
- [ ] Actual validator/test outcomes are recorded; specification validity is not runtime conformance.

## Stop and escalation

Escalate unapproved breaking changes or ambiguous consumer semantics before implementation. Missing validator/runtime is a recorded limitation, not a passing result.

For stage gates and proportional artifacts, consult [methodology](../../../docs/development/methodology.md). Repository rules remain in [AGENTS.md](../../../AGENTS.md).
