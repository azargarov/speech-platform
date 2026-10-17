# STT model alias ownership

Status: accepted for M02 design; implementation authorization remains separate.

## Context

M01 separates public and private contracts and uses stable model aliases. Its internal STT description said the Gateway translates aliases, while the STT worker owns model configuration and lifecycle. Resolving aliases in Gateway would couple public routing to model inventory and make worker replacement less independent.

## Decision

The Gateway forwards a stable model alias unchanged. STT owns alias validation/default selection and maps aliases to immutable model identity and artifact metadata. Public and internal API schemas do not expose engine model IDs, artifact paths or adapter options.

## Consequences

Adding or changing a backend does not require public contract changes. STT reports unknown aliases and effective model capabilities. Gateway configuration does not mirror the model catalog. The private API wording is reconciled to this ownership.

## Alternatives

Gateway mapping gives centralized routing but duplicates model lifecycle state and couples the Gateway to provider metadata. Forwarding opaque native model IDs is simpler but violates the stable alias boundary. Both are rejected.
