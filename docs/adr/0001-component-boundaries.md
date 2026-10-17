# Independent gateway and workers

Status: accepted for M01 implementation; user validation pending.

Decision: Go standard HTTP gateway and two Python worker entry points. Dependency injection at the readiness boundary; provider interfaces will be introduced alongside concrete inference needs. Shared worker mechanics avoid duplicated transport while preserving independent inference modules.

Consequences: small dependencies and independent process lifecycle; later milestones must preserve contracts and extend acceptance checks.
