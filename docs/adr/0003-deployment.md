# Compose and offline inference

Status: accepted for M01 implementation; user validation pending.

Decision: Use one host and Docker Compose with private internal worker networks, no worker published ports, nonroot users, dropped capabilities, read-only root filesystems and bounded resources. ADR 0009 specifies separate Gateway-to-STT and Gateway-to-TTS networks. No Kubernetes. Model provisioning is separate from runtime. No changes to Ollama or Dify.

Consequences: small dependencies and independent process lifecycle; later milestones must preserve contracts and extend acceptance checks.
