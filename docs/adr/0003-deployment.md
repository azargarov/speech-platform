# Compose and offline inference

Status: accepted for M01 implementation; user validation pending.

Decision: Use one host and Docker Compose with an internal network, no worker published ports, nonroot users, dropped capabilities, read-only root filesystems and bounded resources. No Kubernetes. Model provisioning is separate from runtime. No changes to Ollama or Dify.

Consequences: small dependencies and independent process lifecycle; later milestones must preserve contracts and extend acceptance checks.
