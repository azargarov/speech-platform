# Strict configuration and truthful readiness

Status: accepted for M01 implementation; user validation pending.

Decision: Reject missing, unknown and duplicate configuration fields. Keep deployment values in YAML/Compose. Structured event logging excludes payloads. Health measures process availability; readiness measures usable inference. Prometheus-compatible instrumentation will accompany real request handling.

Consequences: small dependencies and independent process lifecycle; later milestones must preserve contracts and extend acceptance checks.
