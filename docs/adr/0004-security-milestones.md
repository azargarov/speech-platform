# Fail closed during foundation

Status: accepted for M01 implementation; user validation pending.

Decision: Expose health only until authentication and routing land in M04. Readiness remains 503 without providers. No audio persistence or transcript logging. Disabled auth configuration never exposes inference in M01.

Consequences: small dependencies and independent process lifecycle; later milestones must preserve contracts and extend acceptance checks.
