# Separate public and internal contracts

Status: accepted for M01 implementation; user validation pending.

Decision: Version public API at /v1 and worker API at /internal/v1. Platform aliases and capabilities hide provider engine details. Internal deadlines are explicit headers; workers remain private. Contracts describe future operations and are not proof of implementation.

Consequences: small dependencies and independent process lifecycle; later milestones must preserve contracts and extend acceptance checks.
